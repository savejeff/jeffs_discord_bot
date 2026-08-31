"""Static hello command definition."""

from discord_agent_bot.commands.base import CommandContext, CommandDefinition


class HelloCommand(CommandDefinition):
	"""Return the fixed hello response without external or agent usage."""

	name = "hello"
	description = "Return world!"
	order = 10

	async def invoke(self, context: CommandContext) -> str:
		"""Return the command's static response after rejecting forged options."""
		context.require_options()
		return "world!"
