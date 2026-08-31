"""Deferred prompt command with persistent tagged-agent selection."""

from __future__ import annotations

import re

from discord_agent_bot.commands.base import (
	CommandContext,
	CommandDefinition,
	CommandError,
	CommandOption,
	STRING_OPTION_TYPE,
)

MAX_PROMPT_LENGTH = 1_000
MAX_AGENT_TAG_LENGTH = 64
MAX_DISCORD_RESPONSE_LENGTH = 2_000
TRUNCATION_MARKER = "\n\n[Response truncated for Discord.]"
AGENT_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _bound_answer(answer: str) -> str:
	"""Fit one selected agent's answer into a Discord interaction response."""
	if len(answer) <= MAX_DISCORD_RESPONSE_LENGTH:
		return answer
	content_length = MAX_DISCORD_RESPONSE_LENGTH - len(TRUNCATION_MARKER)
	return answer[:content_length] + TRUNCATION_MARKER


class PromptCommand(CommandDefinition):
	"""Prompt the default agent or a persistent agent selected by tag."""

	name = "prompt"
	description = "Prompt a persistent tagged Codex agent."
	order = 72
	deferred = True
	options = (
		CommandOption(
			name="prompt",
			description="Question or instruction for the Codex agent.",
			option_type=STRING_OPTION_TYPE,
			required=True,
			min_length=1,
			max_length=MAX_PROMPT_LENGTH,
		),
		CommandOption(
			name="agent_tag",
			description="Persistent agent tag; a new valid tag creates an agent.",
			option_type=STRING_OPTION_TYPE,
			max_length=MAX_AGENT_TAG_LENGTH,
		),
	)

	async def invoke(self, context: CommandContext) -> str:
		"""Route a bounded prompt to one validated persistent agent tag."""
		context.require_option_set(("prompt",), ("agent_tag",))
		prompt = context.string_option("prompt", MAX_PROMPT_LENGTH).strip()
		if not prompt:
			raise CommandError("Prompt cannot be empty")
		agent_tag = context.optional_string("agent_tag", MAX_AGENT_TAG_LENGTH)
		if agent_tag is not None and not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise CommandError(
				"Agent tag must use lowercase letters, digits, underscores, or hyphens"
			)
		if context.agent_requester is None:
			return "The Codex worker is not configured."
		metadata = {
			"source": "discord",
			"command": self.name,
			"guild_id": context.guild_id,
		}
		if context.user_id is not None:
			metadata["user_id"] = context.user_id
		if context.channel_id is not None:
			metadata["channel_id"] = context.channel_id
		answer = await context.agent_requester(prompt, metadata, agent_tag)
		return _bound_answer(answer)
