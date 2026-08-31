"""Deliberate bulk registration of discovered guild commands."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
REGISTRATION_TIMEOUT_SECONDS = 15.0


class RegistrationError(RuntimeError):
	"""Describe a safe command-registration failure without credential content."""


@dataclass(frozen=True, slots=True)
class RegistrationCredentials:
	"""Hold only the Discord values required to register guild commands."""

	application_id: str
	guild_id: str
	bot_token: str = field(repr=False)

	@classmethod
	def from_json_file(cls, secrets_path: Path) -> RegistrationCredentials:
		"""Load required registration values without logging the file or its contents."""
		try:
			with secrets_path.open("r", encoding="utf-8") as secrets_file:
				values = json.load(secrets_file)
		except (OSError, json.JSONDecodeError) as error:
			raise RegistrationError("The secrets file could not be loaded as JSON.") from error

		if not isinstance(values, dict):
			raise RegistrationError("The secrets file must contain one JSON object.")

		application_id = _required_string(values, "DISCORD_APPLICATION_ID")
		guild_id = _required_string(values, "DISCORD_GUILD_ID")
		bot_token = _required_string(values, "DISCORD_BOT_TOKEN")
		if not application_id.isdecimal():
			raise RegistrationError("DISCORD_APPLICATION_ID must be a numeric Discord ID.")
		if not guild_id.isdecimal():
			raise RegistrationError("DISCORD_GUILD_ID must be a numeric Discord ID.")

		return cls(application_id=application_id, guild_id=guild_id, bot_token=bot_token)


def _required_string(values: dict[str, Any], field_name: str) -> str:
	"""Return one non-empty JSON string without exposing its value in errors."""
	value = values.get(field_name)
	if not isinstance(value, str) or not value.strip():
		raise RegistrationError(f"{field_name} must be a non-empty string.")
	return value.strip()


def replace_guild_commands(
	credentials: RegistrationCredentials,
	commands: list[dict[str, Any]],
	opener: Callable[..., Any] = urlopen,
) -> int:
	"""Replace every guild command with the supplied version-controlled definitions."""
	if not commands:
		raise RegistrationError("Refusing to replace guild commands with an empty list.")

	endpoint = (
		f"{DISCORD_API_BASE_URL}/applications/{credentials.application_id}"
		f"/guilds/{credentials.guild_id}/commands"
	)
	request = Request(
		endpoint,
		data=json.dumps(commands, separators=(",", ":")).encode("utf-8"),
		headers={
			"Authorization": f"Bot {credentials.bot_token}",
			"Content-Type": "application/json",
			"User-Agent": "DiscordBot (https://agents.example.com, 1.0)",
		},
		method="PUT",
	)

	try:
		with opener(request, timeout=REGISTRATION_TIMEOUT_SECONDS) as response:
			status_code = response.status
			response.read(64 * 1024)
	except HTTPError as error:
		error.read(64 * 1024)
		raise RegistrationError(
			f"Discord rejected command registration with HTTP status {error.code}."
		) from None
	except URLError as error:
		raise RegistrationError("Could not connect to the Discord API.") from error

	if status_code != 200:
		raise RegistrationError(
			f"Discord returned unexpected HTTP status {status_code} during registration."
		)
	return len(commands)
