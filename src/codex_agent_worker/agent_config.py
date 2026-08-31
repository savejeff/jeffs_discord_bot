"""Load one tagged Codex agent and prepare its persistent workspace."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
from typing import Any

AGENT_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
REASONING_LEVELS = frozenset({"minimal", "low", "medium", "high", "xhigh"})
CODEX_PERMISSION_MODES = frozenset(
	{"auto-review", "container-isolated", "workspace-write"}
)


class AgentConfigError(RuntimeError):
	"""Identify invalid or incomplete per-agent runtime configuration."""


@dataclass(frozen=True, slots=True)
class AgentConfig:
	"""Describe one configured agent and its isolated workspace."""

	tag: str
	workspace: Path
	model: str | None
	reasoning_level: str | None
	codex_permission_mode: str


def validate_agent_tag(tag: str) -> str:
	"""Validate a tag before it is used in a metadata key or filesystem path."""
	if not AGENT_TAG_PATTERN.fullmatch(tag):
		raise AgentConfigError(
			"Agent tag must contain 1-64 lowercase letters, digits, underscores, or hyphens."
		)
	return tag


def _optional_string(value: object, field_name: str) -> str | None:
	"""Accept a null or bounded non-empty configuration string."""
	if value is None:
		return None
	if not isinstance(value, str) or not value.strip() or len(value) > 128:
		raise AgentConfigError(f"Agent {field_name} must be null or a non-empty string.")
	return value.strip()


def load_agent_config(
	config_path: Path,
	tag: str,
	workspaces_root: Path,
	allow_dynamic: bool = False,
) -> AgentConfig:
	"""Load one named agent without accepting caller-controlled workspace paths."""
	validated_tag = validate_agent_tag(tag)
	try:
		document: Any = json.loads(config_path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as error:
		raise AgentConfigError("Could not load the agent configuration file.") from error
	if not isinstance(document, dict) or not isinstance(document.get("agents"), dict):
		raise AgentConfigError("Agent configuration must contain an agents object.")
	entry = document["agents"].get(validated_tag)
	if entry is None and allow_dynamic:
		entry = {}
	if not isinstance(entry, dict):
		raise AgentConfigError(f"Agent tag {validated_tag!r} is not configured.")
	if set(entry) - {"model", "reasoning_level", "codex_permission_mode"}:
		raise AgentConfigError(f"Agent tag {validated_tag!r} contains unknown settings.")

	model = _optional_string(entry.get("model"), "model")
	reasoning_level = _optional_string(entry.get("reasoning_level"), "reasoning level")
	if reasoning_level is not None and reasoning_level not in REASONING_LEVELS:
		raise AgentConfigError(
			"Agent reasoning level must be minimal, low, medium, high, xhigh, or null."
		)
	codex_permission_mode = _optional_string(
		entry.get("codex_permission_mode", "container-isolated"),
		"Codex permission mode",
	)
	if codex_permission_mode not in CODEX_PERMISSION_MODES:
		raise AgentConfigError(
			"Agent Codex permission mode must be auto-review, container-isolated, "
			"or workspace-write."
		)

	root = workspaces_root.resolve()
	workspace_candidate = root / validated_tag
	workspace = workspace_candidate.resolve()
	if workspace != workspace_candidate or workspace.parent != root:
		raise AgentConfigError("Agent workspace resolved outside the workspaces root.")
	return AgentConfig(
		validated_tag,
		workspace,
		model,
		reasoning_level,
		codex_permission_mode,
	)


def load_configured_agent_tags(config_path: Path) -> tuple[str, ...]:
	"""Return every validated tag explicitly declared in the agent configuration."""
	try:
		document: Any = json.loads(config_path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as error:
		raise AgentConfigError("Could not load the agent configuration file.") from error
	agents = document.get("agents") if isinstance(document, dict) else None
	if not isinstance(agents, dict):
		raise AgentConfigError("Agent configuration must contain an agents object.")
	return tuple(sorted(validate_agent_tag(tag) for tag in agents))


def prepare_agent_workspace(
	agent: AgentConfig,
	template_source: Path,
) -> None:
	"""Seed missing project-template files while preserving persistent agent work."""
	agent.workspace.mkdir(parents=True, exist_ok=True)
	try:
		if not template_source.is_dir():
			raise AgentConfigError("Agent workspace template is not a directory.")
		wiki_target = agent.workspace / "docs" / "wiki"
		if wiki_target.is_symlink():
			raise AgentConfigError("Agent workspace contains an unsafe wiki link.")
		preserve_existing_wiki = wiki_target.exists()
		for source in sorted(template_source.rglob("*")):
			relative_path = source.relative_to(template_source)
			if source.is_symlink():
				raise AgentConfigError("Agent workspace template contains a symbolic link.")
			if (
				preserve_existing_wiki
				and relative_path.parts[:2] == ("docs", "wiki")
			):
				continue
			target = agent.workspace / relative_path
			if target.is_symlink():
				raise AgentConfigError("Agent workspace contains an unsafe symbolic link.")
			if source.is_dir():
				target.mkdir(parents=True, exist_ok=True)
				continue
			# Operational root policy follows the image; all other existing files persist.
			if relative_path == Path("AGENTS.md") or not target.exists():
				target.parent.mkdir(parents=True, exist_ok=True)
				shutil.copy2(source, target)
		if not wiki_target.is_dir():
			raise AgentConfigError("Agent workspace template has no docs/wiki directory.")
	except OSError as error:
		raise AgentConfigError("Could not prepare the agent workspace.") from error
