"""Shared bounded Codex model shorthands for agent-management commands."""

from __future__ import annotations

MODEL_ALIASES = {
	"low": ("gpt-5.6-sol", "low"),
	"medium": ("gpt-5.6-sol", "medium"),
	"high": ("gpt-5.6-sol", "high"),
	"luna-low": ("gpt-5.6-luna", "low"),
	"luna-medium": ("gpt-5.6-luna", "medium"),
	"luna-high": ("gpt-5.6-luna", "high"),
	"terra-low": ("gpt-5.6-terra", "low"),
	"terra-medium": ("gpt-5.6-terra", "medium"),
	"terra-high": ("gpt-5.6-terra", "high"),
}
MODEL_CHOICES = tuple(
	{"name": alias, "value": alias}
	for alias in MODEL_ALIASES
)
