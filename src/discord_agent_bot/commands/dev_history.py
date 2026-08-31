"""Bounded current-destination history command definition."""

from discord_agent_bot.commands.base import (
	CommandContext,
	CommandDefinition,
	CommandError,
	CommandOption,
	INTEGER_OPTION_TYPE,
)
from discord_agent_bot.discord_rest import DiscordRestError, RecentMessage

MAX_HISTORY_COUNT = 10
MAX_HISTORY_CONTENT_LENGTH = 1_800
MAX_HISTORY_MESSAGE_LENGTH = 300


def _format_history(messages: list[RecentMessage]) -> str:
	"""Render newest-first message text inside Discord's bounded response content."""
	if not messages:
		return "No readable message history was returned."

	lines = ["Recent messages (newest first):"]
	for index, message in enumerate(messages, start=1):
		author = " ".join(message.author_name.split()) or "unknown"
		content = " ".join(message.content.split()) or "[content unavailable]"
		line = f"{index}. {author}: {content[:MAX_HISTORY_MESSAGE_LENGTH]}"
		remaining = MAX_HISTORY_CONTENT_LENGTH - len("\n".join(lines)) - 1
		if remaining <= 0:
			break
		lines.append(line[:remaining])
	return "\n".join(lines)


class DevHistoryCommand(CommandDefinition):
	"""Read bounded history from only the authorized invoking channel or thread."""

	name = "dev_history"
	description = "Return recent messages from the current channel or thread."
	order = 50
	options = (
		CommandOption(
			name="count",
			description="Number of recent messages to return (default 1).",
			option_type=INTEGER_OPTION_TYPE,
			min_value=1,
			max_value=MAX_HISTORY_COUNT,
		),
	)

	async def invoke(self, context: CommandContext) -> str:
		"""Read and render recent messages through the injected scoped dependency."""
		if context.history_reader is None:
			return "Message history is not configured."
		channel_id = context.channel_id
		if not isinstance(channel_id, str) or not channel_id.isdecimal():
			raise CommandError("Malformed channel identifier")
		count = context.optional_integer("count", 1, 1, MAX_HISTORY_COUNT)
		try:
			messages = await context.history_reader(channel_id, count)
		except DiscordRestError:
			return "Could not read message history. Check bot access and try again."
		return _format_history(messages)
