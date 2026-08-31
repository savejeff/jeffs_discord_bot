"""Discover, validate, and expose the modular Discord command catalog."""

from __future__ import annotations

from importlib import import_module
import inspect
import json
import pkgutil
from types import ModuleType
from typing import Iterable

import discord_agent_bot.commands as commands_package
from discord_agent_bot.commands.base import CommandDefinition, PUBLIC_OPTION_NAME

MAX_DISCORD_MESSAGE_LENGTH = 2_000


class CommandRegistryError(RuntimeError):
	"""Identify an invalid or ambiguous modular command catalog."""


class CommandRegistry:
	"""Provide immutable command lookup, Discord schemas, and generated help text."""

	def __init__(self, commands: Iterable[CommandDefinition]) -> None:
		"""Register each discovered command once and validate the complete catalog."""
		registered: dict[str, CommandDefinition] = {}
		for command in commands:
			self._register(registered, command)
		if not registered:
			raise CommandRegistryError("The command registry cannot be empty.")
		self._commands = tuple(sorted(registered.values(), key=lambda item: (item.order, item.name)))
		self._commands_by_name = {command.name: command for command in self._commands}
		self._help_content = self._format_help()

	@staticmethod
	def _register(
		registered: dict[str, CommandDefinition],
		command: CommandDefinition,
	) -> None:
		"""Validate and add exactly one command definition to the registry."""
		name = getattr(command, "name", None)
		description = getattr(command, "description", None)
		if not isinstance(name, str) or not 1 <= len(name) <= 32:
			raise CommandRegistryError("A command has an invalid name.")
		if not isinstance(description, str) or not 1 <= len(description) <= 100:
			raise CommandRegistryError(f"Command {name} has an invalid description.")
		if command.command_type != 1:
			raise CommandRegistryError(f"Command {name} is not a supported slash command.")
		if type(command.order) is not int:
			raise CommandRegistryError(f"Command {name} has an invalid display order.")
		if (
			type(command.ephemeral) is not bool
			or type(command.deferred) is not bool
			or type(command.mod_only) is not bool
		):
			raise CommandRegistryError(f"Command {name} has invalid response behavior.")
		if name in registered:
			raise CommandRegistryError(f"Command name {name} is registered more than once.")
		if any(option.name == PUBLIC_OPTION_NAME for option in command.options):
			raise CommandRegistryError(
			f"Command {name} must not redefine the universal public option."
		)
		command.to_definition()
		registered[name] = command

	@property
	def commands(self) -> tuple[CommandDefinition, ...]:
		"""Return command objects in their stable display and registration order."""
		return self._commands

	@property
	def help_content(self) -> str:
		"""Return bounded Discord Markdown generated from the registered definitions."""
		return self._help_content

	def get(self, name: str) -> CommandDefinition | None:
		"""Look up one command hook by its Discord command name."""
		return self._commands_by_name.get(name)

	def to_definitions(self) -> list[dict[str, object]]:
		"""Construct the complete Discord bulk-registration payload."""
		return [command.to_definition() for command in self._commands]

	def to_json(self) -> str:
		"""Render the registration payload as the canonical reviewable JSON artifact."""
		return json.dumps(self.to_definitions(), ensure_ascii=False, indent="\t") + "\n"

	def _format_help(self) -> str:
		"""Build Discord Markdown help from the same definitions used for registration."""
		lines = ["## Available commands"]
		for command in self._commands:
			description = " ".join(command.description.replace("`", "").split())
			lines.append(f"- `{command.signature()}` - {description}")
		content = "\n".join(lines)
		if len(content) > MAX_DISCORD_MESSAGE_LENGTH:
			raise CommandRegistryError("The generated command help exceeds Discord's limit.")
		return content


def _command_classes(module: ModuleType) -> list[type[CommandDefinition]]:
	"""Return concrete command classes defined directly by one discovered module."""
	return [
		candidate
		for candidate in vars(module).values()
		if inspect.isclass(candidate)
		and issubclass(candidate, CommandDefinition)
		and candidate is not CommandDefinition
		and not inspect.isabstract(candidate)
		and candidate.__module__ == module.__name__
	]


def discover_command_registry() -> CommandRegistry:
	"""Import each command module and register its single concrete definition."""
	commands: list[CommandDefinition] = []
	prefix = f"{commands_package.__name__}."
	for module_info in pkgutil.iter_modules(commands_package.__path__, prefix):
		module_name = module_info.name.rsplit(".", 1)[-1]
		if module_name == "base" or module_name.startswith("_"):
			continue
		module = import_module(module_info.name)
		classes = _command_classes(module)
		if len(classes) != 1:
			raise CommandRegistryError(
				f"Command module {module_info.name} must define exactly one command class."
			)
		commands.append(classes[0]())
	return CommandRegistry(commands)
