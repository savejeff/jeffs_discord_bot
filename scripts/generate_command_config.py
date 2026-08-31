"""Generate or verify the reviewable Discord command JSON artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Make the source package available when invoked directly from a checkout or
# from the production image before the package is installed.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SOURCE = PROJECT_ROOT / "src"
if str(PROJECT_SOURCE) not in sys.path:
	sys.path.insert(0, str(PROJECT_SOURCE))

from discord_agent_bot.command_registry import (
	CommandRegistryError,
	discover_command_registry,
)

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "config" / "discord_commands.json"


def _parse_arguments() -> argparse.Namespace:
	"""Parse the output path and non-mutating consistency-check mode."""
	parser = argparse.ArgumentParser(
		description="Generate Discord command JSON from modular Python definitions.",
	)
	parser.add_argument(
		"output_json",
		nargs="?",
		type=Path,
		default=DEFAULT_OUTPUT_PATH,
		help="Generated JSON path (default: config/discord_commands.json).",
	)
	parser.add_argument(
		"--check",
		action="store_true",
		help="Fail when the existing file differs instead of writing it.",
	)
	return parser.parse_args()


def main() -> int:
	"""Discover commands and write or verify their canonical JSON representation."""
	arguments = _parse_arguments()
	try:
		content = discover_command_registry().to_json()
	except CommandRegistryError as error:
		print(f"Command generation failed: {error}", file=sys.stderr)
		return 1

	if arguments.check:
		try:
			current_content = arguments.output_json.read_text(encoding="utf-8")
		except OSError:
			current_content = ""
		if current_content != content:
			print(
				f"Command config is outdated: {arguments.output_json}",
				file=sys.stderr,
			)
			return 1
		print(f"Command config is current: {arguments.output_json}")
		return 0

	try:
		arguments.output_json.parent.mkdir(parents=True, exist_ok=True)
		arguments.output_json.write_text(content, encoding="utf-8")
	except OSError as error:
		print(f"Command config could not be written: {error}", file=sys.stderr)
		return 1
	print(f"Generated {arguments.output_json}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
