"""Deferred-response development command."""

from __future__ import annotations

from discord_agent_bot.commands.base import CommandContext, CommandDefinition

DEFERRED_DEVELOPMENT_DELAY_SECONDS = 16.0


class DevDeferredCommand(CommandDefinition):
	"""Exercise Discord's deferred interaction response and completion webhook."""

	name = "dev_deferred"
	description = "Return after a delay longer than 15 seconds."
	order = 60
	deferred = True

	async def invoke(self, context: CommandContext) -> str:
		"""Wait past the development threshold and return a static completion message."""
		context.require_options()
		await context.sleep(DEFERRED_DEVELOPMENT_DELAY_SECONDS)
		return "Deferred response completed after more than 15 seconds."
