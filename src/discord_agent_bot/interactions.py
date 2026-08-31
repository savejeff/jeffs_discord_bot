"""Interaction authorization and bounded command-response logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from discord_agent_bot.command_registry import CommandRegistry
from discord_agent_bot.commands.base import (
	AgentManager,
	CommandContext,
	CommandDefinition,
	CommandError,
	AgentListReader,
	AgentRequester,
	AgentStatusReader,
	AgentThreadCreator,
	HistoryReader,
	SleepFunction,
)
from discord_agent_bot.config import Settings

APPLICATION_COMMAND_TYPE = 2
PING_TYPE = 1
PONG_RESPONSE_TYPE = 1
CHANNEL_MESSAGE_RESPONSE_TYPE = 4
DEFERRED_CHANNEL_MESSAGE_RESPONSE_TYPE = 5
EPHEMERAL_FLAG = 64


class InteractionError(ValueError):
	"""Identify a verified but malformed or unsupported interaction payload."""


@dataclass(frozen=True, slots=True)
class DeferredCommandAction:
	"""Retain the validated data needed to finish one deferred command safely."""

	application_id: str
	interaction_token: str = field(repr=False)
	command: CommandDefinition
	context: CommandContext = field(repr=False)


@dataclass(frozen=True, slots=True)
class InteractionResult:
	"""Return the immediate Discord payload and any post-response command action."""

	payload: dict[str, Any]
	deferred_action: DeferredCommandAction | None = field(default=None, repr=False)


def safe_message_data(content: str, ephemeral: bool) -> dict[str, Any]:
	"""Build message data with automatic Discord mentions disabled."""
	data: dict[str, Any] = {
		"content": content,
		"allowed_mentions": {
			"parse": [],
			"roles": [],
			"users": [],
			"replied_user": False,
		},
	}
	if ephemeral:
		data["flags"] = EPHEMERAL_FLAG
	return data


def _safe_message(content: str, ephemeral: bool = True) -> InteractionResult:
	"""Build an immediate mention-safe response with the requested visibility."""
	return InteractionResult({
		"type": CHANNEL_MESSAGE_RESPONSE_TYPE,
		"data": safe_message_data(content, ephemeral),
	})


def _deferred_action(
	interaction: dict[str, Any],
	command: CommandDefinition,
	context: CommandContext,
	ephemeral: bool,
) -> InteractionResult:
	"""Validate webhook routing and construct Discord's immediate deferred acknowledgement."""
	application_id = interaction.get("application_id")
	interaction_token = interaction.get("token")
	if (
		not isinstance(application_id, str)
		or not application_id.isdecimal()
		or len(application_id) > 32
	):
		raise InteractionError("Malformed deferred application identifier")
	if (
		not isinstance(interaction_token, str)
		or not interaction_token
		or len(interaction_token) > 512
	):
		raise InteractionError("Malformed deferred interaction token")
	data = {"flags": EPHEMERAL_FLAG} if ephemeral else {}
	return InteractionResult(
		payload={"type": DEFERRED_CHANNEL_MESSAGE_RESPONSE_TYPE, "data": data},
		deferred_action=DeferredCommandAction(
			application_id=application_id,
			interaction_token=interaction_token,
			command=command,
			context=context,
		),
	)


def _is_authorized(interaction: dict[str, Any], settings: Settings) -> bool:
	"""Apply guild, destination, user, and role allowlists with default-deny semantics."""
	if interaction.get("guild_id") != settings.guild_id:
		return False

	destination_allowlist = settings.allowed_channel_ids | settings.allowed_thread_ids
	if destination_allowlist and interaction.get("channel_id") not in destination_allowlist:
		return False

	actor_allowlist_configured = bool(settings.allowed_user_ids or settings.allowed_role_ids)
	if not actor_allowlist_configured:
		return True

	user_id, role_ids = _member_identity(interaction)
	return user_id in settings.allowed_user_ids or bool(role_ids & settings.allowed_role_ids)


def _member_identity(interaction: dict[str, Any]) -> tuple[str | None, frozenset[str]]:
	"""Extract the invoking guild member ID and numeric role IDs for command policy."""
	member = interaction.get("member")
	if not isinstance(member, dict):
		return None, frozenset()
	user = member.get("user")
	user_id = user.get("id") if isinstance(user, dict) else None
	if not isinstance(user_id, str) or not user_id.isdecimal():
		user_id = None
	roles = member.get("roles")
	if not isinstance(roles, list) or not all(
		isinstance(role, str) and role.isdecimal() for role in roles
	):
		return user_id, frozenset()
	return user_id, frozenset(roles)


def _command_options(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
	"""Validate command options and index them by their unique Discord option names."""
	values = data.get("options", [])
	if not isinstance(values, list):
		raise InteractionError("Malformed command options")

	options: dict[str, dict[str, Any]] = {}
	for value in values:
		if not isinstance(value, dict) or not isinstance(value.get("name"), str):
			raise InteractionError("Malformed command options")
		name = value["name"]
		if name in options:
			raise InteractionError("Duplicate command option")
		options[name] = value
	return options


async def handle_interaction(
	interaction: object,
	settings: Settings,
	uptime_ms: int,
	history_reader: HistoryReader | None,
	command_registry: CommandRegistry,
	sleep: SleepFunction,
	agent_requester: AgentRequester | None,
	agent_status_reader: AgentStatusReader | None,
	agent_list_reader: AgentListReader | None,
	agent_thread_creator: AgentThreadCreator | None,
	agent_manager: AgentManager | None,
) -> InteractionResult:
	"""Dispatch one verified and authorized Discord interaction to approved handlers."""
	if not isinstance(interaction, dict):
		raise InteractionError("Malformed interaction")

	interaction_type = interaction.get("type")
	if interaction_type == PING_TYPE:
		return InteractionResult({"type": PONG_RESPONSE_TYPE})
	if interaction_type != APPLICATION_COMMAND_TYPE:
		raise InteractionError("Unsupported interaction type")
	if not _is_authorized(interaction, settings):
		return _safe_message("This interaction is not available.")

	data = interaction.get("data")
	if not isinstance(data, dict) or data.get("type", 1) != 1:
		raise InteractionError("Malformed command")
	command_name = data.get("name")
	if not isinstance(command_name, str):
		raise InteractionError("Malformed command name")
	options = _command_options(data)
	command = command_registry.get(command_name)
	if command is None:
		return _safe_message("Unsupported command.")

	user_id, member_role_ids = _member_identity(interaction)
	context = CommandContext(
		guild_id=settings.guild_id,
		channel_id=(
			interaction.get("channel_id")
			if isinstance(interaction.get("channel_id"), str)
			else None
		),
		user_id=user_id,
		member_role_ids=member_role_ids,
		options=options,
		uptime_ms=uptime_ms,
		history_reader=history_reader,
		help_content=command_registry.help_content,
		sleep=sleep,
		agent_requester=agent_requester,
		agent_status_reader=agent_status_reader,
		agent_list_reader=agent_list_reader,
		agent_thread_creator=agent_thread_creator,
		agent_manager=agent_manager,
	)
	if command.mod_only and not (member_role_ids & settings.mod_role_ids):
		return _safe_message("This interaction is not available.")
	try:
		ephemeral = command.response_is_ephemeral(context)
	except CommandError as error:
		raise InteractionError("Malformed command input") from error
	if command.deferred:
		return _deferred_action(interaction, command, context, ephemeral)
	try:
		content = await command.invoke(context)
	except CommandError as error:
		raise InteractionError("Malformed command input") from error
	if not isinstance(content, str):
		raise InteractionError("Command hook returned invalid content")
	return _safe_message(content, ephemeral)
