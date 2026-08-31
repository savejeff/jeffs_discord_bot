"""Resolve configured or dynamic agent tags to isolated persistent runners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import shutil
import threading

from codex_agent_worker.agent_config import (
	AgentConfig,
	AgentConfigError,
	load_agent_config,
	load_configured_agent_tags,
	prepare_agent_workspace,
	validate_agent_tag,
)
from codex_agent_worker.codex_runner import CodexRunner


class AgentRunnerRegistry:
	"""Create one cached Codex runner and workspace for each validated agent tag."""

	def __init__(
		self,
		config_path: Path,
		workspaces_root: Path,
		template_source: Path,
		executable: str,
		timeout_seconds: int,
		codex_home: Path,
		runtime_config_loader: Callable[[str], tuple[str, str] | None] | None = None,
	) -> None:
		"""Store immutable runner inputs without creating dynamic workspaces eagerly."""
		self._config_path = config_path
		self._workspaces_root = workspaces_root
		self._template_source = template_source
		self._executable = executable
		self._timeout_seconds = timeout_seconds
		self._codex_home = codex_home
		self._runtime_config_loader = runtime_config_loader
		self._lock = threading.Lock()
		self._runners: dict[str, CodexRunner] = {}

	def get(self, agent_tag: str) -> CodexRunner:
		"""Return a cached runner or initialize a safe dynamic tagged workspace."""
		with self._lock:
			existing = self._runners.get(agent_tag)
			if existing is not None:
				return existing
			agent = load_agent_config(
				self._config_path,
				agent_tag,
				self._workspaces_root,
				allow_dynamic=True,
			)
			if self._runtime_config_loader is not None:
				runtime_config = self._runtime_config_loader(agent.tag)
				if runtime_config is not None:
					agent = replace(
						agent,
						model=runtime_config[0],
						reasoning_level=runtime_config[1],
					)
			prepare_agent_workspace(
				agent,
				self._template_source,
			)
			runner = self._create_runner(agent)
			self._runners[agent.tag] = runner
			return runner

	def list_tags(self) -> tuple[str, ...]:
		"""List configured, initialized, and currently cached valid agent tags."""
		tags = set(load_configured_agent_tags(self._config_path))
		with self._lock:
			tags.update(self._runners)
		try:
			workspace_entries = tuple(self._workspaces_root.iterdir())
		except FileNotFoundError:
			workspace_entries = ()
		except OSError as error:
			raise AgentConfigError("Could not list agent workspaces.") from error
		for entry in workspace_entries:
			if entry.is_symlink() or not entry.is_dir():
				continue
			try:
				tags.add(validate_agent_tag(entry.name))
			except AgentConfigError:
				continue
		return tuple(sorted(tags))

	def prepare_configured_workspaces(self) -> None:
		"""Seed every declared agent workspace without starting a Codex process."""
		for agent_tag in load_configured_agent_tags(self._config_path):
			agent = load_agent_config(
				self._config_path,
				agent_tag,
				self._workspaces_root,
			)
			prepare_agent_workspace(agent, self._template_source)

	def invalidate(self, agent_tag: str) -> None:
		"""Discard one idle cached runner so new settings apply to its next turn."""
		validated_tag = validate_agent_tag(agent_tag)
		with self._lock:
			self._runners.pop(validated_tag, None)

	def delete_workspace(self, agent_tag: str) -> None:
		"""Remove an idle agent runner and its entire validated workspace tree."""
		workspace = self._workspace_path(agent_tag)
		with self._lock:
			self._runners.pop(agent_tag, None)
		if workspace.exists():
			if workspace.is_symlink() or not workspace.is_dir():
				raise AgentConfigError("Agent workspace is not a safe directory.")
			try:
				shutil.rmtree(workspace)
			except OSError as error:
				raise AgentConfigError("Could not delete the agent workspace.") from error

	def reset_workspace(self, agent_tag: str) -> None:
		"""Recreate one idle workspace solely from the current image template."""
		self.delete_workspace(agent_tag)
		self.get(agent_tag)

	def delete_conversation(self, thread_id: str | None) -> None:
		"""Delete rollout files belonging to one removed agent conversation only."""
		if thread_id is None:
			return
		if (
			not 1 <= len(thread_id) <= 128
			or any(
				character
				not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
				for character in thread_id
			)
		):
			raise AgentConfigError("Stored Codex conversation identifier is invalid.")
		sessions_root = (self._codex_home / "sessions").resolve()
		if not sessions_root.is_dir():
			return
		try:
			for candidate in sessions_root.rglob("*.jsonl"):
				if thread_id not in candidate.name:
					continue
				resolved = candidate.resolve()
				if (
					candidate.is_symlink()
					or not resolved.is_relative_to(sessions_root)
					or not resolved.is_file()
				):
					raise AgentConfigError("Codex conversation path is unsafe.")
				resolved.unlink()
		except OSError as error:
			raise AgentConfigError("Could not delete the Codex conversation rollout.") from error

	def _workspace_path(self, agent_tag: str) -> Path:
		"""Resolve a validated workspace while preventing root or symlink escape."""
		validated_tag = validate_agent_tag(agent_tag)
		root = self._workspaces_root.resolve()
		candidate = root / validated_tag
		workspace = candidate.resolve()
		if workspace != candidate or workspace.parent != root:
			raise AgentConfigError("Agent workspace resolved outside the workspaces root.")
		return workspace

	def _create_runner(self, agent: AgentConfig) -> CodexRunner:
		"""Construct one runner from resolved settings and an internal workspace path."""
		return CodexRunner(
			executable=self._executable,
			workspace=agent.workspace,
			timeout_seconds=self._timeout_seconds,
			model=agent.model,
			reasoning_level=agent.reasoning_level,
			codex_home=self._codex_home,
			permission_mode=agent.codex_permission_mode,
		)
