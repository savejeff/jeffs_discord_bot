"""Deferred command that lists durable configured and created agent tags."""

from __future__ import annotations

from discord_agent_bot.commands.base import (
	AgentStatusError,
	CommandContext,
	CommandDefinition,
)

MAX_DISCORD_RESPONSE_LENGTH = 2_000


def _format_agent_tags(agent_tags: tuple[str, ...]) -> str:
	"""Render as many sorted agent tags as Discord's response limit permits."""
	prefix = "Available agent tags:\n```text\n"
	suffix = "\n```"
	lines: list[str] = []
	for index, agent_tag in enumerate(agent_tags):
		candidate_lines = [*lines, agent_tag]
		remaining = len(agent_tags) - index - 1
		if remaining:
			candidate_lines.append(f"... {remaining} more")
		candidate = prefix + "\n".join(candidate_lines) + suffix
		if len(candidate) > MAX_DISCORD_RESPONSE_LENGTH:
			break
		lines.append(agent_tag)
	if len(lines) < len(agent_tags):
		remaining = len(agent_tags) - len(lines)
		while lines:
			candidate = prefix + "\n".join(
				[*lines, f"... {remaining} more"]
			) + suffix
			if len(candidate) <= MAX_DISCORD_RESPONSE_LENGTH:
				return candidate
			lines.pop()
			remaining += 1
	return prefix + ("\n".join(lines) if lines else "(none)") + suffix


class AgentListCommand(CommandDefinition):
	"""List persistent agent tags without invoking a Codex agent."""

	name = "agent_list"
	description = "List configured and previously created Codex agent tags."
	order = 88
	deferred = True

	async def invoke(self, context: CommandContext) -> str:
		"""Request the worker's content-free tag catalog and format it for Discord."""
		context.require_options()
		if context.agent_list_reader is None:
			return "Agent listing is not configured."
		try:
			agent_tags = await context.agent_list_reader()
		except AgentStatusError:
			return "The agent list is currently unavailable."
		return _format_agent_tags(agent_tags)
