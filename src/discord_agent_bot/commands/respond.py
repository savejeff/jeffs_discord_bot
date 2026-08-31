"""Deferred proof-of-concept command backed by the private Codex worker."""

from __future__ import annotations

from discord_agent_bot.commands.base import (
	CommandContext,
	CommandDefinition,
	CommandOption,
	STRING_OPTION_TYPE,
)

MAX_RESPOND_PROMPT_LENGTH = 1_000
MAX_DISCORD_RESPONSE_LENGTH = 2_000
TRUNCATION_MARKER = "\n\n[Response truncated for Discord.]"


class RespondCommand(CommandDefinition):
	"""Send one bounded prompt into the worker's single persistent conversation."""

	name = "respond"
	description = "Ask the private Codex worker to answer a prompt."
	order = 70
	deferred = True
	options = (
		CommandOption(
			name="prompt",
			description="Question or instruction for the Codex worker.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			max_length=MAX_RESPOND_PROMPT_LENGTH,
		),
	)

	async def invoke(self, context: CommandContext) -> str:
		"""Submit the user prompt with non-secret routing metadata and bound the answer."""
		context.require_options("prompt")
		prompt = context.string_option("prompt", MAX_RESPOND_PROMPT_LENGTH)
		if context.agent_requester is None:
			raise RuntimeError("The Codex worker requester is unavailable")
		metadata = {
			"source": "discord",
			"command": self.name,
			"guild_id": context.guild_id,
		}
		if context.user_id is not None:
			metadata["user_id"] = context.user_id
		if context.channel_id is not None:
			metadata["channel_id"] = context.channel_id
		answer = await context.agent_requester(prompt, metadata)
		if len(answer) <= MAX_DISCORD_RESPONSE_LENGTH:
			return answer
		content_length = MAX_DISCORD_RESPONSE_LENGTH - len(TRUNCATION_MARKER)
		return answer[:content_length] + TRUNCATION_MARKER
