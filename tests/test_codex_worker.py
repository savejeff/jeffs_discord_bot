"""Offline tests for the private persistent tagged-agent Codex worker."""

from __future__ import annotations

import json
from datetime import datetime, timezone
import hashlib
from io import BytesIO
from pathlib import Path
import sqlite3
import zipfile

import pytest
from starlette.testclient import TestClient

from codex_agent_worker.agent_config import (
	load_agent_config,
	load_configured_agent_tags,
	prepare_agent_workspace,
)
from codex_agent_worker.application import create_app
from codex_agent_worker.artifacts import WorkspaceArtifactError, WorkspaceArtifactStore
from codex_agent_worker.codex_runner import (
	build_codex_command,
	find_codex_runtime_profile,
	parse_codex_events,
	read_codex_runtime_profile,
)
from codex_agent_worker.models import CodexRunResult, CodexRuntimeProfile
from codex_agent_worker.runner_registry import AgentRunnerRegistry
from codex_agent_worker.storage import WorkerStore
from discord_agent_bot.codex_worker_client import CodexWorkerClient, CodexWorkerError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeRunner:
	"""Return deterministic answers while recording tagged conversation resume state."""

	def __init__(self) -> None:
		self.calls: list[tuple[str, str | None]] = []
		self.cancelled = False

	def run(self, prompt: str, thread_id: str | None) -> CodexRunResult:
		"""Return one synthetic Codex event result for the worker loop."""
		self.calls.append((prompt, thread_id))
		return CodexRunResult(
			0,
			thread_id or "thread-one",
			f"answer: {prompt}",
			None,
			CodexRuntimeProfile("actual-model", "high", 1_777_000_000.0),
		)

	def current_runtime_profile(self) -> CodexRuntimeProfile | None:
		"""Return no active profile because synthetic turns complete immediately."""
		return None

	def latest_runtime_profile(self, _thread_id: str | None) -> CodexRuntimeProfile | None:
		"""Return no rollout profile because synthetic results persist it directly."""
		return None

	def cancel(self) -> None:
		"""Record orderly application shutdown without a real child process."""
		self.cancelled = True


def test_worker_websocket_queues_and_resumes_single_conversation(tmp_path: Path) -> None:
	"""Deliver delayed JSON answers while reusing one persisted Codex thread."""
	store = WorkerStore(tmp_path / "worker.db")
	runner = _FakeRunner()
	app = create_app(store=store, runner=runner)

	with TestClient(app) as client:
		assert client.get("/health").json() == {
			"status": "ok",
			"conversation": "tagged",
			"default_agent_tag": "dev1",
		}
		with client.websocket_connect("/ws") as websocket:
			websocket.send_json(
				{
					"type": "prompt",
					"request_id": "request-one",
					"prompt": "first question",
					"metadata": {
						"source": "test",
						"command": "respond",
						"user_id": "100000000000000001",
						"channel_id": "100000000000000002",
					},
				}
			)
			accepted = websocket.receive_json()
			response = websocket.receive_json()

		assert accepted["type"] == "accepted"
		assert accepted["metadata"]["queue_position"] == 1
		assert response == {
			"type": "response",
			"request_id": "request-one",
			"status": "completed",
			"answer": "answer: first question",
			"metadata": {
				"conversation": "tagged",
				"agent_tag": "dev1",
				"request": {
					"source": "test",
					"command": "respond",
					"user_id": "100000000000000001",
					"channel_id": "100000000000000002",
				},
			},
		}

		with client.websocket_connect("/ws") as websocket:
			websocket.send_json(
				{
					"type": "prompt",
					"request_id": "request-two",
					"prompt": "follow-up",
					"metadata": {"command": "summarize"},
				}
			)
			websocket.receive_json()
			assert websocket.receive_json()["answer"] == "answer: follow-up"

		with client.websocket_connect("/ws") as websocket:
			websocket.send_json(
				{
					"type": "prompt",
					"request_id": "request-three",
					"agent_tag": "new_agent",
					"prompt": "new conversation",
					"metadata": {"command": "prompt"},
				}
			)
			accepted = websocket.receive_json()
			response = websocket.receive_json()
			assert accepted["metadata"]["agent_tag"] == "new_agent"
			assert response["metadata"]["agent_tag"] == "new_agent"
			assert response["answer"] == "answer: new conversation"

		with client.websocket_connect("/ws") as websocket:
			websocket.send_json({"type": "agent_list", "request_id": "list-one"})
			agent_list_response = websocket.receive_json()

		assert agent_list_response == {
			"type": "agent_list",
			"request_id": "list-one",
			"agent_tags": ["dev1", "new_agent"],
		}

		with client.websocket_connect("/ws") as websocket:
			websocket.send_json(
				{
					"type": "status",
					"request_id": "status-one",
					"agent_tag": "new_agent",
				}
			)
			status_response = websocket.receive_json()

		assert status_response["type"] == "status"
		assert status_response["request_id"] == "status-one"
		assert status_response["status"]["state"] == "idle"
		assert status_response["status"]["model"] == "actual-model"
		assert status_response["status"]["reasoning_level"] == "high"
		assert status_response["status"]["runtime_profile_scope"] == "most_recent"
		assert status_response["status"]["queued"] == 0
		assert status_response["status"]["agent_tag"] == "new_agent"
		assert status_response["status"]["processed"] == 1
		assert status_response["status"]["recent_commands"][0]["command"] == "prompt"

	assert runner.calls == [
		("first question", None),
		("follow-up", "thread-one"),
		("new conversation", None),
	]
	assert runner.cancelled is True


def test_worker_management_configures_resets_and_deletes_agent(
	tmp_path: Path,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""Apply durable runtime settings and destructive workspace lifecycle requests."""
	config_path = tmp_path / "config_agents.json"
	config_path.write_text(
		json.dumps({"agents": {"dev1": {"model": None, "reasoning_level": None}}}),
		encoding="utf-8",
	)
	template = tmp_path / "template"
	(template / "docs" / "wiki").mkdir(parents=True)
	(template / "docs" / "wiki" / "README.md").write_text("baseline", encoding="utf-8")
	(template / "AGENTS.md").write_text("instructions", encoding="utf-8")
	workspaces_root = tmp_path / "workspaces"
	store = WorkerStore(tmp_path / "worker.db")
	monkeypatch.setenv("CODEX_AGENTS_CONFIG", str(config_path))
	monkeypatch.setenv("CODEX_WORKSPACE_TEMPLATE", str(template))
	monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
	app = create_app(store=store, workspaces_root=workspaces_root)

	with TestClient(app) as client:
		with client.websocket_connect("/ws") as websocket:
			websocket.send_json(
				{
					"type": "agent_config",
					"request_id": "config-one",
					"agent_tag": "dev1",
					"model": "gpt-5.6-sol",
					"reasoning_level": "low",
				}
			)
			assert websocket.receive_json() == {
				"type": "agent_management",
				"request_id": "config-one",
				"operation": "config",
				"agent_tag": "dev1",
				"model": "gpt-5.6-sol",
				"reasoning_level": "low",
			}
		workspace = workspaces_root / "dev1"
		assert store.get_agent_runtime_config("dev1") == ("gpt-5.6-sol", "low")
		(workspace / "modified.txt").write_text("remove me", encoding="utf-8")
		(workspace / "docs" / "wiki" / "README.md").write_text(
			"modified wiki",
			encoding="utf-8",
		)

		with client.websocket_connect("/ws") as websocket:
			websocket.send_json(
				{
					"type": "agent_reset",
					"request_id": "reset-one",
					"agent_tag": "dev1",
				}
			)
			assert websocket.receive_json()["operation"] == "reset"
		assert not (workspace / "modified.txt").exists()
		assert (workspace / "docs" / "wiki" / "README.md").read_text(
			encoding="utf-8"
		) == "baseline"

		with client.websocket_connect("/ws") as websocket:
			websocket.send_json(
				{
					"type": "agent_delete",
					"request_id": "delete-one",
					"agent_tag": "dev1",
				}
			)
			assert websocket.receive_json()["operation"] == "delete"
		assert not workspace.exists()
		assert store.get_agent_runtime_config("dev1") is None

		with client.websocket_connect("/ws") as websocket:
			websocket.send_json({"type": "agent_list", "request_id": "list-after"})
			assert websocket.receive_json()["agent_tags"] == []


def test_worker_stages_downloads_and_exports_request_scoped_uploads(
	tmp_path: Path,
) -> None:
	"""Keep thread attachment bytes inside the selected persistent agent workspace."""
	store = WorkerStore(tmp_path / "worker.db")
	runner = _FakeRunner()
	workspaces_root = tmp_path / "workspaces"
	app = create_app(store=store, runner=runner, workspaces_root=workspaces_root)
	request_id = "gateway_100000000000000020"
	inbound_content = b"input notes"
	outbound_content = b"generated report"
	outbound_sha256 = hashlib.sha256(outbound_content).hexdigest()
	outbound_directory = workspaces_root / "dev1" / "tmp" / "upload" / request_id
	outbound_directory.mkdir(parents=True)
	(outbound_directory / "report.md").write_bytes(outbound_content)

	with TestClient(app) as client:
		stage_response = client.post(
			"/artifacts/inbound",
			params={
				"agent_tag": "dev1",
				"request_id": request_id,
				"attachment_id": "100000000000000021",
				"filename": "notes.txt",
			},
			content=inbound_content,
		)
		assert stage_response.status_code == 201
		assert stage_response.json() == {
			"relative_path": (
				f"tmp/download/{request_id}/100000000000000021_notes.txt"
			)
		}

		with client.websocket_connect("/ws") as websocket:
			websocket.send_json(
				{
					"type": "prompt",
					"request_id": request_id,
					"agent_tag": "dev1",
					"prompt": "use the staged notes",
					"metadata": {
						"source": "discord_gateway",
						"command": "agent_thread",
					},
				}
			)
			websocket.receive_json()
			response = websocket.receive_json()

		assert response["attachments"] == [
			{
				"filename": "report.md",
				"content_type": "text/markdown",
				"size": len(outbound_content),
				"sha256": outbound_sha256,
			}
		]
		download_response = client.get(
			"/artifacts/outbound",
			params={
				"agent_tag": "dev1",
				"request_id": request_id,
				"filename": "report.md",
				"sha256": outbound_sha256,
			},
		)
		assert download_response.status_code == 200
		assert download_response.content == outbound_content

	assert (
		workspaces_root
		/ "dev1"
		/ "tmp"
		/ "download"
		/ request_id
		/ "100000000000000021_notes.txt"
	).read_bytes() == inbound_content


def test_workspace_policy_accepts_pdf_images_and_outbound_only_zip(tmp_path: Path) -> None:
	"""Accept signed document/image shapes but never stage a ZIP as agent input."""
	store = WorkspaceArtifactStore(tmp_path / "workspaces")
	request_id = "gateway_100000000000000020"
	accepted_inputs = (
		("100000000000000021", "document.pdf", b"%PDF-1.7\n%%EOF"),
		("100000000000000022", "photo.jpg", b"\xff\xd8\xffimage\xff\xd9"),
		("100000000000000023", "diagram.png", b"\x89PNG\r\n\x1a\nimage"),
	)
	for attachment_id, filename, content in accepted_inputs:
		path = store.stage_download(
			"dev1",
			request_id,
			attachment_id,
			filename,
			content,
		)
		assert path.endswith(f"{attachment_id}_{filename}")

	zip_buffer = BytesIO()
	with zipfile.ZipFile(zip_buffer, "w") as archive:
		archive.writestr("report.txt", "generated report")
	zip_content = zip_buffer.getvalue()
	with pytest.raises(WorkspaceArtifactError, match="unsupported"):
		store.stage_download(
			"dev1",
			"gateway_100000000000000030",
			"100000000000000031",
			"archive.zip",
			zip_content,
		)
	with pytest.raises(WorkspaceArtifactError, match="ZIP archive"):
		store.stage_download(
			"dev1",
			"gateway_100000000000000032",
			"100000000000000033",
			"renamed.png",
			zip_content,
		)

	upload_directory = store.prepare_upload_directory(
		"dev1",
		"gateway_100000000000000040",
	)
	(upload_directory / "bundle.zip").write_bytes(zip_content)
	artifacts = store.list_uploads("dev1", "gateway_100000000000000040")
	assert artifacts[0].filename == "bundle.zip"
	assert artifacts[0].content_type == "application/zip"


def test_worker_store_recovers_interrupted_job(tmp_path: Path) -> None:
	"""Recover interrupted work without counting offline time as active runtime."""
	database_path = tmp_path / "worker.db"
	current_time = [datetime(2026, 8, 29, 12, tzinfo=timezone.utc).timestamp()]
	store = WorkerStore(database_path, clock=lambda: current_time[0])
	store.enqueue("request-one", "prompt", "{}")
	assert store.claim_next() is not None
	current_time[0] += 30
	store.heartbeat_activity("request-one")
	store.close()

	current_time[0] += 300
	recovered_store = WorkerStore(database_path, clock=lambda: current_time[0])
	pending_status = recovered_store.status_snapshot(timezone.utc, "dev1")
	recovered = recovered_store.claim_next()
	recovered_store.close()

	assert pending_status["state"] == "idle"
	assert pending_status["queued"] == 1
	assert pending_status["total_active_seconds"] == 30
	assert recovered is not None
	assert recovered.request_id == "request-one"
	assert recovered.status == "processing"


def test_worker_store_migrates_existing_jobs_to_default_agent_tag(tmp_path: Path) -> None:
	"""Keep pre-routing queue records assigned to dev1 during schema migration."""
	database_path = tmp_path / "legacy-worker.db"
	connection = sqlite3.connect(database_path)
	connection.execute(
		"""
		CREATE TABLE jobs (
			request_id TEXT PRIMARY KEY,
			prompt TEXT NOT NULL,
			metadata_json TEXT NOT NULL,
			status TEXT NOT NULL,
			response TEXT,
			error TEXT,
			created_at REAL NOT NULL,
			updated_at REAL NOT NULL
		)
		"""
	)
	connection.execute(
		"""
		INSERT INTO jobs (
			request_id, prompt, metadata_json, status, created_at, updated_at
		) VALUES ('legacy', 'prompt', '{}', 'completed', 1, 2)
		"""
	)
	connection.commit()
	connection.close()

	store = WorkerStore(database_path)
	job = store.get_job("legacy")
	store.close()

	assert job is not None
	assert job.agent_tag == "dev1"


def test_worker_store_counts_only_codex_activity_and_reports_recent_commands(
	tmp_path: Path,
) -> None:
	"""Aggregate active child time independently from idle container uptime."""
	current_time = [datetime(2026, 8, 29, 12, tzinfo=timezone.utc).timestamp()]
	store = WorkerStore(tmp_path / "worker.db", clock=lambda: current_time[0])
	store.enqueue(
		"request-one",
		"private prompt",
		json.dumps(
			{
				"command": "respond",
				"user_id": "100000000000000001",
				"channel_id": "100000000000000002",
			}
		),
	)
	assert store.claim_next() is not None

	current_time[0] += 120
	store.heartbeat_activity("request-one")
	running = store.status_snapshot(timezone.utc, "dev1")
	assert running["state"] == "running"
	assert running["model"] is None
	assert running["runtime_profile_scope"] == "unavailable"
	assert running["processing"] == 1
	assert running["processed"] == 0
	assert running["total_active_seconds"] == 120
	assert running["today_active_seconds"] == 120

	current_time[0] += 60
	store.mark_completed("request-one", "answer")
	store.enqueue("request-two", "other prompt", "{}", "dev2")
	completed = store.status_snapshot(timezone.utc, "dev1")
	other = store.status_snapshot(timezone.utc, "dev2")
	store.close()

	assert completed["state"] == "idle"
	assert completed["processed"] == 1
	assert completed["completed"] == 1
	assert completed["total_active_seconds"] == 180
	assert completed["today_active_seconds"] == 180
	assert other["queued"] == 1
	assert other["processed"] == 0
	assert completed["recent_commands"] == [
		{
			"received_at": "2026-08-29T12:00:00+00:00",
			"command": "respond",
			"status": "completed",
			"user_id": "100000000000000001",
			"channel_id": "100000000000000002",
		}
	]


def test_worker_store_reports_observed_runtime_profile_by_agent_tag(tmp_path: Path) -> None:
	"""Persist actual Codex turn metadata without consulting requested config values."""
	store = WorkerStore(tmp_path / "worker.db")
	store.set_runtime_profile(
		CodexRuntimeProfile("gpt-actual", "xhigh", 1_777_000_000.0),
		"dev1",
	)
	status = store.status_snapshot(timezone.utc, "dev1")
	other_status = store.status_snapshot(timezone.utc, "dev2")
	store.close()

	assert status["model"] == "gpt-actual"
	assert status["reasoning_level"] == "xhigh"
	assert status["runtime_profile_scope"] == "most_recent"
	assert other_status["model"] is None
	assert other_status["runtime_profile_scope"] == "unavailable"


def test_codex_command_and_jsonl_parser_preserve_thread_and_final_message() -> None:
	"""Build the isolated CLI command and parse only supported observable events."""
	workspace = Path("/workspaces/dev1")
	command = build_codex_command(
		"codex",
		workspace,
		"thread-one",
		model="configured-model",
		reasoning_level="high",
	)
	stdout = "\n".join(
		[
			json.dumps({"type": "thread.started", "thread_id": "thread-one"}),
			json.dumps(
				{
					"type": "item.completed",
					"item": {"type": "agent_message", "text": "final answer"},
				}
			),
		]
	)

	assert command == [
		"codex",
		"exec",
		"--json",
		"--color",
		"never",
		"--skip-git-repo-check",
		"-C",
		str(workspace),
		"--dangerously-bypass-approvals-and-sandbox",
		"--model",
		"configured-model",
		"--config",
		'model_reasoning_effort="high"',
		"resume",
		"thread-one",
		"-",
	]
	assert parse_codex_events(stdout) == ("thread-one", "final answer", False)


def test_codex_command_supports_auto_review_with_workspace_sandbox() -> None:
	"""Configure self-approval through the current Codex auto-review settings."""
	workspace = Path("/workspaces/dev1")
	command = build_codex_command(
		"codex",
		workspace,
		None,
		permission_mode="auto-review",
	)

	assert command == [
		"codex",
		"exec",
		"--json",
		"--color",
		"never",
		"--skip-git-repo-check",
		"-C",
		str(workspace),
		"--sandbox",
		"workspace-write",
		"--ask-for-approval",
		"on-request",
		"--config",
		'approvals_reviewer="auto_review"',
		"-",
	]


def test_codex_command_rejects_unknown_permission_mode() -> None:
	"""Fail closed when configuration does not name a supported permission mode."""
	with pytest.raises(ValueError, match="Unsupported Codex permission mode"):
		build_codex_command(
			"codex",
			Path("/workspaces/dev1"),
			None,
			permission_mode="unknown",
		)


def test_project_config_starts_without_preconfigured_agents(tmp_path: Path) -> None:
	"""Keep a fresh worker workspace volume empty until its first requested tag."""
	config_path = PROJECT_ROOT / "config" / "config_agents.json"
	workspaces_root = tmp_path / "workspaces"
	registry = AgentRunnerRegistry(
		config_path=config_path,
		workspaces_root=workspaces_root,
		template_source=tmp_path / "unused-template",
		executable="codex",
		timeout_seconds=10,
		codex_home=tmp_path / "codex-home",
	)

	assert load_configured_agent_tags(config_path) == ()
	registry.prepare_configured_workspaces()
	assert registry.list_tags() == ()
	assert not workspaces_root.exists()


def test_rollout_parser_reads_actual_latest_turn_profile(tmp_path: Path) -> None:
	"""Use Codex turn-context evidence instead of the requested agent configuration."""
	workspace = tmp_path / "workspaces" / "dev1"
	workspace.mkdir(parents=True)
	rollout = tmp_path / "rollout-thread-one.jsonl"
	rollout.write_text(
		"\n".join(
			[
				json.dumps(
					{
						"timestamp": "2026-08-29T12:00:00Z",
						"type": "turn_context",
						"payload": {
							"cwd": str(workspace),
							"model": "gpt-previous",
							"effort": "medium",
						},
					}
				),
				json.dumps({"type": "response_item", "payload": {"content": "secret"}}),
				json.dumps(
					{
						"timestamp": "2026-08-29T12:01:00Z",
						"type": "turn_context",
						"payload": {
							"cwd": str(workspace),
							"model": "gpt-actual",
							"effort": "high",
						},
					}
				),
			]
		),
		encoding="utf-8",
	)

	profile = read_codex_runtime_profile(rollout, workspace)

	assert profile is not None
	assert profile.model == "gpt-actual"
	assert profile.reasoning_level == "high"


def test_runtime_profile_finder_bootstraps_persistent_codex_session(tmp_path: Path) -> None:
	"""Find a prior session profile after the worker database is upgraded or recreated."""
	workspace = tmp_path / "workspaces" / "dev1"
	workspace.mkdir(parents=True)
	session_directory = tmp_path / "codex-home" / "sessions" / "2026" / "08" / "29"
	session_directory.mkdir(parents=True)
	rollout = session_directory / "rollout-2026-08-29T12-00-00-thread-one.jsonl"
	rollout.write_text(
		json.dumps(
			{
				"timestamp": "2026-08-29T12:00:00Z",
				"type": "turn_context",
				"payload": {
					"cwd": str(workspace),
					"model": "gpt-persisted",
					"effort": "medium",
				},
			}
		),
		encoding="utf-8",
	)

	profile = find_codex_runtime_profile(
		tmp_path / "codex-home",
		workspace,
		"thread-one",
	)

	assert profile is not None
	assert profile.model == "gpt-persisted"
	assert profile.reasoning_level == "medium"


def test_tagged_agent_config_prepares_workspace_without_overwriting_wiki(
	tmp_path: Path,
) -> None:
	"""Load dev1 settings and preserve its initialized wiki across restarts."""
	config_path = tmp_path / "config_agents.json"
	config_path.write_text(
		json.dumps(
			{
				"agents": {
					"dev1": {
						"model": "configured-model",
						"reasoning_level": "medium",
						"codex_permission_mode": "auto-review",
					}
				}
			}
		),
		encoding="utf-8",
	)
	template = tmp_path / "workspace-template"
	(template / "docs" / "wiki").mkdir(parents=True)
	(template / "scripts").mkdir()
	(template / "AGENTS.md").write_text("initial instructions", encoding="utf-8")
	(template / "README.md").write_text("generic project", encoding="utf-8")
	(template / "scripts" / "requirements.txt").write_text("", encoding="utf-8")
	(template / "docs" / "wiki" / "README.md").write_text(
		"baseline",
		encoding="utf-8",
	)

	agent = load_agent_config(config_path, "dev1", tmp_path / "workspaces")
	prepare_agent_workspace(agent, template)
	(agent.workspace / "docs" / "wiki" / "README.md").write_text(
		"agent extension",
		encoding="utf-8",
	)
	(agent.workspace / "README.md").write_text("agent project", encoding="utf-8")
	(template / "AGENTS.md").write_text("updated instructions", encoding="utf-8")
	(template / "docs" / "wiki" / "README.md").write_text(
		"new baseline",
		encoding="utf-8",
	)
	(template / "data").mkdir()
	(template / "data" / ".gitkeep").write_text("", encoding="utf-8")
	prepare_agent_workspace(agent, template)

	assert agent.tag == "dev1"
	assert agent.model == "configured-model"
	assert agent.reasoning_level == "medium"
	assert agent.codex_permission_mode == "auto-review"
	assert agent.workspace == (tmp_path / "workspaces" / "dev1").resolve()
	assert (agent.workspace / "AGENTS.md").read_text(encoding="utf-8") == (
		"updated instructions"
	)
	assert (agent.workspace / "docs" / "wiki" / "README.md").read_text(
		encoding="utf-8"
	) == "agent extension"
	assert (agent.workspace / "README.md").read_text(encoding="utf-8") == "agent project"
	assert (agent.workspace / "data" / ".gitkeep").is_file()
	assert (agent.workspace / "scripts" / "requirements.txt").is_file()

	dynamic_agent = load_agent_config(
		config_path,
		"new_agent",
		tmp_path / "workspaces",
		allow_dynamic=True,
	)
	prepare_agent_workspace(dynamic_agent, template)
	assert dynamic_agent.model is None
	assert dynamic_agent.reasoning_level is None
	assert dynamic_agent.codex_permission_mode == "container-isolated"
	assert dynamic_agent.workspace == (tmp_path / "workspaces" / "new_agent").resolve()
	assert (dynamic_agent.workspace / "docs" / "wiki" / "README.md").read_text(
		encoding="utf-8"
	) == "new baseline"


def test_runner_registry_prepares_every_configured_workspace(
	tmp_path: Path,
) -> None:
	"""Seed future fixed-purpose agents before their first prompt is submitted."""
	config_path = tmp_path / "config_agents.json"
	config_path.write_text(
		json.dumps(
			{
				"agents": {
					"knowledge_base": {"codex_permission_mode": "workspace-write"},
					"release_notes": {"codex_permission_mode": "container-isolated"},
				}
			}
		),
		encoding="utf-8",
	)
	template = tmp_path / "template"
	(template / "docs" / "wiki").mkdir(parents=True)
	(template / "AGENTS.md").write_text("development policy", encoding="utf-8")
	(template / "docs" / "wiki" / "README.md").write_text(
		"wiki seed",
		encoding="utf-8",
	)
	workspaces_root = tmp_path / "workspaces"
	registry = AgentRunnerRegistry(
		config_path=config_path,
		workspaces_root=workspaces_root,
		template_source=template,
		executable="codex",
		timeout_seconds=10,
		codex_home=tmp_path / "codex-home",
	)

	registry.prepare_configured_workspaces()

	assert registry.list_tags() == ("knowledge_base", "release_notes")
	for agent_tag in registry.list_tags():
		workspace = workspaces_root / agent_tag
		assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == (
			"development policy"
		)
		assert (workspace / "docs" / "wiki" / "README.md").read_text(
			encoding="utf-8"
		) == "wiki seed"


def test_worker_store_keeps_conversation_ids_separate_by_agent_tag(tmp_path: Path) -> None:
	"""Persist independent conversation identifiers for future tagged agents."""
	store = WorkerStore(tmp_path / "worker.db")
	store.set_thread_id("thread-dev1", "dev1")
	store.set_thread_id("thread-dev2", "dev2")

	assert store.get_thread_id("dev1") == "thread-dev1"
	assert store.get_thread_id("dev2") == "thread-dev2"
	store.close()


def test_runner_registry_lists_configured_and_initialized_valid_tags(
	tmp_path: Path,
) -> None:
	"""Combine declared tags with safe existing workspace directory names."""
	config_path = tmp_path / "config_agents.json"
	config_path.write_text(
		json.dumps({"agents": {"dev1": {"model": None, "reasoning_level": None}}}),
		encoding="utf-8",
	)
	workspaces_root = tmp_path / "workspaces"
	(workspaces_root / "project_two").mkdir(parents=True)
	(workspaces_root / "Invalid Tag").mkdir()
	registry = AgentRunnerRegistry(
		config_path=config_path,
		workspaces_root=workspaces_root,
		template_source=tmp_path / "template",
		executable="codex",
		timeout_seconds=10,
		codex_home=tmp_path / "codex-home",
	)

	assert registry.list_tags() == ("dev1", "project_two")


def test_runner_registry_deletes_only_matching_conversation_rollout(
	tmp_path: Path,
) -> None:
	"""Remove one deleted agent's Codex session without touching shared login state."""
	config_path = tmp_path / "config_agents.json"
	config_path.write_text(json.dumps({"agents": {}}), encoding="utf-8")
	codex_home = tmp_path / "codex-home"
	sessions = codex_home / "sessions" / "2026" / "08" / "30"
	sessions.mkdir(parents=True)
	matching = sessions / "rollout-2026-agent-thread-one.jsonl"
	other = sessions / "rollout-2026-agent-thread-two.jsonl"
	matching.write_text("matching", encoding="utf-8")
	other.write_text("other", encoding="utf-8")
	(codex_home / "auth.json").write_text("shared login", encoding="utf-8")
	registry = AgentRunnerRegistry(
		config_path=config_path,
		workspaces_root=tmp_path / "workspaces",
		template_source=tmp_path / "template",
		executable="codex",
		timeout_seconds=10,
		codex_home=codex_home,
	)

	registry.delete_conversation("thread-one")

	assert not matching.exists()
	assert other.is_file()
	assert (codex_home / "auth.json").read_text(encoding="utf-8") == "shared login"


def test_bundled_workspace_template_has_generic_python_project_structure() -> None:
	"""Keep the image seed work-ready for Python utilities and durable outputs."""
	template = PROJECT_ROOT / "config" / "codex-worker" / "workspace-template"
	required_paths = (
		"AGENTS.md",
		"brief.md",
		"agent/BRIEFING.md",
		"docs/agent/PROJECT_GUIDE.md",
		"docs/wiki/.gitkeep",
		"scripts/activate_venv.sh",
		"scripts/requirements.txt",
		"data/.gitkeep",
		"logs/.gitkeep",
		"tmp/.gitkeep",
		"tmp/download/.gitkeep",
		"tmp/upload/.gitkeep",
	)

	assert all((template / relative_path).is_file() for relative_path in required_paths)
	activation_script = (template / "scripts" / "activate_venv.sh").read_text(
		encoding="utf-8"
	)
	assert "python3 -m venv" in activation_script
	assert "scripts/.venv" in (template / ".gitignore").read_text(encoding="utf-8")


def test_gateway_client_parser_accepts_only_matching_terminal_answer() -> None:
	"""Ignore the queue acknowledgement and reject worker errors without details."""
	request_id = "request-one"
	assert CodexWorkerClient._parse_response(
		json.dumps(
			{
				"type": "accepted",
				"request_id": request_id,
				"metadata": {"agent_tag": "dev1"},
			}
		),
		request_id,
	) is None
	assert CodexWorkerClient._parse_response(
		json.dumps(
			{
				"type": "response",
				"request_id": request_id,
				"answer": "done",
				"metadata": {"agent_tag": "dev1"},
			}
		),
		request_id,
	) == "done"

	try:
		CodexWorkerClient._parse_response(
			json.dumps({"type": "error", "request_id": request_id}),
			request_id,
		)
	except CodexWorkerError as error:
		assert "could not complete" in str(error)
	else:
		raise AssertionError("Worker errors must not be accepted as answers")


def test_gateway_client_parser_validates_agent_management_acknowledgement() -> None:
	"""Accept only an exact lifecycle response matching the request parameters."""
	CodexWorkerClient._parse_management_response(
		json.dumps(
			{
				"type": "agent_management",
				"request_id": "config-one",
				"operation": "config",
				"agent_tag": "dev1",
				"model": "gpt-5.6-sol",
				"reasoning_level": "low",
			}
		),
		"config-one",
		"config",
		"dev1",
		"gpt-5.6-sol",
		"low",
	)
	with pytest.raises(CodexWorkerError, match="invalid management response"):
		CodexWorkerClient._parse_management_response(
			json.dumps(
				{
					"type": "agent_management",
					"request_id": "delete-one",
					"operation": "reset",
					"agent_tag": "dev1",
				}
			),
			"delete-one",
			"delete",
			"dev1",
			None,
			None,
		)


def test_gateway_client_parser_accepts_bounded_artifact_manifest() -> None:
	"""Preserve only safe filename, media, size, and digest fields from the worker."""
	response = CodexWorkerClient._parse_worker_response(
		json.dumps(
			{
				"type": "response",
				"request_id": "request-one",
				"answer": "done",
				"attachments": [
					{
						"filename": "report.md",
						"content_type": "text/markdown",
						"size": 12,
						"sha256": "a" * 64,
					},
					{
						"filename": "bundle.zip",
						"content_type": "application/zip",
						"size": 64,
						"sha256": "b" * 64,
					},
				],
				"metadata": {"agent_tag": "dev1"},
			}
		),
		"request-one",
	)

	assert response is not None
	assert response.answer == "done"
	assert response.attachments[0].filename == "report.md"
	assert response.attachments[1].filename == "bundle.zip"


def test_gateway_client_parser_validates_worker_status() -> None:
	"""Convert content-free worker status JSON into the typed report boundary."""
	request_id = "status-one"
	status = CodexWorkerClient._parse_status_response(
		json.dumps(
			{
				"type": "status",
				"request_id": request_id,
				"status": {
					"agent_tag": "dev1",
					"state": "idle",
					"model": "gpt-actual",
					"reasoning_level": "medium",
					"runtime_profile_scope": "most_recent",
					"queued": 0,
					"processing": 0,
					"processed": 1,
					"completed": 1,
					"failed": 0,
					"total_active_seconds": 60.5,
					"today_active_seconds": 20.0,
					"time_zone": "UTC",
					"recent_commands": [
						{
							"received_at": "2026-08-29T14:00:00+02:00",
							"command": "respond",
							"status": "completed",
							"user_id": "100000000000000001",
							"channel_id": "100000000000000002",
						}
					],
				},
			}
		),
		request_id,
	)

	assert status.agent_tag == "dev1"
	assert status.state == "idle"
	assert status.model == "gpt-actual"
	assert status.reasoning_level == "medium"
	assert status.runtime_profile_scope == "most_recent"
	assert status.processed == 1
	assert status.total_active_seconds == 60.5
	assert status.recent_commands[0].command == "respond"


def test_gateway_client_parser_validates_sorted_agent_list() -> None:
	"""Accept only a matching, unique, sorted list of valid agent tags."""
	agent_tags = CodexWorkerClient._parse_agent_list_response(
		json.dumps(
			{
				"type": "agent_list",
				"request_id": "list-one",
				"agent_tags": ["dev1", "project_two"],
			}
		),
		"list-one",
	)

	assert agent_tags == ("dev1", "project_two")
	assert CodexWorkerClient._parse_agent_list_response(
		json.dumps(
			{
				"type": "agent_list",
				"request_id": "empty-list",
				"agent_tags": [],
			}
		),
		"empty-list",
	) == ()
	with pytest.raises(CodexWorkerError):
		CodexWorkerClient._parse_agent_list_response(
			json.dumps(
				{
					"type": "agent_list",
					"request_id": "list-one",
					"agent_tags": ["project_two", "dev1"],
				}
			),
			"list-one",
		)
