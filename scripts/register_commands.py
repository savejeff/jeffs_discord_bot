"""Discover and replace guild commands using a supplied secrets JSON path."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Make the source package available when the script is invoked directly from a
# checkout; the Docker image also supplies this path through PYTHONPATH.
PROJECT_SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SOURCE) not in sys.path:
	sys.path.insert(0, str(PROJECT_SOURCE))

from discord_agent_bot.command_registration import (
	RegistrationCredentials,
	RegistrationError,
	replace_guild_commands,
)
from discord_agent_bot.command_registry import (
	CommandRegistryError,
	discover_command_registry,
)


def _parse_arguments() -> argparse.Namespace:
	"""Parse the credential path and optional non-interactive confirmation."""
	parser = argparse.ArgumentParser(
		description="Replace all guild commands from discovered Python definitions.",
	)
	parser.add_argument(
		"secrets_json",
		type=Path,
		help="Path to secrets.json; credential values are never command arguments.",
	)
	parser.add_argument(
		"--yes",
		action="store_true",
		help="Skip the interactive replacement confirmation prompt.",
	)
	return parser.parse_args()


def _confirmed(command_count: int, skip_confirmation: bool) -> bool:
	"""Require an intentional confirmation before replacing every guild command."""
	if skip_confirmation:
		return True
	answer = input(
		f"Replace all guild commands with {command_count} configured command(s)? [y/N] "
	)
	return answer.strip().lower() in {"y", "yes"}


def main() -> int:
	"""Discover definitions, confirm replacement, then synchronize the guild list."""
	arguments = _parse_arguments()
	try:
		commands = discover_command_registry().to_definitions()
	except CommandRegistryError as error:
		print(f"Registration failed: {error}", file=sys.stderr)
		return 1

	if not _confirmed(len(commands), arguments.yes):
		print("Registration cancelled.")
		return 0

	try:
		credentials = RegistrationCredentials.from_json_file(arguments.secrets_json)
		registered_count = replace_guild_commands(credentials, commands)
	except RegistrationError as error:
		print(f"Registration failed: {error}", file=sys.stderr)
		return 1

	print(f"Successfully synchronized {registered_count} guild command(s).")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
