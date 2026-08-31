"""Creation boundary for durable creator-owned Discord agent threads."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from discord_agent_bot.commands.base import (
	AgentThreadBindingResult,
	AgentThreadError,
)
from discord_agent_bot.discord_rest import DiscordRestClient, DiscordRestError
from discord_agent_bot.thread_bindings import (
	ThreadBindingStore,
	ThreadBindingStoreError,
)


@dataclass(frozen=True, slots=True)
class DiscordAgentThreadCreator:
	"""Create a public Discord thread with a creator-to-agent binding."""

	rest_client: DiscordRestClient
	binding_store: ThreadBindingStore

	async def __call__(
		self,
		guild_id: str,
		parent_channel_id: str,
		creator_user_id: str,
		agent_tag: str,
	) -> AgentThreadBindingResult:
		"""Create and introduce a thread for the explicitly selected local agent."""
		thread_name = f"agent-{agent_tag}"
		try:
			created_thread = await asyncio.to_thread(
				self.rest_client.create_public_thread,
				parent_channel_id,
				thread_name,
			)
			await asyncio.to_thread(
				self.binding_store.bind_thread,
				created_thread.thread_id,
				guild_id,
				created_thread.parent_channel_id,
				agent_tag,
				creator_user_id,
			)
		except (DiscordRestError, ThreadBindingStoreError) as error:
			raise AgentThreadError("The agent thread could not be created.") from error

		introduction = (
			f"This thread is connected to agent `{agent_tag}`. "
			"Only ordinary messages from its creator are forwarded to the agent. "
			"Archiving or deleting the thread closes this connection without removing the agent."
		)
		try:
			await asyncio.to_thread(
				self.rest_client.create_message,
				created_thread.thread_id,
				introduction,
			)
		except DiscordRestError:
			# The durable binding remains useful even if the informational message fails.
			pass
		return AgentThreadBindingResult(
			thread_id=created_thread.thread_id,
			agent_tag=agent_tag,
		)
