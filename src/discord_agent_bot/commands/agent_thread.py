"""Command that creates a creator-owned ordinary-message agent thread."""

from __future__ import annotations

import re

from discord_agent_bot.commands._agent_profiles import MODEL_ALIASES, MODEL_CHOICES
from discord_agent_bot.commands.base import (
	AgentStatusError,
	AgentThreadError,
	CommandContext,
	CommandDefinition,
	CommandError,
	CommandOption,
	STRING_OPTION_TYPE,
)

MAX_AGENT_TAG_LENGTH = 64
AGENT_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AgentThreadCommand(CommandDefinition):
	"""Create a thread for one persistent creator-owned local agent."""

	name = "agent_thread"
	description = "Create a creator-only Codex agent thread."
	order = 74
	deferred = True
	options = (
		CommandOption(
			name="agent_tag",
			description="Required existing or new persistent agent tag.",
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
		"""Configure and bind a Discord thread to one explicitly tagged agent."""
		context.require_options("agent_tag", "model")
		agent_tag = context.string_option("agent_tag", MAX_AGENT_TAG_LENGTH)
		if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise CommandError(
				"Agent tag must use lowercase letters, digits, underscores, or hyphens"
			)
		alias = context.string_option("model", 32)
		profile = MODEL_ALIASES.get(alias)
		if profile is None:
			raise CommandError("Unknown model shorthand")
		if context.channel_id is None or context.user_id is None:
			raise CommandError("The thread destination or creator is unavailable")
		if context.agent_thread_creator is None:
			return "Agent thread creation is not configured."
		try:
			if context.agent_manager is None:
				return "Agent management is not configured."
			await context.agent_manager.configure(agent_tag, profile[0], profile[1])
			result = await context.agent_thread_creator(
				context.guild_id,
				context.channel_id,
				context.user_id,
				agent_tag,
			)
		except AgentThreadError:
			return "The agent thread could not be created."
		except AgentStatusError:
			return "The agent configuration could not be changed."
		return (
			f"Agent thread created: <#{result.thread_id}>\n"
			f"Agent tag: `{result.agent_tag}`\n"
			"Only your ordinary messages in that thread will be sent to this agent."
		)
