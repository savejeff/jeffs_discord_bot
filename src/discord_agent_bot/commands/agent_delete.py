"""Moderator-only complete tagged-agent deletion command."""

from __future__ import annotations

import re

from discord_agent_bot.commands.base import (
	AgentStatusError,
	CommandContext,
	CommandDefinition,
	CommandError,
	CommandOption,
	STRING_OPTION_TYPE,
)

MAX_AGENT_TAG_LENGTH = 64
AGENT_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AgentDeleteCommand(CommandDefinition):
	"""Delete one idle agent's workspace, worker history, and thread bindings."""

	name = "agent_delete"
	description = "Delete a tagged agent and its workspace. Moderator only."
	order = 91
	deferred = True
	mod_only = True
	options = (
		CommandOption(
			name="agent_tag",
			description="Agent tag to delete permanently.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			max_length=MAX_AGENT_TAG_LENGTH,
		),
	)

	async def invoke(self, context: CommandContext) -> str:
		"""Request complete deletion for one validated idle agent tag."""
		context.require_options("agent_tag")
		agent_tag = context.string_option("agent_tag", MAX_AGENT_TAG_LENGTH)
		if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise CommandError("Agent tag is invalid")
		if context.agent_manager is None:
			return "Agent management is not configured."
		try:
			await context.agent_manager.delete(agent_tag)
		except AgentStatusError:
			return "The agent could not be deleted. It may be busy or unavailable."
		return f"Agent `{agent_tag}` and its workspace were deleted."
