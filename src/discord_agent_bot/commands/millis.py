"""Application-uptime command definition."""

from discord_agent_bot.commands.base import CommandContext, CommandDefinition


class MillisCommand(CommandDefinition):
	"""Return monotonic milliseconds since the application was constructed."""

	name = "millis"
	description = "Return milliseconds since the application started."
	order = 30

	async def invoke(self, context: CommandContext) -> str:
		"""Return a nonnegative process-local uptime value."""
		context.require_options()
		return str(max(0, context.uptime_ms))
