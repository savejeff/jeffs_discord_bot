"""Base contracts shared by independently discoverable command modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from discord_agent_bot.discord_rest import RecentMessage

CHAT_INPUT_COMMAND_TYPE = 1
STRING_OPTION_TYPE = 3
INTEGER_OPTION_TYPE = 4
BOOLEAN_OPTION_TYPE = 5
PUBLIC_OPTION_NAME = "public"

HistoryReader = Callable[[str, int], Awaitable[list[RecentMessage]]]
SleepFunction = Callable[[float], Awaitable[None]]


class AgentRequester(Protocol):
	"""Submit a prompt to the default or explicitly tagged persistent agent."""

	def __call__(
		self,
		prompt: str,
		metadata: Mapping[str, str],
		agent_tag: str | None = None,
	) -> Awaitable[str]:
		"""Return the delayed answer from the selected agent tag."""


@dataclass(frozen=True, slots=True)
class AgentThreadBindingResult:
	"""Describe a created Discord thread and its persistent agent tag."""

	thread_id: str
	agent_tag: str


class AgentThreadCreator(Protocol):
	"""Create a Discord thread with a creator-only agent binding."""

	def __call__(
		self,
		guild_id: str,
		parent_channel_id: str,
		creator_user_id: str,
		agent_tag: str,
	) -> Awaitable[AgentThreadBindingResult]:
		"""Return the created thread and its explicitly requested agent tag."""


class AgentManager(Protocol):
	"""Expose only the approved tagged-agent lifecycle operations to commands."""

	def configure(
		self,
		agent_tag: str,
		model: str,
		reasoning_level: str,
	) -> Awaitable[None]:
		"""Persist and apply one tagged agent's runtime settings."""

	def reset(self, agent_tag: str) -> Awaitable[None]:
		"""Restore one tagged agent workspace from the bundled template."""

	def delete(self, agent_tag: str) -> Awaitable[None]:
		"""Remove one tagged agent and its persistent state."""


class CommandError(ValueError):
	"""Identify malformed command input without exposing confidential content."""


class AgentStatusError(RuntimeError):
	"""Identify a redacted worker status transport or validation failure."""


class AgentThreadError(RuntimeError):
	"""Identify a redacted thread creation or binding failure."""


@dataclass(frozen=True, slots=True)
class RecentAgentCommand:
	"""Describe one non-content worker request for moderator reporting."""

	received_at: str
	command: str
	status: str
	user_id: str | None
	channel_id: str | None


@dataclass(frozen=True, slots=True)
class AgentStatus:
	"""Hold validated worker activity counters without prompt or response content."""

	agent_tag: str
	state: str
	model: str | None
	reasoning_level: str | None
	runtime_profile_scope: str
	queued: int
	processing: int
	processed: int
	completed: int
	failed: int
	total_active_seconds: float
	today_active_seconds: float
	time_zone: str
	recent_commands: tuple[RecentAgentCommand, ...]


AgentStatusReader = Callable[[str], Awaitable[AgentStatus]]
AgentListReader = Callable[[], Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class CommandOption:
	"""Describe one Discord command option and serialize its registration schema."""

	name: str
	description: str
	option_type: int
	required: bool = False
	choices: tuple[Mapping[str, Any], ...] = ()
	options: tuple[CommandOption, ...] = ()
	channel_types: tuple[int, ...] = ()
	min_value: int | float | None = None
	max_value: int | float | None = None
	min_length: int | None = None
	max_length: int | None = None
	autocomplete: bool = False

	def to_definition(self) -> dict[str, Any]:
		"""Return the option fields accepted by Discord's registration API."""
		definition: dict[str, Any] = {
			"name": self.name,
			"description": self.description,
			"type": self.option_type,
			"required": self.required,
		}
		if self.choices:
			definition["choices"] = [dict(choice) for choice in self.choices]
		if self.options:
			definition["options"] = [option.to_definition() for option in self.options]
		if self.channel_types:
			definition["channel_types"] = list(self.channel_types)
		if self.min_value is not None:
			definition["min_value"] = self.min_value
		if self.max_value is not None:
			definition["max_value"] = self.max_value
		if self.min_length is not None:
			definition["min_length"] = self.min_length
		if self.max_length is not None:
			definition["max_length"] = self.max_length
		if self.autocomplete:
			definition["autocomplete"] = True
		return definition


PUBLIC_RESPONSE_OPTION = CommandOption(
	name=PUBLIC_OPTION_NAME,
	description="Show the response to everyone in the channel.",
	option_type=BOOLEAN_OPTION_TYPE,
)


@dataclass(frozen=True, slots=True)
class CommandContext:
	"""Provide one command with validated transport context and approved dependencies."""

	guild_id: str
	channel_id: str | None
	user_id: str | None
	member_role_ids: frozenset[str]
	options: dict[str, dict[str, Any]]
	uptime_ms: int
	history_reader: HistoryReader | None
	help_content: str
	sleep: SleepFunction
	agent_requester: AgentRequester | None
	agent_status_reader: AgentStatusReader | None
	agent_list_reader: AgentListReader | None
	agent_thread_creator: AgentThreadCreator | None
	agent_manager: AgentManager | None

	def require_options(self, *names: str) -> None:
		"""Require command-specific options while allowing universal options."""
		actual_names = set(self.options) - {PUBLIC_OPTION_NAME}
		if actual_names != set(names):
			raise CommandError("The command options do not match its definition")

	def require_option_set(
		self,
		required: tuple[str, ...],
		optional: tuple[str, ...] = (),
	) -> None:
		"""Require all mandatory names while allowing only the declared optional names."""
		actual_names = set(self.options) - {PUBLIC_OPTION_NAME}
		required_names = set(required)
		allowed_names = required_names | set(optional)
		if not required_names <= actual_names or not actual_names <= allowed_names:
			raise CommandError("The command options do not match its definition")

	def string_option(self, name: str, max_length: int) -> str:
		"""Extract one required bounded string with its expected Discord type."""
		option = self.options.get(name)
		if not option or option.get("type") != STRING_OPTION_TYPE:
			raise CommandError("Malformed string option")
		value = option.get("value")
		if not isinstance(value, str) or len(value) > max_length:
			raise CommandError("Malformed string option")
		return value

	def optional_string(self, name: str, max_length: int) -> str | None:
		"""Extract one optional bounded string with its expected Discord type."""
		option = self.options.get(name)
		if option is None:
			return None
		value = option.get("value")
		if option.get("type") != STRING_OPTION_TYPE or not isinstance(value, str):
			raise CommandError("Malformed string option")
		if not value or len(value) > max_length:
			raise CommandError("Malformed string option")
		return value

	def optional_integer(
		self,
		name: str,
		default: int,
		minimum: int,
		maximum: int,
	) -> int:
		"""Extract one optional bounded integer while rejecting unrelated options."""
		if name not in self.options:
			self.require_option_set((), (name,))
			return default
		self.require_option_set((), (name,))
		option = self.options[name]
		value = option.get("value")
		if option.get("type") != INTEGER_OPTION_TYPE or type(value) is not int:
			raise CommandError("Malformed integer option")
		if not minimum <= value <= maximum:
			raise CommandError("Integer option is outside its allowed range")
		return value

	def optional_boolean(self, name: str, default: bool) -> bool:
		"""Extract one optional Discord boolean without accepting truthy substitutes."""
		option = self.options.get(name)
		if option is None:
			return default
		value = option.get("value")
		if option.get("type") != BOOLEAN_OPTION_TYPE or type(value) is not bool:
			raise CommandError("Malformed boolean option")
		return value


class CommandDefinition(ABC):
	"""Define the metadata and asynchronous hook owned by one Discord command."""

	name: ClassVar[str]
	description: ClassVar[str]
	options: ClassVar[tuple[CommandOption, ...]] = ()
	command_type: ClassVar[int] = CHAT_INPUT_COMMAND_TYPE
	order: ClassVar[int] = 100
	ephemeral: ClassVar[bool] = True
	deferred: ClassVar[bool] = False
	mod_only: ClassVar[bool] = False

	def registration_options(self) -> tuple[CommandOption, ...]:
		"""Return command-specific options followed by universal response visibility."""
		return self.options + (PUBLIC_RESPONSE_OPTION,)

	def to_definition(self) -> dict[str, Any]:
		"""Construct this command's complete Discord registration definition."""
		return {
			"name": self.name,
			"type": self.command_type,
			"description": self.description,
			"options": [option.to_definition() for option in self.registration_options()],
		}

	def signature(self) -> str:
		"""Construct the command syntax displayed by the help command."""
		arguments = [
			f"<{option.name}>" if option.required else f"[{option.name}]"
			for option in self.registration_options()
		]
		argument_text = f" {' '.join(arguments)}" if arguments else ""
		return f"/{self.name}{argument_text}"

	def response_is_ephemeral(self, context: CommandContext) -> bool:
		"""Apply the universal public override after validating declared option names."""
		required = tuple(option.name for option in self.options if option.required)
		optional = tuple(option.name for option in self.options if not option.required)
		context.require_option_set(required, optional)
		public = context.optional_boolean(PUBLIC_OPTION_NAME, False)
		return self.ephemeral and not public

	@abstractmethod
	async def invoke(self, context: CommandContext) -> str:
		"""Execute one authorized invocation and return mention-safe response text."""
