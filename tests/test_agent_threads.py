"""Offline tests for durable creator-owned Discord agent thread routing."""

from __future__ import annotations

from pathlib import Path

from nacl.signing import SigningKey
import pytest

from discord_agent_bot.agent_threads import DiscordAgentThreadCreator
from discord_agent_bot.codex_worker_client import (
	CodexWorkerClient,
	WorkerAttachment,
	WorkerResponse,
)
from discord_agent_bot.config import Settings
from discord_agent_bot.discord_rest import CreatedThread, DiscordUpload
from discord_agent_bot.thread_bindings import ThreadBindingStore
from discord_gateway_observer.application import GatewayObserver

GUILD_ID = "100000000000000001"
PARENT_CHANNEL_ID = "100000000000000002"
THREAD_ID = "100000000000000010"
SECOND_THREAD_ID = "100000000000000011"
CREATOR_USER_ID = "100000000000000003"
OTHER_USER_ID = "100000000000000004"
MESSAGE_ID = "100000000000000020"


class _FakeWorkerClient:
	"""Capture observer prompts while returning a deterministic local answer."""

	def __init__(self) -> None:
		self.requests: list[tuple[str, dict[str, str], str, str | None]] = []
		self.staged: list[tuple[str, str, str, str, bytes]] = []
		self.artifact_content: dict[str, bytes] = {}
		self.response = WorkerResponse("thread answer")

	async def ask_with_artifacts(
		self,
		prompt: str,
		metadata: dict[str, str],
		agent_tag: str,
		request_id: str | None = None,
	) -> WorkerResponse:
		"""Record one routed creator message without contacting Codex."""
		self.requests.append((prompt, metadata, agent_tag, request_id))
		return self.response

	async def stage_attachment(
		self,
		agent_tag: str,
		request_id: str,
		attachment_id: str,
		filename: str,
		content: bytes,
	) -> str:
		"""Record a synthetic inbound transfer and return its workspace path."""
		self.staged.append((agent_tag, request_id, attachment_id, filename, content))
		return f"tmp/download/{request_id}/{attachment_id}_{filename}"

	async def download_artifact(
		self,
		_agent_tag: str,
		_request_id: str,
		artifact: WorkerAttachment,
	) -> bytes:
		"""Return synthetic bytes for one worker output manifest entry."""
		return self.artifact_content[artifact.filename]

	@staticmethod
	def parse_artifact_manifest(value: str) -> tuple[WorkerAttachment, ...]:
		"""Use the production manifest validator in observer delivery tests."""
		return CodexWorkerClient.parse_artifact_manifest(value)


class _FakeRestClient:
	"""Capture mention-safe response delivery without contacting Discord."""

	def __init__(self) -> None:
		self.messages: list[
			tuple[str, str, str | None, tuple[DiscordUpload, ...]]
		] = []
		self.created_threads: list[tuple[str, str]] = []
		self.downloads: dict[str, bytes] = {}

	def create_public_thread(self, channel_id: str, name: str) -> CreatedThread:
		"""Record one thread creation and return the synthetic bound thread."""
		self.created_threads.append((channel_id, name))
		return CreatedThread(THREAD_ID, channel_id)

	def create_message(
		self,
		channel_id: str,
		content: str,
		nonce: str | None = None,
		attachments: tuple[DiscordUpload, ...] = (),
	) -> str:
		"""Record one response and return a synthetic Discord message ID."""
		self.messages.append((channel_id, content, nonce, attachments))
		return "100000000000000030"

	def download_attachment(self, url: str, expected_size: int) -> bytes:
		"""Return a synthetic Discord CDN file with its expected byte count."""
		content = self.downloads[url]
		assert len(content) == expected_size
		return content


def _settings() -> Settings:
	"""Create non-secret observer settings scoped to the synthetic guild."""
	return Settings(
		public_key=SigningKey.generate().verify_key,
		guild_id=GUILD_ID,
		bot_token="test-token",
	)


def test_store_accepts_only_creator_and_closure_retains_agent(tmp_path: Path) -> None:
	"""Deduplicate creator prompts and cancel work when the Discord thread closes."""
	store = ThreadBindingStore(tmp_path / "gateway.db", clock=lambda: 100.0)
	store.bind_thread(
		THREAD_ID,
		GUILD_ID,
		PARENT_CHANNEL_ID,
		"existing_agent",
		CREATOR_USER_ID,
	)

	assert store.enqueue_creator_message(
		MESSAGE_ID,
		THREAD_ID,
		GUILD_ID,
		OTHER_USER_ID,
		"not authorized",
	) is False
	assert store.enqueue_creator_message(
		MESSAGE_ID,
		THREAD_ID,
		GUILD_ID,
		CREATOR_USER_ID,
		"creator prompt",
	) is True
	assert store.enqueue_creator_message(
		MESSAGE_ID,
		THREAD_ID,
		GUILD_ID,
		CREATOR_USER_ID,
		"duplicate prompt",
	) is False
	job = store.claim_prompt()
	assert job is not None
	assert job.prompt == "creator prompt"

	assert store.close_binding(THREAD_ID, "archived") is True
	assert store.store_answer(MESSAGE_ID, "must not be delivered") is False
	assert store.binding_is_active(THREAD_ID) is False
	assert store.list_agent_tags() == ("existing_agent",)
	assert store.claim_answer() is None


def test_only_observer_startup_recovers_interrupted_prompt(tmp_path: Path) -> None:
	"""Prevent an HTTP-service restart from stealing an active observer prompt."""
	database_path = tmp_path / "gateway.db"
	store = ThreadBindingStore(database_path)
	store.bind_thread(
		THREAD_ID,
		GUILD_ID,
		PARENT_CHANNEL_ID,
		"dev1",
		CREATOR_USER_ID,
	)
	assert store.enqueue_creator_message(
		MESSAGE_ID,
		THREAD_ID,
		GUILD_ID,
		CREATOR_USER_ID,
		"recover me",
	) is True
	assert store.claim_prompt() is not None

	interaction_process_store = ThreadBindingStore(database_path)
	assert interaction_process_store.claim_prompt() is None
	observer_process_store = ThreadBindingStore(database_path, recover_interrupted=True)
	recovered_job = observer_process_store.claim_prompt()
	assert recovered_job is not None
	assert recovered_job.message_id == MESSAGE_ID


def test_observer_startup_turns_interrupted_attachment_staging_into_reply(
	tmp_path: Path,
) -> None:
	"""Avoid silently losing a creator file when the observer restarts mid-transfer."""
	database_path = tmp_path / "gateway.db"
	store = ThreadBindingStore(database_path)
	store.bind_thread(
		THREAD_ID,
		GUILD_ID,
		PARENT_CHANNEL_ID,
		"dev1",
		CREATOR_USER_ID,
	)
	assert store.reserve_creator_message(
		MESSAGE_ID,
		THREAD_ID,
		GUILD_ID,
		CREATOR_USER_ID,
		"message with file",
		staging=True,
	) == "dev1"

	recovered_store = ThreadBindingStore(database_path, recover_interrupted=True)
	recovered = recovered_store.claim_answer()

	assert recovered is not None
	assert recovered.message_id == MESSAGE_ID
	assert "interrupted" in (recovered.answer or "")


@pytest.mark.anyio
async def test_thread_creator_uses_required_tag_and_persists_binding(tmp_path: Path) -> None:
	"""Create a thread whose durable agent identity is always supplied explicitly."""
	store = ThreadBindingStore(tmp_path / "gateway.db")
	rest = _FakeRestClient()
	creator = DiscordAgentThreadCreator(rest, store)  # type: ignore[arg-type]

	result = await creator(GUILD_ID, PARENT_CHANNEL_ID, CREATOR_USER_ID, "project_alpha")

	assert result.thread_id == THREAD_ID
	assert result.agent_tag == "project_alpha"
	assert rest.created_threads == [(PARENT_CHANNEL_ID, "agent-project_alpha")]
	assert rest.messages[0][0] == THREAD_ID
	binding = store.get_binding(THREAD_ID)
	assert binding is not None
	assert binding.creator_user_id == CREATOR_USER_ID
	assert binding.agent_tag == "project_alpha"


@pytest.mark.anyio
async def test_observer_routes_creator_message_and_closes_archived_binding(
	tmp_path: Path,
) -> None:
	"""Route ordinary creator text through Codex and stop after a thread archive event."""
	store = ThreadBindingStore(tmp_path / "gateway.db")
	store.bind_thread(
		THREAD_ID,
		GUILD_ID,
		PARENT_CHANNEL_ID,
		"dev1",
		CREATOR_USER_ID,
	)
	worker = _FakeWorkerClient()
	rest = _FakeRestClient()
	observer = GatewayObserver(
		settings=_settings(),
		binding_store=store,
		rest_client=rest,  # type: ignore[arg-type]
		worker_client=worker,  # type: ignore[arg-type]
		health_file=tmp_path / "healthy",
	)

	await observer._handle_dispatch(
		"MESSAGE_CREATE",
		{
			"id": MESSAGE_ID,
			"guild_id": GUILD_ID,
			"channel_id": THREAD_ID,
			"type": 0,
			"content": "ignored",
			"author": {"id": OTHER_USER_ID, "bot": False},
		},
	)
	assert await observer.process_one_delivery_step() is False

	await observer._handle_dispatch(
		"MESSAGE_CREATE",
		{
			"id": MESSAGE_ID,
			"guild_id": GUILD_ID,
			"channel_id": THREAD_ID,
			"type": 0,
			"content": "explain the next step",
			"author": {"id": CREATOR_USER_ID, "bot": False},
		},
	)
	assert await observer.process_one_delivery_step() is True
	assert await observer.process_one_delivery_step() is True
	assert len(worker.requests) == 1
	prompt, metadata, agent_tag, request_id = worker.requests[0]
	assert prompt.startswith("explain the next step\n\n")
	assert f"tmp/upload/gateway_{MESSAGE_ID}/" in prompt
	assert (metadata, agent_tag, request_id) == (
			{
				"source": "discord_gateway",
				"command": "agent_thread",
				"guild_id": GUILD_ID,
				"channel_id": THREAD_ID,
				"user_id": CREATOR_USER_ID,
				"message_id": MESSAGE_ID,
			},
			"dev1",
			f"gateway_{MESSAGE_ID}",
		)
	assert rest.messages == [(THREAD_ID, "thread answer", MESSAGE_ID, ())]

	await observer._handle_dispatch(
		"THREAD_UPDATE",
		{
			"id": THREAD_ID,
			"guild_id": GUILD_ID,
			"thread_metadata": {"archived": True},
		},
	)
	assert store.binding_is_active(THREAD_ID) is False
	assert store.list_agent_tags() == ("dev1",)


@pytest.mark.anyio
async def test_thread_attachments_move_through_workspace_and_back_to_discord(
	tmp_path: Path,
) -> None:
	"""Stage creator files in tmp/download and upload tmp/upload results with the answer."""
	store = ThreadBindingStore(tmp_path / "gateway.db")
	store.bind_thread(
		THREAD_ID,
		GUILD_ID,
		PARENT_CHANNEL_ID,
		"dev1",
		CREATOR_USER_ID,
	)
	worker = _FakeWorkerClient()
	rest = _FakeRestClient()
	inbound_url = "https://cdn.discordapp.com/attachments/channel/file/input.md"
	rest.downloads[inbound_url] = b"source notes"
	outbound_content = b"compiled report"
	worker.artifact_content["report.md"] = outbound_content
	worker.response = WorkerResponse(
		"The report is attached.",
		(
			WorkerAttachment(
				"report.md",
				"text/markdown",
				len(outbound_content),
				"0" * 64,
			),
		),
	)
	observer = GatewayObserver(
		settings=_settings(),
		binding_store=store,
		rest_client=rest,  # type: ignore[arg-type]
		worker_client=worker,  # type: ignore[arg-type]
		health_file=tmp_path / "healthy",
	)

	await observer._handle_dispatch(
		"MESSAGE_CREATE",
		{
			"id": MESSAGE_ID,
			"guild_id": GUILD_ID,
			"channel_id": THREAD_ID,
			"type": 0,
			"content": "summarize this",
			"attachments": [
				{
					"id": "100000000000000021",
					"filename": "input.md",
					"size": len(b"source notes"),
					"url": inbound_url,
				}
			],
			"author": {"id": CREATOR_USER_ID, "bot": False},
		},
	)
	assert await observer.process_one_delivery_step() is True
	assert await observer.process_one_delivery_step() is True

	assert worker.staged == [
		(
			"dev1",
			f"gateway_{MESSAGE_ID}",
			"100000000000000021",
			"input.md",
			b"source notes",
		)
	]
	assert f"tmp/download/gateway_{MESSAGE_ID}/100000000000000021_input.md" in (
		worker.requests[0][0]
	)
	uploads = rest.messages[0][3]
	assert len(uploads) == 1
	assert uploads[0] == DiscordUpload("report.md", "text/markdown", outbound_content)


def test_gateway_rejects_zip_as_inbound_attachment() -> None:
	"""Keep ZIP archives out of the agent workspace even though output ZIPs are allowed."""
	with pytest.raises(ValueError, match="metadata"):
		GatewayObserver._parse_gateway_attachments(
			[
				{
					"id": "100000000000000021",
					"filename": "input.zip",
					"size": 100,
					"url": "https://cdn.discordapp.com/attachments/1/2/input.zip",
				}
			]
		)


@pytest.fixture
def anyio_backend() -> str:
	"""Keep observer tests on the asyncio backend used in production."""
	return "asyncio"
