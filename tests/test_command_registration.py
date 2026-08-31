"""Offline tests for deliberate bulk guild-command registration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from discord_agent_bot.command_registration import (
	DISCORD_API_BASE_URL,
	RegistrationCredentials,
	RegistrationError,
	replace_guild_commands,
)
from discord_agent_bot.command_registry import (
	CommandRegistry,
	CommandRegistryError,
	discover_command_registry,
)
from discord_agent_bot.commands.base import CommandContext, CommandDefinition

APPLICATION_ID = "100000000000000006"
GUILD_ID = "100000000000000001"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_OPTION_DEFINITION = {
	"name": "public",
	"description": "Show the response to everyone in the channel.",
	"type": 5,
	"required": False,
}


class _FakeResponse:
	"""Provide the small successful urllib response surface used by registration."""

	status = 200

	def __enter__(self) -> _FakeResponse:
		return self

	def __exit__(self, *_args: object) -> None:
		return None

	def read(self, _limit: int) -> bytes:
		return b"[]"


def test_credentials_load_without_exposing_token_in_repr(tmp_path: Path) -> None:
	"""Read required JSON fields while keeping token values out of object rendering."""
	token = uuid4().hex
	secrets_path = tmp_path / "secrets.json"
	secrets_path.write_text(
		json.dumps(
			{
				"DISCORD_APPLICATION_ID": APPLICATION_ID,
				"DISCORD_GUILD_ID": GUILD_ID,
				"DISCORD_BOT_TOKEN": token,
			}
		),
		encoding="utf-8",
	)

	credentials = RegistrationCredentials.from_json_file(secrets_path)

	assert credentials.application_id == APPLICATION_ID
	assert credentials.guild_id == GUILD_ID
	assert credentials.bot_token == token
	assert token not in repr(credentials)


def test_missing_token_is_rejected_without_file_content(tmp_path: Path) -> None:
	"""Reject incomplete configuration with a field-specific, value-free message."""
	secrets_path = tmp_path / "secrets.json"
	secrets_path.write_text(
		json.dumps(
			{
				"DISCORD_APPLICATION_ID": APPLICATION_ID,
				"DISCORD_GUILD_ID": GUILD_ID,
				"DISCORD_BOT_TOKEN": "",
			}
		),
		encoding="utf-8",
	)

	with pytest.raises(RegistrationError, match="DISCORD_BOT_TOKEN must be a non-empty string"):
		RegistrationCredentials.from_json_file(secrets_path)


def test_version_control_command_list_contains_all_supported_commands() -> None:
	"""Validate discovery produces the complete schema and generated review artifact."""
	registry = discover_command_registry()
	commands = registry.to_definitions()

	assert [command["name"] for command in commands] == [
		"hello",
		"echo",
		"millis",
		"add",
		"dev_history",
		"dev_public",
		"dev_deferred",
		"respond",
		"prompt",
		"agent_thread",
		"explain",
		"summarize",
		"agent_list",
		"agent_config",
		"agent_reset",
		"agent_delete",
		"agent_report",
		"help",
	]
	assert commands[0]["description"] == "Return world!"
	assert commands[0]["options"] == [PUBLIC_OPTION_DEFINITION]
	assert all(command["options"][-1] == PUBLIC_OPTION_DEFINITION for command in commands)
	commands_by_name = {command["name"]: command for command in commands}
	assert [option["name"] for option in commands_by_name["echo"]["options"]] == [
		"text",
		"public",
	]
	assert [option["name"] for option in commands_by_name["add"]["options"]] == [
		"left",
		"right",
		"public",
	]
	assert commands_by_name["dev_history"]["options"] == [
		{
			"name": "count",
			"description": "Number of recent messages to return (default 1).",
			"type": 4,
			"required": False,
			"min_value": 1,
			"max_value": 10,
		},
		PUBLIC_OPTION_DEFINITION,
	]
	assert commands_by_name["help"]["options"] == [PUBLIC_OPTION_DEFINITION]
	assert commands_by_name["dev_public"]["options"] == [PUBLIC_OPTION_DEFINITION]
	assert commands_by_name["dev_deferred"]["options"] == [PUBLIC_OPTION_DEFINITION]
	assert commands_by_name["respond"]["options"] == [
		{
			"name": "prompt",
			"description": "Question or instruction for the Codex worker.",
			"type": 3,
			"required": True,
			"max_length": 1_000,
		},
		{
			"name": "public",
			"description": "Show the response to everyone in the channel.",
			"type": 5,
			"required": False,
		},
	]
	assert commands_by_name["prompt"]["options"] == [
		{
			"name": "prompt",
			"description": "Question or instruction for the Codex agent.",
			"type": 3,
			"required": True,
			"min_length": 1,
			"max_length": 1_000,
		},
		{
			"name": "agent_tag",
			"description": "Persistent agent tag; a new valid tag creates an agent.",
			"type": 3,
			"required": False,
			"max_length": 64,
		},
		PUBLIC_OPTION_DEFINITION,
	]
	assert commands_by_name["agent_thread"]["options"] == [
		{
			"name": "agent_tag",
			"description": "Required existing or new persistent agent tag.",
			"type": 3,
			"required": True,
			"max_length": 64,
		},
		{
			"name": "model",
			"description": "Model shorthand; each value also sets its reasoning level.",
			"type": 3,
			"required": True,
			"choices": [
				{"name": alias, "value": alias}
				for alias in (
					"low",
					"medium",
					"high",
					"luna-low",
					"luna-medium",
					"luna-high",
					"terra-low",
					"terra-medium",
					"terra-high",
				)
			],
		},
		PUBLIC_OPTION_DEFINITION,
	]
	assert commands_by_name["explain"]["options"] == [
		{
			"name": "topic",
			"description": "Topic or question to explain.",
			"type": 3,
			"required": True,
			"min_length": 1,
			"max_length": 1_000,
		},
		{
			"name": "public",
			"description": "Show the response to everyone in the channel.",
			"type": 5,
			"required": False,
		},
	]
	assert commands_by_name["summarize"]["options"] == [
		{
			"name": "topic",
			"description": "Topic or question the summary should focus on.",
			"type": 3,
			"required": True,
			"min_length": 1,
			"max_length": 500,
		},
		{
			"name": "public",
			"description": "Show the response to everyone in the channel.",
			"type": 5,
			"required": False,
		},
	]
	assert commands_by_name["agent_list"]["options"] == [PUBLIC_OPTION_DEFINITION]
	assert commands_by_name["agent_config"]["options"] == [
		{
			"name": "agent_tag",
			"description": "Agent tag to configure.",
			"type": 3,
			"required": True,
			"max_length": 64,
		},
		{
			"name": "model",
			"description": "Model shorthand; each value also sets its reasoning level.",
			"type": 3,
			"required": True,
			"choices": [
				{"name": alias, "value": alias}
				for alias in (
					"low",
					"medium",
					"high",
					"luna-low",
					"luna-medium",
					"luna-high",
					"terra-low",
					"terra-medium",
					"terra-high",
				)
			],
		},
		PUBLIC_OPTION_DEFINITION,
	]
	for command_name in ("agent_reset", "agent_delete"):
		assert [
			option["name"] for option in commands_by_name[command_name]["options"]
		] == ["agent_tag", "public"]
	assert commands_by_name["agent_report"]["options"] == [
		{
			"name": "agent_tag",
			"description": "Agent tag to report.",
			"type": 3,
			"required": True,
			"max_length": 64,
		},
		PUBLIC_OPTION_DEFINITION,
	]
	assert (PROJECT_ROOT / "config" / "discord_commands.json").read_text(
		encoding="utf-8"
	) == registry.to_json()


def test_each_command_is_owned_by_a_separate_discovered_module() -> None:
	"""Keep every concrete command definition and hook isolated in its own module."""
	commands = discover_command_registry().commands
	module_names = [command.__class__.__module__ for command in commands]

	assert len(module_names) == len(set(module_names))
	assert all(module_name.startswith("discord_agent_bot.commands.") for module_name in module_names)


def test_help_is_discord_markdown_derived_from_the_complete_catalog() -> None:
	"""Render every slash command with required and optional argument notation."""
	help_content = discover_command_registry().help_content

	assert help_content.startswith("## Available commands\n")
	assert "- `/hello [public]` - Return world!" in help_content
	assert "- `/echo <text> [public]` - Return the supplied text." in help_content
	assert "- `/add <left> <right> [public]` - Add two numbers" in help_content
	assert "- `/dev_history [count] [public]` - Return recent messages" in help_content
	assert "- `/dev_public [public]` - Return a response visible to everyone" in help_content
	assert "- `/dev_deferred [public]` - Return after a delay longer than 15 seconds." in help_content
	assert "- `/respond <prompt> [public]` - Ask the private Codex worker" in help_content
	assert "- `/prompt <prompt> [agent_tag] [public]` - Prompt a persistent tagged" in help_content
	assert "- `/agent_thread <agent_tag> <model> [public]` - Create a creator-only" in help_content
	assert "- `/explain <topic> [public]` - Explain a topic using the application wiki" in help_content
	assert "- `/summarize <topic> [public]` - Summarize recent channel" in help_content
	assert "- `/agent_list [public]` - List configured and previously created" in help_content
	assert "- `/agent_config <agent_tag> <model> [public]`" in help_content
	assert "- `/agent_reset <agent_tag> [public]`" in help_content
	assert "- `/agent_delete <agent_tag> [public]`" in help_content
	assert (
		"- `/agent_report <agent_tag> [public]` - Show one tagged agent's "
		"moderator-only worker status report."
	) in help_content
	assert "- `/help [public]` - Show all available commands." in help_content
	assert len(help_content) <= 2_000


def test_empty_command_registry_is_rejected_before_discord_mutation() -> None:
	"""Prevent an empty discovered package from deleting every registered command."""
	with pytest.raises(CommandRegistryError, match="cannot be empty"):
		CommandRegistry([])


def test_duplicate_command_names_are_rejected() -> None:
	"""Reject ambiguous modular hooks before runtime dispatch or registration."""
	class FirstCommand(CommandDefinition):
		"""Provide the first synthetic definition for duplicate validation."""

		name = "duplicate"
		description = "First synthetic command."

		async def invoke(self, _context: CommandContext) -> str:
			"""Return an unused synthetic response."""
			return "first"

	class SecondCommand(CommandDefinition):
		"""Provide the second synthetic definition for duplicate validation."""

		name = "duplicate"
		description = "Second synthetic command."

		async def invoke(self, _context: CommandContext) -> str:
			"""Return an unused synthetic response."""
			return "second"

	with pytest.raises(CommandRegistryError, match="registered more than once"):
		CommandRegistry([FirstCommand(), SecondCommand()])


def test_registration_bulk_overwrites_with_complete_command_list() -> None:
	"""Verify the bulk endpoint, authentication header, and complete JSON payload offline."""
	token = uuid4().hex
	credentials = RegistrationCredentials(
		application_id=APPLICATION_ID,
		guild_id=GUILD_ID,
		bot_token=token,
	)
	commands = discover_command_registry().to_definitions()
	captured: dict[str, Any] = {}

	def fake_opener(request: Any, timeout: float) -> _FakeResponse:
		"""Capture the outbound request without performing network access."""
		captured["request"] = request
		captured["timeout"] = timeout
		return _FakeResponse()

	registered_count = replace_guild_commands(credentials, commands, opener=fake_opener)
	request = captured["request"]
	payload = json.loads(request.data)

	assert registered_count == len(commands)
	assert request.full_url == (
		f"{DISCORD_API_BASE_URL}/applications/{APPLICATION_ID}/guilds/{GUILD_ID}/commands"
	)
	assert request.method == "PUT"
	assert request.get_header("Authorization") == f"Bot {token}"
	assert token.encode("utf-8") not in request.data
	assert captured["timeout"] == 15.0
	assert payload == commands
