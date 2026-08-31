"""Environment-backed configuration for the Discord interaction service."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from nacl.signing import VerifyKey


def _parse_id_set(value: object, field_name: str) -> frozenset[str]:
	"""Parse an optional JSON list or comma-separated allowlist of Discord IDs."""
	if not value:
		return frozenset()

	if isinstance(value, str):
		identifiers = frozenset(item.strip() for item in value.split(",") if item.strip())
	elif isinstance(value, list) and all(isinstance(item, str) for item in value):
		identifiers = frozenset(item.strip() for item in value if item.strip())
	else:
		raise ValueError(f"{field_name} must be a JSON string list or comma-separated Discord IDs")
	if any(not identifier.isdecimal() for identifier in identifiers):
		raise ValueError(f"{field_name} must contain only numeric Discord IDs")
	return identifiers


def _required_discord_id(value: object, field_name: str) -> str:
	"""Validate one required numeric Discord ID without exposing it in errors."""
	if not isinstance(value, str) or not value.isdecimal():
		raise ValueError(f"{field_name} must be set to one numeric Discord ID")
	return value


def _load_configuration_file() -> dict[str, Any]:
	"""Load the optional mounted JSON file without logging its path or contents."""
	configured_path = os.environ.get("DISCORD_SECRETS_FILE", "").strip()
	if not configured_path:
		return {}

	try:
		with Path(configured_path).open("r", encoding="utf-8") as secrets_file:
			values = json.load(secrets_file)
	except (OSError, json.JSONDecodeError) as error:
		raise ValueError("DISCORD_SECRETS_FILE could not be loaded as JSON") from error

	if not isinstance(values, dict):
		raise ValueError("DISCORD_SECRETS_FILE must contain one JSON object")
	return values


def _configuration_value(file_values: dict[str, Any], field_name: str) -> object:
	"""Prefer an explicitly supplied environment value over the mounted JSON field."""
	if field_name in os.environ:
		return os.environ[field_name]
	return file_values.get(field_name)


@dataclass(frozen=True, slots=True)
class Settings:
	"""Hold the verified public key and application authorization allowlists."""

	public_key: VerifyKey
	guild_id: str
	bot_token: str | None = field(default=None, repr=False)
	allowed_channel_ids: frozenset[str] = frozenset()
	allowed_thread_ids: frozenset[str] = frozenset()
	allowed_user_ids: frozenset[str] = frozenset()
	allowed_role_ids: frozenset[str] = frozenset()
	mod_role_ids: frozenset[str] = frozenset()

	@classmethod
	def from_environment(cls) -> Settings:
		"""Load and validate configuration from environment and an optional JSON mount."""
		file_values = _load_configuration_file()
		public_key_value = _configuration_value(file_values, "DISCORD_PUBLIC_KEY")
		public_key_hex = public_key_value.strip() if isinstance(public_key_value, str) else ""
		try:
			public_key = VerifyKey(bytes.fromhex(public_key_hex))
		except (TypeError, ValueError) as error:
			raise ValueError("DISCORD_PUBLIC_KEY must be a 32-byte hexadecimal Ed25519 public key") from error

		bot_token_value = _configuration_value(file_values, "DISCORD_BOT_TOKEN")
		bot_token = bot_token_value.strip() if isinstance(bot_token_value, str) else ""

		return cls(
			public_key=public_key,
			guild_id=_required_discord_id(
				_configuration_value(file_values, "DISCORD_GUILD_ID"),
				"DISCORD_GUILD_ID",
			),
			bot_token=bot_token or None,
			allowed_channel_ids=_parse_id_set(
				_configuration_value(file_values, "DISCORD_ALLOWED_CHANNEL_IDS"),
				"DISCORD_ALLOWED_CHANNEL_IDS",
			),
			allowed_thread_ids=_parse_id_set(
				_configuration_value(file_values, "DISCORD_ALLOWED_THREAD_IDS"),
				"DISCORD_ALLOWED_THREAD_IDS",
			),
			allowed_user_ids=_parse_id_set(
				_configuration_value(file_values, "DISCORD_ALLOWED_USER_IDS"),
				"DISCORD_ALLOWED_USER_IDS",
			),
			allowed_role_ids=_parse_id_set(
				_configuration_value(file_values, "DISCORD_ALLOWED_ROLE_IDS"),
				"DISCORD_ALLOWED_ROLE_IDS",
			),
			mod_role_ids=_parse_id_set(
				_configuration_value(file_values, "DISCORD_MOD_ROLE_IDS"),
				"DISCORD_MOD_ROLE_IDS",
			),
		)
