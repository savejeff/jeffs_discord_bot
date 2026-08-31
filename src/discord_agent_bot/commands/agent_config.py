"""Moderator-only tagged-agent runtime profile configuration command."""

from __future__ import annotations

import re

from discord_agent_bot.commands._agent_profiles import MODEL_ALIASES, MODEL_CHOICES
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


class AgentConfigCommand(CommandDefinition):
	"""Set the model and reasoning effort of an existing or new tagged agent."""

	name = "agent_config"
	description = "Set a tagged agent model and reasoning level. Moderator only."
	order = 89
	deferred = True
	mod_only = True
	options = (
		CommandOption(
			name="agent_tag",
			description="Agent tag to configure.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			max_length=MAX_AGENT_TAG_LENGTH,
		),
		CommandOption(
			name="model",
			description="Model shorthand; each value also sets its reasoning level.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			choices=MODEL_CHOICES,
		),
	)

	async def invoke(self, context: CommandContext) -> str:
		"""Resolve the shorthand and persist it through the private worker."""
		context.require_options("agent_tag", "model")
		agent_tag = context.string_option("agent_tag", MAX_AGENT_TAG_LENGTH)
		if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise CommandError("Agent tag is invalid")
		alias = context.string_option("model", 32)
		profile = MODEL_ALIASES.get(alias)
		if profile is None:
			raise CommandError("Unknown model shorthand")
		if context.agent_manager is None:
			return "Agent management is not configured."
		try:
			await context.agent_manager.configure(agent_tag, profile[0], profile[1])
		except AgentStatusError:
			return "The agent configuration could not be changed."
		return (
			f"Agent `{agent_tag}` now uses `{profile[0]}` with "
			f"`{profile[1]}` reasoning."
		)
