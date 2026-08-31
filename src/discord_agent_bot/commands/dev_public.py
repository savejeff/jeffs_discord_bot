"""Public-response development command."""

from __future__ import annotations

from discord_agent_bot.commands.base import CommandContext, CommandDefinition


class DevPublicCommand(CommandDefinition):
	"""Exercise a mention-safe response that is visible to the whole channel."""

	name = "dev_public"
	description = "Return a response visible to everyone in the channel."
	order = 50
	ephemeral = False

	async def invoke(self, context: CommandContext) -> str:
		"""Return static public content without invoking an agent or external service."""
		context.require_options()
		return "This response is visible to everyone in this channel."
