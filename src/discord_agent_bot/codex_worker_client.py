"""Bounded JSON WebSocket client for the private Codex worker module."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from math import isfinite
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from discord_agent_bot.commands.base import AgentStatus, AgentStatusError, RecentAgentCommand

MAX_WORKER_MESSAGE_BYTES = 128 * 1024
MAX_ATTACHMENT_COUNT = 3
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ARTIFACT_RESPONSE_BYTES = MAX_ATTACHMENT_BYTES + 1
MAX_AGENT_TAG_COUNT = 1_024
AGENT_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULT_AGENT_TAG = "dev1"
SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
INBOUND_ATTACHMENT_SUFFIXES = frozenset(
	{".txt", ".md", ".json", ".csv", ".log", ".pdf", ".jpg", ".jpeg", ".png"}
)
OUTBOUND_ATTACHMENT_SUFFIXES = INBOUND_ATTACHMENT_SUFFIXES | frozenset({".zip"})


def _validate_artifact_route(agent_tag: str, request_id: str) -> None:
	"""Reject identifiers before using them in private artifact request URLs."""
	if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
		raise CodexWorkerError("The requested agent tag is invalid.")
	if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
		raise CodexWorkerError("The worker request identifier is invalid.")


def _validate_filename(filename: str, allowed_suffixes: frozenset[str]) -> None:
	"""Accept only conservative filenames supported for the transfer direction."""
	if (
		not SAFE_FILENAME_PATTERN.fullmatch(filename)
		or not any(filename.lower().endswith(suffix) for suffix in allowed_suffixes)
	):
		raise CodexWorkerError("The attachment filename or type is unsupported.")


class CodexWorkerError(AgentStatusError):
	"""Represent a redacted worker transport or protocol failure."""


@dataclass(frozen=True, slots=True)
class WorkerAttachment:
	"""Describe one digest-pinned file produced by a tagged worker agent."""

	filename: str
	content_type: str
	size: int
	sha256: str


@dataclass(frozen=True, slots=True)
class WorkerResponse:
	"""Return one worker answer together with optional thread attachments."""

	answer: str
	attachments: tuple[WorkerAttachment, ...] = ()
	attachment_warning: str | None = None


@dataclass(frozen=True, slots=True)
class CodexWorkerClient:
	"""Submit one prompt and wait for its delayed response on the same WebSocket."""

	url: str
	response_timeout_seconds: float = 840.0
	open_timeout_seconds: float = 5.0
	status_timeout_seconds: float = 10.0

	async def ask(
		self,
		prompt: str,
		metadata: Mapping[str, str],
		agent_tag: str | None = None,
		request_id: str | None = None,
	) -> str:
		"""Send a JSON prompt envelope and validate the matching terminal response."""
		response = await self.ask_with_artifacts(
			prompt,
			metadata,
			agent_tag,
			request_id,
		)
		return response.answer

	async def ask_with_artifacts(
		self,
		prompt: str,
		metadata: Mapping[str, str],
		agent_tag: str | None = None,
		request_id: str | None = None,
	) -> WorkerResponse:
		"""Wait for a worker answer and its validated outbound artifact manifest."""
		resolved_agent_tag = DEFAULT_AGENT_TAG if agent_tag is None else agent_tag
		if not AGENT_TAG_PATTERN.fullmatch(resolved_agent_tag):
			raise CodexWorkerError("The requested agent tag is invalid.")
		resolved_request_id = uuid4().hex if request_id is None else request_id
		if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", resolved_request_id):
			raise CodexWorkerError("The worker request identifier is invalid.")
		request_document = json.dumps(
			{
				"type": "prompt",
				"request_id": resolved_request_id,
				"agent_tag": resolved_agent_tag,
				"prompt": prompt,
				"metadata": dict(metadata),
			},
			ensure_ascii=False,
			separators=(",", ":"),
		)
		try:
			async with asyncio.timeout(self.response_timeout_seconds):
				async with connect(
					self.url,
					open_timeout=self.open_timeout_seconds,
					close_timeout=2,
					ping_interval=20,
					ping_timeout=20,
					max_size=MAX_WORKER_MESSAGE_BYTES,
				) as websocket:
					await websocket.send(request_document)
					while True:
						raw_response = await websocket.recv()
						response = self._parse_worker_response(
							raw_response,
							resolved_request_id,
							resolved_agent_tag,
						)
						if response is not None:
							return response
		except TimeoutError as error:
			raise CodexWorkerError("The Codex worker response timed out.") from error
		except (ConnectionClosed, OSError, WebSocketException) as error:
			raise CodexWorkerError("The Codex worker is unavailable.") from error

	async def stage_attachment(
		self,
		agent_tag: str,
		request_id: str,
		attachment_id: str,
		filename: str,
		content: bytes,
	) -> str:
		"""Transfer one validated Discord file into the selected worker workspace."""
		_validate_artifact_route(agent_tag, request_id)
		_validate_filename(filename, INBOUND_ATTACHMENT_SUFFIXES)
		if not attachment_id.isdecimal() or len(attachment_id) > 32:
			raise CodexWorkerError("The attachment identifier is invalid.")
		if len(content) > MAX_ATTACHMENT_BYTES:
			raise CodexWorkerError("The attachment is too large.")
		query = urlencode(
			{
				"agent_tag": agent_tag,
				"request_id": request_id,
				"attachment_id": attachment_id,
				"filename": filename,
			}
		)
		request = Request(
			f"{self._artifact_http_base()}/artifacts/inbound?{query}",
			data=content,
			headers={"Content-Type": "application/octet-stream"},
			method="POST",
		)
		response_body = await asyncio.to_thread(
			self._bounded_artifact_request,
			request,
			4_096,
		)
		try:
			document: Any = json.loads(response_body)
		except (json.JSONDecodeError, UnicodeDecodeError) as error:
			raise CodexWorkerError("The Codex worker returned invalid attachment JSON.") from error
		relative_path = document.get("relative_path") if isinstance(document, dict) else None
		if (
			not isinstance(relative_path, str)
			or not relative_path.startswith(f"tmp/download/{request_id}/")
			or len(relative_path) > 256
		):
			raise CodexWorkerError("The Codex worker returned an invalid attachment path.")
		return relative_path

	async def download_artifact(
		self,
		agent_tag: str,
		request_id: str,
		artifact: WorkerAttachment,
	) -> bytes:
		"""Retrieve one worker output and verify its advertised size and digest."""
		_validate_artifact_route(agent_tag, request_id)
		_validate_filename(artifact.filename, OUTBOUND_ATTACHMENT_SUFFIXES)
		query = urlencode(
			{
				"agent_tag": agent_tag,
				"request_id": request_id,
				"filename": artifact.filename,
				"sha256": artifact.sha256,
			}
		)
		request = Request(
			f"{self._artifact_http_base()}/artifacts/outbound?{query}",
			method="GET",
		)
		content = await asyncio.to_thread(
			self._bounded_artifact_request,
			request,
			MAX_ARTIFACT_RESPONSE_BYTES,
		)
		if (
			len(content) != artifact.size
			or hashlib.sha256(content).hexdigest() != artifact.sha256
		):
			raise CodexWorkerError("The worker attachment changed during transfer.")
		return content

	def _artifact_http_base(self) -> str:
		"""Derive the private HTTP origin paired with the configured WebSocket URL."""
		parts = urlsplit(self.url)
		if parts.scheme not in {"ws", "wss"} or not parts.netloc or parts.query or parts.fragment:
			raise CodexWorkerError("The Codex worker URL is invalid.")
		scheme = "https" if parts.scheme == "wss" else "http"
		path = parts.path[:-3] if parts.path.endswith("/ws") else parts.path.rstrip("/")
		return urlunsplit((scheme, parts.netloc, path, "", "")).rstrip("/")

	@staticmethod
	def _bounded_artifact_request(request: Request, maximum_bytes: int) -> bytes:
		"""Execute one private worker file request with bounded response handling."""
		try:
			with urlopen(request, timeout=10.0) as response:
				status_code = response.status
				content = response.read(maximum_bytes + 1)
		except HTTPError as error:
			error.read(4_096)
			raise CodexWorkerError("The Codex worker rejected an attachment.") from None
		except URLError as error:
			raise CodexWorkerError("The Codex worker attachment service is unavailable.") from error
		if status_code not in {200, 201} or len(content) > maximum_bytes:
			raise CodexWorkerError("The Codex worker returned an invalid attachment response.")
		return content

	async def status(self, agent_tag: str) -> AgentStatus:
		"""Request validated counters for one tag without submitting a prompt."""
		if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise CodexWorkerError("The requested agent tag is invalid.")
		request_id = uuid4().hex
		request_document = json.dumps(
			{
				"type": "status",
				"request_id": request_id,
				"agent_tag": agent_tag,
			},
			separators=(",", ":"),
		)
		try:
			async with asyncio.timeout(self.status_timeout_seconds):
				async with connect(
					self.url,
					open_timeout=self.open_timeout_seconds,
					close_timeout=2,
					ping_interval=20,
					ping_timeout=20,
					max_size=MAX_WORKER_MESSAGE_BYTES,
				) as websocket:
					await websocket.send(request_document)
					return self._parse_status_response(await websocket.recv(), request_id)
		except TimeoutError as error:
			raise CodexWorkerError("The Codex worker status timed out.") from error
		except (ConnectionClosed, OSError, WebSocketException) as error:
			raise CodexWorkerError("The Codex worker is unavailable.") from error

	async def list_agents(self) -> tuple[str, ...]:
		"""Request the configured and durable created tags without invoking Codex."""
		request_id = uuid4().hex
		request_document = json.dumps(
			{"type": "agent_list", "request_id": request_id},
			separators=(",", ":"),
		)
		try:
			async with asyncio.timeout(self.status_timeout_seconds):
				async with connect(
					self.url,
					open_timeout=self.open_timeout_seconds,
					close_timeout=2,
					ping_interval=20,
					ping_timeout=20,
					max_size=MAX_WORKER_MESSAGE_BYTES,
				) as websocket:
					await websocket.send(request_document)
					return self._parse_agent_list_response(
						await websocket.recv(),
						request_id,
					)
		except TimeoutError as error:
			raise CodexWorkerError("The Codex worker agent list timed out.") from error
		except (ConnectionClosed, OSError, WebSocketException) as error:
			raise CodexWorkerError("The Codex worker is unavailable.") from error

	async def configure(
		self,
		agent_tag: str,
		model: str,
		reasoning_level: str,
	) -> None:
		"""Set one agent's explicit model and reasoning profile."""
		await self._manage_agent(
			"config",
			agent_tag,
			model=model,
			reasoning_level=reasoning_level,
		)

	async def reset(self, agent_tag: str) -> None:
		"""Request complete template restoration for one agent workspace."""
		await self._manage_agent("reset", agent_tag)

	async def delete(self, agent_tag: str) -> None:
		"""Request complete removal of one tagged agent and workspace."""
		await self._manage_agent("delete", agent_tag)

	async def _manage_agent(
		self,
		operation: str,
		agent_tag: str,
		model: str | None = None,
		reasoning_level: str | None = None,
	) -> None:
		"""Send one validated lifecycle request over the private worker socket."""
		if operation not in {"config", "reset", "delete"}:
			raise CodexWorkerError("The worker management operation is invalid.")
		if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise CodexWorkerError("The requested agent tag is invalid.")
		request_id = uuid4().hex
		document: dict[str, str] = {
			"type": f"agent_{operation}",
			"request_id": request_id,
			"agent_tag": agent_tag,
		}
		if operation == "config":
			if (
				model not in {"gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra"}
				or reasoning_level not in {"low", "medium", "high"}
			):
				raise CodexWorkerError("The requested runtime profile is invalid.")
			document["model"] = model
			document["reasoning_level"] = reasoning_level
		try:
			async with asyncio.timeout(self.status_timeout_seconds):
				async with connect(
					self.url,
					open_timeout=self.open_timeout_seconds,
					close_timeout=2,
					ping_interval=20,
					ping_timeout=20,
					max_size=MAX_WORKER_MESSAGE_BYTES,
				) as websocket:
					await websocket.send(json.dumps(document, separators=(",", ":")))
					self._parse_management_response(
						await websocket.recv(),
						request_id,
						operation,
						agent_tag,
						model,
						reasoning_level,
					)
		except TimeoutError as error:
			raise CodexWorkerError("The Codex worker management request timed out.") from error
		except (ConnectionClosed, OSError, WebSocketException) as error:
			raise CodexWorkerError("The Codex worker is unavailable.") from error

	@staticmethod
	def _parse_management_response(
		raw_response: str | bytes,
		request_id: str,
		operation: str,
		agent_tag: str,
		model: str | None,
		reasoning_level: str | None,
	) -> None:
		"""Validate the exact acknowledgement for one lifecycle mutation."""
		if not isinstance(raw_response, str):
			raise CodexWorkerError("The Codex worker returned a binary management response.")
		try:
			response: Any = json.loads(raw_response)
		except json.JSONDecodeError as error:
			raise CodexWorkerError("The Codex worker returned invalid management JSON.") from error
		if isinstance(response, dict) and response.get("type") == "error":
			raise CodexWorkerError("The Codex worker rejected the management request.")
		expected: dict[str, object] = {
			"type": "agent_management",
			"request_id": request_id,
			"operation": operation,
			"agent_tag": agent_tag,
		}
		if operation == "config":
			expected.update({"model": model, "reasoning_level": reasoning_level})
		if response != expected:
			raise CodexWorkerError("The Codex worker returned an invalid management response.")

	@staticmethod
	def _parse_response(
		raw_response: str | bytes,
		request_id: str,
		agent_tag: str = DEFAULT_AGENT_TAG,
	) -> str | None:
		"""Validate one worker event and return only a matching completed answer."""
		response = CodexWorkerClient._parse_worker_response(
			raw_response,
			request_id,
			agent_tag,
		)
		return None if response is None else response.answer

	@staticmethod
	def _parse_worker_response(
		raw_response: str | bytes,
		request_id: str,
		agent_tag: str = DEFAULT_AGENT_TAG,
	) -> WorkerResponse | None:
		"""Validate one worker event including its optional artifact manifest."""
		if not isinstance(raw_response, str):
			raise CodexWorkerError("The Codex worker returned a binary response.")
		try:
			response: Any = json.loads(raw_response)
		except json.JSONDecodeError as error:
			raise CodexWorkerError("The Codex worker returned invalid JSON.") from error
		if not isinstance(response, dict):
			raise CodexWorkerError("The Codex worker returned an invalid document.")
		response_type = response.get("type")
		response_request_id = response.get("request_id")
		response_metadata = response.get("metadata")
		matches_agent = (
			isinstance(response_metadata, dict)
			and response_metadata.get("agent_tag") == agent_tag
		)
		if (
			response_type == "accepted"
			and response_request_id == request_id
			and matches_agent
		):
			return None
		if (
			response_type == "response"
			and response_request_id == request_id
			and matches_agent
		):
			answer = response.get("answer")
			if isinstance(answer, str) and answer:
				attachments = CodexWorkerClient._parse_attachments(response.get("attachments", []))
				warning = response.get("attachment_warning")
				if warning is not None and (
					not isinstance(warning, str) or not 1 <= len(warning) <= 200
				):
					raise CodexWorkerError("The Codex worker returned an invalid warning.")
				return WorkerResponse(answer, attachments, warning)
		if response_type == "error" and response_request_id in {None, request_id}:
			raise CodexWorkerError("The Codex worker could not complete the prompt.")
		raise CodexWorkerError("The Codex worker returned an unexpected response.")

	@staticmethod
	def _parse_attachments(value: object) -> tuple[WorkerAttachment, ...]:
		"""Validate the bounded output-file manifest without accepting paths or URLs."""
		if not isinstance(value, list) or len(value) > MAX_ATTACHMENT_COUNT:
			raise CodexWorkerError("The Codex worker returned invalid attachments.")
		attachments: list[WorkerAttachment] = []
		total_size = 0
		for item in value:
			if not isinstance(item, dict) or set(item) != {
				"filename",
				"content_type",
				"size",
				"sha256",
			}:
				raise CodexWorkerError("The Codex worker returned invalid attachment metadata.")
			filename = item["filename"]
			content_type = item["content_type"]
			size = item["size"]
			sha256 = item["sha256"]
			if not isinstance(filename, str):
				raise CodexWorkerError("The Codex worker returned an invalid filename.")
			_validate_filename(filename, OUTBOUND_ATTACHMENT_SUFFIXES)
			if (
				not isinstance(content_type, str)
				or not 1 <= len(content_type) <= 100
				or any(character in content_type for character in "\r\n")
				or type(size) is not int
				or not 0 <= size <= MAX_ATTACHMENT_BYTES
				or not isinstance(sha256, str)
				or not re.fullmatch(r"[0-9a-f]{64}", sha256)
			):
				raise CodexWorkerError("The Codex worker returned invalid attachment values.")
			total_size += size
			if total_size > MAX_TOTAL_ATTACHMENT_BYTES:
				raise CodexWorkerError("The Codex worker returned oversized attachments.")
			attachments.append(WorkerAttachment(filename, content_type, size, sha256))
		return tuple(attachments)

	@staticmethod
	def parse_artifact_manifest(value: str) -> tuple[WorkerAttachment, ...]:
		"""Decode a persisted worker artifact manifest for restart-safe delivery."""
		try:
			document: Any = json.loads(value)
		except json.JSONDecodeError as error:
			raise CodexWorkerError("The stored attachment manifest is invalid.") from error
		return CodexWorkerClient._parse_attachments(document)

	@staticmethod
	def _parse_status_response(raw_response: str | bytes, request_id: str) -> AgentStatus:
		"""Convert one matching worker status event into the typed command boundary."""
		if not isinstance(raw_response, str):
			raise CodexWorkerError("The Codex worker returned a binary status response.")
		try:
			response: Any = json.loads(raw_response)
		except json.JSONDecodeError as error:
			raise CodexWorkerError("The Codex worker returned invalid status JSON.") from error
		if (
			not isinstance(response, dict)
			or response.get("type") != "status"
			or response.get("request_id") != request_id
			or not isinstance(response.get("status"), dict)
		):
			raise CodexWorkerError("The Codex worker returned an invalid status document.")
		status = response["status"]
		agent_tag = status.get("agent_tag")
		state = status.get("state")
		model = CodexWorkerClient._optional_runtime_value(status.get("model"), 128)
		reasoning_level = CodexWorkerClient._optional_runtime_value(
			status.get("reasoning_level"),
			64,
		)
		runtime_profile_scope = status.get("runtime_profile_scope")
		time_zone = status.get("time_zone")
		if (
			not isinstance(agent_tag, str)
			or not agent_tag
			or len(agent_tag) > 64
			or any(
				character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
				for character in agent_tag
			)
			or state not in {"running", "idle"}
			or runtime_profile_scope not in {"current", "most_recent", "unavailable"}
			or (runtime_profile_scope == "unavailable" and model is not None)
			or (runtime_profile_scope != "unavailable" and model is None)
			or not isinstance(time_zone, str)
			or not 1 <= len(time_zone) <= 64
			or any(
				character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_+-"
				for character in time_zone
			)
		):
			raise CodexWorkerError("The Codex worker returned invalid status values.")
		recent_values = status.get("recent_commands")
		if not isinstance(recent_values, list) or len(recent_values) > 25:
			raise CodexWorkerError("The Codex worker returned invalid recent commands.")
		recent_commands = tuple(
			CodexWorkerClient._parse_recent_command(value) for value in recent_values
		)
		return AgentStatus(
			agent_tag=agent_tag,
			state=state,
			model=model,
			reasoning_level=reasoning_level,
			runtime_profile_scope=runtime_profile_scope,
			queued=CodexWorkerClient._nonnegative_int(status, "queued"),
			processing=CodexWorkerClient._nonnegative_int(status, "processing"),
			processed=CodexWorkerClient._nonnegative_int(status, "processed"),
			completed=CodexWorkerClient._nonnegative_int(status, "completed"),
			failed=CodexWorkerClient._nonnegative_int(status, "failed"),
			total_active_seconds=CodexWorkerClient._nonnegative_number(
				status, "total_active_seconds"
			),
			today_active_seconds=CodexWorkerClient._nonnegative_number(
				status, "today_active_seconds"
			),
			time_zone=time_zone[:64],
			recent_commands=recent_commands,
		)

	@staticmethod
	def _parse_agent_list_response(
		raw_response: str | bytes,
		request_id: str,
	) -> tuple[str, ...]:
		"""Validate one matching bounded, sorted worker agent-tag response."""
		if not isinstance(raw_response, str):
			raise CodexWorkerError("The Codex worker returned a binary agent list.")
		try:
			response: Any = json.loads(raw_response)
		except json.JSONDecodeError as error:
			raise CodexWorkerError("The Codex worker returned invalid agent-list JSON.") from error
		if (
			not isinstance(response, dict)
			or response.get("type") != "agent_list"
			or response.get("request_id") != request_id
			or set(response) != {"type", "request_id", "agent_tags"}
		):
			raise CodexWorkerError("The Codex worker returned an invalid agent list.")
		agent_tags = response["agent_tags"]
		if (
			not isinstance(agent_tags, list)
			or len(agent_tags) > MAX_AGENT_TAG_COUNT
			or not all(
				isinstance(agent_tag, str)
				and AGENT_TAG_PATTERN.fullmatch(agent_tag)
				for agent_tag in agent_tags
			)
			or agent_tags != sorted(set(agent_tags))
		):
			raise CodexWorkerError("The Codex worker returned invalid agent tags.")
		return tuple(agent_tags)

	@staticmethod
	def _parse_recent_command(value: object) -> RecentAgentCommand:
		"""Validate one content-free recent command record from the worker."""
		if not isinstance(value, dict):
			raise CodexWorkerError("The Codex worker returned an invalid command record.")
		received_at = value.get("received_at")
		command = value.get("command")
		status = value.get("status")
		if not all(isinstance(item, str) for item in (received_at, command, status)):
			raise CodexWorkerError("The Codex worker returned invalid command fields.")
		try:
			datetime.fromisoformat(received_at)
		except ValueError as error:
			raise CodexWorkerError("The Codex worker returned an invalid command time.") from error
		if (
			not command
			or len(command) > 32
			or any(
				character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
				for character in command
			)
			or status not in {"pending", "processing", "completed", "failed"}
		):
			raise CodexWorkerError("The Codex worker returned invalid command values.")
		user_id = CodexWorkerClient._optional_identifier(value.get("user_id"))
		channel_id = CodexWorkerClient._optional_identifier(value.get("channel_id"))
		return RecentAgentCommand(
			received_at=received_at[:40],
			command=command[:32],
			status=status[:16],
			user_id=user_id,
			channel_id=channel_id,
		)

	@staticmethod
	def _optional_identifier(value: object) -> str | None:
		"""Accept only absent or bounded numeric Discord identifiers."""
		if value is None:
			return None
		if not isinstance(value, str) or not value.isdecimal() or len(value) > 32:
			raise CodexWorkerError("The Codex worker returned an invalid identifier.")
		return value

	@staticmethod
	def _optional_runtime_value(value: object, maximum_length: int) -> str | None:
		"""Accept a bounded single-line Codex runtime identifier or an absent value."""
		if value is None:
			return None
		if (
			not isinstance(value, str)
			or not value
			or len(value) > maximum_length
			or any(
				character not in "abcdefghijklmnopqrstuvwxyz0123456789._-/"
				for character in value
			)
		):
			raise CodexWorkerError("The Codex worker returned an invalid runtime profile.")
		return value

	@staticmethod
	def _nonnegative_int(status: dict[str, Any], field_name: str) -> int:
		"""Read one nonnegative integer counter without accepting booleans."""
		value = status.get(field_name)
		if type(value) is not int or value < 0:
			raise CodexWorkerError("The Codex worker returned an invalid counter.")
		return value

	@staticmethod
	def _nonnegative_number(status: dict[str, Any], field_name: str) -> float:
		"""Read one finite nonnegative duration counter from worker JSON."""
		value = status.get(field_name)
		if type(value) not in {int, float} or not isfinite(value) or value < 0:
			raise CodexWorkerError("The Codex worker returned an invalid duration.")
		return float(value)
