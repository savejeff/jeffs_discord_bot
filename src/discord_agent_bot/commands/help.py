"""Catalog-derived Discord Markdown help command definition."""

from discord_agent_bot.commands.base import CommandContext, CommandDefinition


class HelpCommand(CommandDefinition):
	"""Return the registry-generated lookup without external or agent usage."""

	name = "help"
	description = "Show all available commands."
	order = 100

	async def invoke(self, context: CommandContext) -> str:
		"""Return the static help content prepared from the discovered registry."""
		context.require_options()
		return context.help_content
