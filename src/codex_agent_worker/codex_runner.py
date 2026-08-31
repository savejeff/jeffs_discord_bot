"""Subprocess adapter for one persistent non-interactive Codex conversation."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import threading
from time import time
from typing import Any

from codex_agent_worker.models import CodexRunResult, CodexRuntimeProfile

INITIAL_INSTRUCTIONS = """You are a general-purpose assistant reached through a private WebSocket module.
Work inside your assigned current working directory, where you may read and write files. For
application-specific questions, consult the relevant material under docs/wiki before answering, then
use general knowledge only to clarify or fill identified gaps. Treat docs/wiki as read-only unless
the current user request explicitly asks you to update or extend that knowledge base. Be concise,
factual, and state uncertainty rather than inventing details. Do not attempt to access Discord or its
credentials. The metadata associated with the transport request is not part of the user prompt.

User request:
"""

RESUME_INSTRUCTIONS = """Continue the same tagged conversation and work inside your assigned current
working directory, where you may read and write files. Consult docs/wiki for application-specific
questions and treat it as read-only unless the current user request explicitly asks you to update or
extend the knowledge base. Supplement it with clearly identified general knowledge when useful, and
state uncertainty rather than inventing details.

New user request:
"""


def build_codex_command(
	executable: str,
	workspace: Path,
	thread_id: str | None,
	model: str | None = None,
	reasoning_level: str | None = None,
	permission_mode: str = "container-isolated",
) -> list[str]:
	"""Build a Codex command using the configured per-agent permission policy."""
	base = [
		executable,
		"exec",
		"--json",
		"--color",
		"never",
		"--skip-git-repo-check",
		"-C",
		str(workspace),
	]
	if permission_mode == "container-isolated":
		# The dedicated read-only-root worker container is the isolation boundary.
		base.append("--dangerously-bypass-approvals-and-sandbox")
	elif permission_mode == "workspace-write":
		base.extend(
			[
				"--sandbox",
				"workspace-write",
				"--ask-for-approval",
				"never",
			]
		)
	elif permission_mode == "auto-review":
		base.extend(
			[
				"--sandbox",
				"workspace-write",
				"--ask-for-approval",
				"on-request",
				"--config",
				'approvals_reviewer="auto_review"',
			]
		)
	else:
		raise ValueError("Unsupported Codex permission mode.")
	if model is not None:
		base.extend(["--model", model])
	if reasoning_level is not None:
		base.extend(["--config", f'model_reasoning_effort="{reasoning_level}"'])
	if thread_id is None:
		return [*base, "-"]
	return [*base, "resume", thread_id, "-"]


def parse_codex_events(stdout: str) -> tuple[str | None, str | None, bool]:
	"""Extract the started thread, final agent message, and error presence from JSONL."""
	thread_id: str | None = None
	final_message: str | None = None
	had_error = False
	for line in stdout.splitlines():
		try:
			event: dict[str, Any] = json.loads(line)
		except (json.JSONDecodeError, TypeError):
			continue
		if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
			thread_id = event["thread_id"]
		elif event.get("type") == "item.completed":
			item = event.get("item", {})
			if isinstance(item, dict) and item.get("type") == "agent_message":
				text = item.get("text")
				if isinstance(text, str):
					final_message = text
		elif event.get("type") in {"error", "turn.failed"}:
			had_error = True
	return thread_id, final_message, had_error


def _parse_timestamp(value: object) -> float | None:
	if not isinstance(value, str):
		return None
	try:
		return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
	except ValueError:
		return None


def _profile_from_turn_context(event: dict[str, Any]) -> CodexRuntimeProfile | None:
	"""Extract only the effective model profile from one Codex rollout event."""
	if event.get("type") != "turn_context" or not isinstance(event.get("payload"), dict):
		return None
	payload = event["payload"]
	model = payload.get("model")
	if not isinstance(model, str) or not model or len(model) > 128:
		return None
	reasoning_level = payload.get("effort")
	if reasoning_level is None:
		collaboration_mode = payload.get("collaboration_mode")
		if isinstance(collaboration_mode, dict):
			settings = collaboration_mode.get("settings")
			profile_settings = settings if isinstance(settings, dict) else collaboration_mode
			reasoning_level = profile_settings.get("reasoning_effort")
	if not isinstance(reasoning_level, str) or not reasoning_level:
		reasoning_level = None
	elif len(reasoning_level) > 64:
		return None
	observed_at = _parse_timestamp(event.get("timestamp"))
	if observed_at is None:
		return None
	return CodexRuntimeProfile(model, reasoning_level, observed_at)


def read_codex_runtime_profile(
	rollout_path: Path,
	workspace: Path,
	not_before: float | None = None,
) -> CodexRuntimeProfile | None:
	"""Read the latest matching runtime profile without retaining rollout content."""
	latest: CodexRuntimeProfile | None = None
	try:
		with rollout_path.open("r", encoding="utf-8", errors="replace") as rollout:
			for line in rollout:
				try:
					event: dict[str, Any] = json.loads(line)
				except (json.JSONDecodeError, TypeError):
					continue
				profile = _profile_from_turn_context(event)
				if profile is None or (
					not_before is not None and profile.observed_at < not_before
				):
					continue
				payload = event["payload"]
				cwd = payload.get("cwd")
				if not isinstance(cwd, str):
					continue
				try:
					matches_workspace = Path(cwd).resolve() == workspace.resolve()
				except OSError:
					continue
				if matches_workspace:
					latest = profile
	except OSError:
		return None
	return latest


def find_codex_runtime_profile(
	codex_home: Path,
	workspace: Path,
	thread_id: str | None,
	not_before: float | None = None,
) -> CodexRuntimeProfile | None:
	"""Find the newest actual turn profile for one thread or active workspace."""
	sessions_root = codex_home / "sessions"
	pattern = f"*{thread_id}*.jsonl" if thread_id else "rollout-*.jsonl"
	try:
		candidates = sorted(
			sessions_root.rglob(pattern),
			key=lambda candidate: candidate.stat().st_mtime,
			reverse=True,
		)
	except OSError:
		return None
	for candidate in candidates:
		if not_before is not None:
			try:
				if candidate.stat().st_mtime < not_before:
					continue
			except OSError:
				continue
		profile = read_codex_runtime_profile(candidate, workspace, not_before)
		if profile is not None:
			return profile
	return None


class CodexRunner:
	"""Run one Codex child at a time with timeout and redacted failure handling."""

	def __init__(
		self,
		executable: str,
		workspace: Path,
		timeout_seconds: int,
		model: str | None = None,
		reasoning_level: str | None = None,
		codex_home: Path | None = None,
		permission_mode: str = "container-isolated",
	) -> None:
		"""Configure the executable, workspace, model policy, and turn deadline."""
		self._executable = executable
		self._workspace = workspace
		self._timeout_seconds = timeout_seconds
		self._model = model
		self._reasoning_level = reasoning_level
		self._permission_mode = permission_mode
		self._codex_home = codex_home or Path(
			os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
		)
		self._process_lock = threading.Lock()
		self._process: subprocess.Popen[str] | None = None
		self._active_thread_id: str | None = None
		self._active_started_at: float | None = None

	def run(self, prompt: str, thread_id: str | None) -> CodexRunResult:
		"""Execute or resume one turn and return only the final agent message."""
		command = build_codex_command(
			self._executable,
			self._workspace,
			thread_id,
			self._model,
			self._reasoning_level,
			self._permission_mode,
		)
		framed_prompt = (
			f"{RESUME_INSTRUCTIONS if thread_id else INITIAL_INSTRUCTIONS}{prompt.strip()}\n"
		)
		environment = os.environ.copy()
		# Transport authority belongs to the Discord gateway, never to the Codex child.
		for name in list(environment):
			if name.startswith("DISCORD_") or name.startswith("CODEX_WORKER_"):
				environment.pop(name, None)
		try:
			process = subprocess.Popen(
				command,
				cwd=self._workspace,
				env=environment,
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
				encoding="utf-8",
				errors="replace",
			)
		except OSError:
			return CodexRunResult(-1, thread_id, None, "Could not start Codex.")

		with self._process_lock:
			self._process = process
			self._active_thread_id = thread_id
			self._active_started_at = time()
		try:
			stdout, _stderr = process.communicate(framed_prompt, timeout=self._timeout_seconds)
		except subprocess.TimeoutExpired:
			process.terminate()
			try:
				process.communicate(timeout=10)
			except subprocess.TimeoutExpired:
				process.kill()
				process.communicate()
			profile = self.latest_runtime_profile(thread_id)
			return CodexRunResult(
				-1,
				thread_id,
				None,
				"Codex turn timed out.",
				profile,
			)
		finally:
			with self._process_lock:
				self._process = None
				self._active_thread_id = None
				self._active_started_at = None

		started_thread, final_message, had_error = parse_codex_events(stdout)
		resolved_thread = started_thread or thread_id
		profile = self.latest_runtime_profile(resolved_thread)
		if process.returncode != 0 or had_error:
			return CodexRunResult(
				process.returncode,
				resolved_thread,
				None,
				"Codex turn failed.",
				profile,
			)
		if not resolved_thread or not final_message:
			return CodexRunResult(
				process.returncode,
				resolved_thread,
				None,
				"Codex returned no answer.",
				profile,
			)
		return CodexRunResult(process.returncode, resolved_thread, final_message, None, profile)

	def current_runtime_profile(self) -> CodexRuntimeProfile | None:
		"""Read the actual profile recorded for the currently executing turn."""
		with self._process_lock:
			if self._process is None or self._process.poll() is not None:
				return None
			thread_id = self._active_thread_id
			started_at = self._active_started_at
		if started_at is None:
			return None
		return find_codex_runtime_profile(
			self._codex_home,
			self._workspace,
			thread_id,
			started_at,
		)

	def latest_runtime_profile(self, thread_id: str | None) -> CodexRuntimeProfile | None:
		"""Read the most recent actual profile recorded for the resolved conversation."""
		return find_codex_runtime_profile(
			self._codex_home,
			self._workspace,
			thread_id,
		)

	def cancel(self) -> None:
		"""Terminate the active Codex child during worker shutdown."""
		with self._process_lock:
			if self._process is not None and self._process.poll() is None:
				self._process.terminate()
