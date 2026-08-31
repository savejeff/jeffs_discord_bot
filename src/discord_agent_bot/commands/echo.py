"""Bounded echo command definition."""

from discord_agent_bot.commands.base import (
	CommandContext,
	CommandDefinition,
	CommandOption,
	STRING_OPTION_TYPE,
)

MAX_ECHO_LENGTH = 200


class EchoCommand(CommandDefinition):
	"""Return a bounded supplied string under the shared mention-safe response policy."""

	name = "echo"
	description = "Return the supplied text."
	order = 20
	options = (
		CommandOption(
			name="text",
			description="Text to return.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			max_length=MAX_ECHO_LENGTH,
		),
	)

	async def invoke(self, context: CommandContext) -> str:
		"""Validate and return the exact supplied text."""
		context.require_options("text")
		return context.string_option("text", MAX_ECHO_LENGTH)
