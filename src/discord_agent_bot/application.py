"""ASGI transport for verified Discord interaction requests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
import os
from pathlib import Path
from time import monotonic, perf_counter
from typing import Any

from nacl.exceptions import BadSignatureError
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from discord_agent_bot.agent_threads import DiscordAgentThreadCreator
from discord_agent_bot.command_registry import CommandRegistry, discover_command_registry
from discord_agent_bot.codex_worker_client import CodexWorkerClient
from discord_agent_bot.commands.base import (
	AgentManager,
	AgentListReader,
	AgentRequester,
	AgentStatusReader,
	AgentThreadCreator,
	CommandError,
	HistoryReader,
	SleepFunction,
)
from discord_agent_bot.config import Settings
from discord_agent_bot.discord_rest import (
	DiscordRestClient,
	InteractionWebhookClient,
	RecentMessage,
)
from discord_agent_bot.interactions import (
	DeferredCommandAction,
	InteractionError,
	handle_interaction,
)
from discord_agent_bot.thread_bindings import ThreadBindingStore

LOGGER = logging.getLogger("discord_agent_bot")
MAX_REQUEST_BYTES = 64 * 1024
DeferredResponder = Callable[[str, str, str], Awaitable[None]]


class BoundAgentManager:
	"""Combine worker lifecycle calls with Discord thread-binding cleanup."""

	def __init__(
		self,
		worker_manager: AgentManager,
		binding_store: ThreadBindingStore | None,
	) -> None:
		"""Retain the two stores whose state forms one Discord-facing agent."""
		self._worker_manager = worker_manager
		self._binding_store = binding_store

	async def configure(
		self,
		agent_tag: str,
		model: str,
		reasoning_level: str,
	) -> None:
		"""Delegate a runtime-profile update to the private worker."""
		await self._worker_manager.configure(agent_tag, model, reasoning_level)

	async def reset(self, agent_tag: str) -> None:
		"""Delegate workspace restoration without altering thread bindings."""
		await self._worker_manager.reset(agent_tag)

	async def delete(self, agent_tag: str) -> None:
		"""Delete worker state first, then remove every matching Discord binding."""
		await self._worker_manager.delete(agent_tag)
		if self._binding_store is not None:
			await asyncio.to_thread(self._binding_store.delete_agent_bindings, agent_tag)


async def _finish_deferred_command(
	action: DeferredCommandAction,
	responder: DeferredResponder,
) -> None:
	"""Run a deferred hook after acknowledgement and safely edit its original response."""
	try:
		content = await action.command.invoke(action.context)
		if not isinstance(content, str):
			raise TypeError("Command hook returned invalid content")
	except CommandError:
		content = "The deferred command input was invalid."
	except Exception as error:
		LOGGER.error(
			"deferred_command_failed command=%r error_type=%s",
			action.command.name,
			type(error).__name__,
		)
		content = "The deferred command could not be completed."
	try:
		await responder(action.application_id, action.interaction_token, content)
	except Exception as error:
		LOGGER.error(
			"deferred_response_failed command=%r error_type=%s",
			action.command.name,
			type(error).__name__,
		)


async def _read_bounded_body(request: Request) -> bytes:
	"""Read the exact request bytes while enforcing the public endpoint size limit."""
	body = bytearray()
	async for chunk in request.stream():
		body.extend(chunk)
		if len(body) > MAX_REQUEST_BYTES:
			raise InteractionError("Request body is too large")
	return bytes(body)


def _has_valid_signature(request: Request, body: bytes, settings: Settings) -> bool:
	"""Verify Discord's signature over the timestamp and unchanged raw body."""
	signature_hex = request.headers.get("x-signature-ed25519", "")
	timestamp = request.headers.get("x-signature-timestamp", "")
	try:
		signature = bytes.fromhex(signature_hex)
		settings.public_key.verify(timestamp.encode("ascii") + body, signature)
		return bool(timestamp)
	except (BadSignatureError, UnicodeEncodeError, ValueError):
		return False


def _metadata(interaction: object) -> tuple[object, object]:
	"""Return only non-content metadata suitable for structured operational logs."""
	if not isinstance(interaction, dict):
		return None, None
	data = interaction.get("data")
	command_name = data.get("name") if isinstance(data, dict) else None
	return interaction.get("type"), command_name


def create_app(
	settings: Settings | None = None,
	history_reader: HistoryReader | None = None,
	clock: Callable[[], float] = monotonic,
	command_registry: CommandRegistry | None = None,
	sleep: SleepFunction = asyncio.sleep,
	deferred_responder: DeferredResponder | None = None,
	agent_requester: AgentRequester | None = None,
	agent_status_reader: AgentStatusReader | None = None,
	agent_list_reader: AgentListReader | None = None,
	agent_thread_creator: AgentThreadCreator | None = None,
	agent_manager: AgentManager | None = None,
	thread_binding_store: ThreadBindingStore | None = None,
) -> Starlette:
	"""Create the ASGI service using supplied test settings or deployment environment."""
	uses_deployment_environment = settings is None
	active_settings = settings or Settings.from_environment()
	application_started_at = clock()
	active_command_registry = command_registry or discover_command_registry()
	worker_client = CodexWorkerClient(
		url=os.environ.get(
			"CODEX_WORKER_WEBSOCKET_URL",
			"ws://codex-agent-worker:8090/ws",
		),
		response_timeout_seconds=float(
			os.environ.get("CODEX_WORKER_RESPONSE_TIMEOUT_SECONDS", "840")
		),
	)
	active_agent_requester = agent_requester or worker_client.ask
	active_agent_status_reader = agent_status_reader or worker_client.status
	active_agent_list_reader = agent_list_reader or worker_client.list_agents
	active_thread_binding_store = thread_binding_store
	if active_thread_binding_store is None and uses_deployment_environment:
		active_thread_binding_store = ThreadBindingStore(
			Path(
				os.environ.get(
					"DISCORD_GATEWAY_DATABASE",
					"/var/lib/discord-gateway/gateway.db",
				)
			)
		)
	active_agent_thread_creator = agent_thread_creator
	if (
		active_agent_thread_creator is None
		and active_thread_binding_store is not None
		and active_settings.bot_token
	):
		active_agent_thread_creator = DiscordAgentThreadCreator(
			DiscordRestClient(active_settings.bot_token),
			active_thread_binding_store,
		)
	if active_thread_binding_store is not None:
		worker_agent_list_reader = active_agent_list_reader

		async def list_all_agents() -> tuple[str, ...]:
			"""Merge worker-known tags with agents retained by closed thread bindings."""
			worker_tags = await worker_agent_list_reader()
			binding_tags = await asyncio.to_thread(
				active_thread_binding_store.list_agent_tags
			)
			return tuple(sorted(set(worker_tags) | set(binding_tags)))

		active_agent_list_reader = list_all_agents
	active_agent_manager = BoundAgentManager(
		agent_manager or worker_client,
		active_thread_binding_store,
	)
	active_webhook_client = InteractionWebhookClient()
	active_deferred_responder = deferred_responder
	if active_deferred_responder is None:
		async def respond_to_deferred(
			application_id: str,
			interaction_token: str,
			content: str,
		) -> None:
			"""Move the blocking deferred-response PATCH off the ASGI event loop."""
			await asyncio.to_thread(
				active_webhook_client.edit_original_response,
				application_id,
				interaction_token,
				content,
			)

		active_deferred_responder = respond_to_deferred
	active_history_reader = history_reader
	if active_history_reader is None and active_settings.bot_token:
		discord_rest = DiscordRestClient(active_settings.bot_token)

		async def read_history(channel_id: str, limit: int) -> list[RecentMessage]:
			"""Run the blocking standard-library REST call outside the ASGI event loop."""
			return await asyncio.to_thread(discord_rest.get_recent_messages, channel_id, limit)

		active_history_reader = read_history

	async def health(_request: Request) -> JSONResponse:
		"""Expose a non-identifying readiness response for local/container checks."""
		return JSONResponse({"status": "ok"})

	async def interactions(request: Request) -> JSONResponse:
		"""Verify, authorize, and immediately answer or acknowledge one interaction."""
		started_at = perf_counter()
		status_code = 200
		outcome = "handled"
		interaction: object = None

		if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
			return JSONResponse({"error": "Unsupported content type"}, status_code=415)

		try:
			body = await _read_bounded_body(request)
		except InteractionError:
			return JSONResponse({"error": "Invalid request"}, status_code=413)

		if not _has_valid_signature(request, body, active_settings):
			return JSONResponse({"error": "Invalid request signature"}, status_code=401)

		try:
			interaction = json.loads(body)
			uptime_ms = int(max(0.0, clock() - application_started_at) * 1_000)
			interaction_result = await handle_interaction(
				interaction,
				active_settings,
				uptime_ms,
				active_history_reader,
				active_command_registry,
				sleep,
				active_agent_requester,
				active_agent_status_reader,
				active_agent_list_reader,
				active_agent_thread_creator,
				active_agent_manager,
			)
		except (InteractionError, json.JSONDecodeError, UnicodeDecodeError):
			status_code = 400
			outcome = "rejected"
			interaction_result = None
			response_payload = {"error": "Invalid interaction"}
		else:
			response_payload = interaction_result.payload

		interaction_type, command_name = _metadata(interaction)
		LOGGER.info(
			"interaction_result type=%r command=%r outcome=%s status=%d elapsed_ms=%.2f",
			interaction_type,
			command_name,
			outcome,
			status_code,
			(perf_counter() - started_at) * 1000,
		)
		background = None
		if interaction_result is not None and interaction_result.deferred_action is not None:
			background = BackgroundTask(
				_finish_deferred_command,
				interaction_result.deferred_action,
				active_deferred_responder,
			)
		return JSONResponse(response_payload, status_code=status_code, background=background)

	return Starlette(
		debug=False,
		routes=[
			Route("/health", health, methods=["GET"]),
			Route("/discord/interactions", interactions, methods=["POST"]),
		],
	)
