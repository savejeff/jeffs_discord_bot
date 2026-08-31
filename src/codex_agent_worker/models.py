"""Immutable values shared by the worker queue and Codex runner."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptJob:
	"""Describe one durable prompt and its current processing state."""

	request_id: str
	prompt: str
	metadata_json: str
	status: str
	agent_tag: str = "dev1"
	response: str | None = None
	error: str | None = None


@dataclass(frozen=True, slots=True)
class CodexRuntimeProfile:
	"""Describe model settings observed in Codex's persisted turn context."""

	model: str
	reasoning_level: str | None
	observed_at: float


@dataclass(frozen=True, slots=True)
class CodexRunResult:
	"""Describe the observable outcome of one non-interactive Codex turn."""

	returncode: int
	thread_id: str | None
	final_message: str | None
	error: str | None
	runtime_profile: CodexRuntimeProfile | None = None
