"""Minimal bounded Discord REST access required by approved development commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import json
from pathlib import Path
import secrets
from typing import Any, Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import zipfile

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
HISTORY_TIMEOUT_SECONDS = 2.0
MAX_HISTORY_RESPONSE_BYTES = 512 * 1024
MAX_HISTORY_REQUEST_COUNT = 100
WEBHOOK_TIMEOUT_SECONDS = 5.0
MAX_WEBHOOK_RESPONSE_BYTES = 64 * 1024
GENERAL_REST_TIMEOUT_SECONDS = 5.0
MAX_GENERAL_RESPONSE_BYTES = 64 * 1024
ATTACHMENT_TIMEOUT_SECONDS = 10.0
MAX_ATTACHMENT_COUNT = 3
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 20 * 1024 * 1024
INBOUND_ATTACHMENT_SUFFIXES = frozenset(
	{".txt", ".md", ".json", ".csv", ".log", ".pdf", ".jpg", ".jpeg", ".png"}
)
OUTBOUND_ATTACHMENT_SUFFIXES = INBOUND_ATTACHMENT_SUFFIXES | frozenset({".zip"})
ALLOWED_ATTACHMENT_HOSTS = frozenset({"cdn.discordapp.com", "media.discordapp.net"})


class DiscordRestError(RuntimeError):
	"""Represent a redacted Discord REST failure suitable for safe command handling."""


@dataclass(frozen=True, slots=True)
class RecentMessage:
	"""Hold only the recent-message fields needed by bounded history consumers."""

	author_name: str
	content: str
	timestamp: str


@dataclass(frozen=True, slots=True)
class CreatedThread:
	"""Describe the Discord thread fields needed to create a durable binding."""

	thread_id: str
	parent_channel_id: str


@dataclass(frozen=True, slots=True)
class DiscordUpload:
	"""Hold one validated in-memory file for a Discord multipart message."""

	filename: str
	content_type: str
	content: bytes


@dataclass(frozen=True, slots=True)
class DiscordRestClient:
	"""Perform narrowly scoped Discord REST reads with bounded time and response size."""

	bot_token: str = field(repr=False)
	opener: Callable[..., Any] = field(default=urlopen, repr=False)

	def get_recent_messages(self, channel_id: str, limit: int) -> list[RecentMessage]:
		"""Read newest-first messages from one already-authorized channel or thread."""
		if not channel_id.isdecimal():
			raise DiscordRestError("The channel identifier is invalid.")
		if not 1 <= limit <= MAX_HISTORY_REQUEST_COUNT:
			raise DiscordRestError("The history limit is outside the supported range.")

		request = Request(
			f"{DISCORD_API_BASE_URL}/channels/{channel_id}/messages?limit={limit}",
			headers={
				"Authorization": f"Bot {self.bot_token}",
				"User-Agent": "DiscordBot (https://agents.example.com, 1.0)",
			},
			method="GET",
		)
		try:
			with self.opener(request, timeout=HISTORY_TIMEOUT_SECONDS) as response:
				status_code = response.status
				response_body = response.read(MAX_HISTORY_RESPONSE_BYTES + 1)
		except HTTPError as error:
			error.read(64 * 1024)
			if error.code == 429:
				raise DiscordRestError("Discord rate-limited the history request.") from None
			raise DiscordRestError(
				f"Discord rejected the history request with HTTP status {error.code}."
			) from None
		except URLError as error:
			raise DiscordRestError("Could not connect to Discord for message history.") from error

		if status_code != 200:
			raise DiscordRestError(
				f"Discord returned unexpected HTTP status {status_code} for message history."
			)
		if len(response_body) > MAX_HISTORY_RESPONSE_BYTES:
			raise DiscordRestError("Discord returned an oversized message-history response.")

		try:
			values = json.loads(response_body)
		except (json.JSONDecodeError, UnicodeDecodeError) as error:
			raise DiscordRestError("Discord returned invalid message-history JSON.") from error
		if not isinstance(values, list):
			raise DiscordRestError("Discord returned an invalid message-history document.")

		return [_parse_message(value) for value in values[:limit]]

	def create_public_thread(self, channel_id: str, name: str) -> CreatedThread:
		"""Create one public thread below an already-authorized guild channel."""
		if not channel_id.isdecimal() or len(channel_id) > 32:
			raise DiscordRestError("The channel identifier is invalid.")
		if not isinstance(name, str) or not 1 <= len(name) <= 100:
			raise DiscordRestError("The thread name is invalid.")
		value = self._request_json(
			f"/channels/{channel_id}/threads",
			"POST",
			{
				"name": name,
				"auto_archive_duration": 10_080,
				"type": 11,
			},
		)
		thread_id = value.get("id") if isinstance(value, dict) else None
		parent_channel_id = value.get("parent_id") if isinstance(value, dict) else None
		if (
			not isinstance(thread_id, str)
			or not thread_id.isdecimal()
			or not isinstance(parent_channel_id, str)
			or parent_channel_id != channel_id
		):
			raise DiscordRestError("Discord returned an invalid thread document.")
		return CreatedThread(thread_id, parent_channel_id)

	def create_message(
		self,
		channel_id: str,
		content: str,
		nonce: str | None = None,
		attachments: Sequence[DiscordUpload] = (),
	) -> str:
		"""Post one mention-safe message, optionally using Discord nonce deduplication."""
		if not channel_id.isdecimal() or len(channel_id) > 32:
			raise DiscordRestError("The channel identifier is invalid.")
		if not isinstance(content, str) or not 1 <= len(content) <= 2_000:
			raise DiscordRestError("The message content is invalid.")
		payload: dict[str, Any] = {
			"content": content,
			"allowed_mentions": {
				"parse": [],
				"roles": [],
				"users": [],
				"replied_user": False,
			},
		}
		if nonce is not None:
			if not nonce.isdecimal() or len(nonce) > 25:
				raise DiscordRestError("The message nonce is invalid.")
			payload["nonce"] = nonce
			payload["enforce_nonce"] = True
		validated_attachments = self._validate_uploads(attachments)
		if validated_attachments:
			payload["attachments"] = [
				{"id": index, "filename": upload.filename}
				for index, upload in enumerate(validated_attachments)
			]
			value = self._request_multipart_json(
				f"/channels/{channel_id}/messages",
				payload,
				validated_attachments,
			)
		else:
			value = self._request_json(
				f"/channels/{channel_id}/messages",
				"POST",
				payload,
			)
		message_id = value.get("id") if isinstance(value, dict) else None
		if not isinstance(message_id, str) or not message_id.isdecimal():
			raise DiscordRestError("Discord returned an invalid message document.")
		return message_id

	def download_attachment(self, url: str, expected_size: int) -> bytes:
		"""Download one signed Discord attachment with strict origin and byte bounds."""
		parts = urlsplit(url)
		if (
			parts.scheme != "https"
			or parts.hostname not in ALLOWED_ATTACHMENT_HOSTS
			or parts.username is not None
			or parts.password is not None
			or parts.port not in {None, 443}
		):
			raise DiscordRestError("The attachment URL is not an approved Discord CDN URL.")
		if type(expected_size) is not int or not 0 <= expected_size <= MAX_ATTACHMENT_BYTES:
			raise DiscordRestError("The attachment size is invalid.")
		request = Request(
			url,
			headers={"User-Agent": "DiscordBot (https://agents.example.com, 1.0)"},
			method="GET",
		)
		try:
			with self.opener(request, timeout=ATTACHMENT_TIMEOUT_SECONDS) as response:
				status_code = response.status
				content = response.read(MAX_ATTACHMENT_BYTES + 1)
		except HTTPError as error:
			error.read(4_096)
			raise DiscordRestError("Discord rejected the attachment download.") from None
		except URLError as error:
			raise DiscordRestError("Could not download the Discord attachment.") from error
		if status_code != 200 or len(content) > MAX_ATTACHMENT_BYTES:
			raise DiscordRestError("Discord returned an invalid attachment response.")
		if len(content) != expected_size:
			raise DiscordRestError("The Discord attachment size did not match its metadata.")
		return content

	@staticmethod
	def _validate_uploads(attachments: Sequence[DiscordUpload]) -> tuple[DiscordUpload, ...]:
		"""Validate message files before building a multipart Discord request."""
		values = tuple(attachments)
		if len(values) > MAX_ATTACHMENT_COUNT:
			raise DiscordRestError("Too many message attachments were supplied.")
		total_size = 0
		for upload in values:
			if (
				not isinstance(upload, DiscordUpload)
				or Path(upload.filename).name != upload.filename
				or not 1 <= len(upload.filename) <= 128
				or not upload.filename.isascii()
				or any(
					character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._ -"
					for character in upload.filename
				)
				or Path(upload.filename).suffix.lower() not in OUTBOUND_ATTACHMENT_SUFFIXES
				or not 1 <= len(upload.content_type) <= 100
				or not upload.content_type.isascii()
				or any(character in upload.content_type for character in "\r\n")
				or not isinstance(upload.content, bytes)
				or len(upload.content) > MAX_ATTACHMENT_BYTES
			):
				raise DiscordRestError("A message attachment is invalid.")
			_validate_upload_content(upload)
			total_size += len(upload.content)
		if total_size > MAX_TOTAL_ATTACHMENT_BYTES:
			raise DiscordRestError("Combined message attachments are too large.")
		return values

	def _request_multipart_json(
		self,
		path: str,
		payload: dict[str, Any],
		attachments: Sequence[DiscordUpload],
	) -> Any:
		"""Post one bounded Discord multipart request and decode its JSON response."""
		boundary = f"discord-agent-{secrets.token_hex(16)}"
		body_parts = [
			f"--{boundary}\r\n".encode("ascii"),
			b'Content-Disposition: form-data; name="payload_json"\r\n',
			b"Content-Type: application/json\r\n\r\n",
			json.dumps(payload, separators=(",", ":")).encode("utf-8"),
			b"\r\n",
		]
		for index, upload in enumerate(attachments):
			body_parts.extend(
				[
					f"--{boundary}\r\n".encode("ascii"),
					(
						f'Content-Disposition: form-data; name="files[{index}]"; '
						f'filename="{upload.filename}"\r\n'
					).encode("ascii"),
					f"Content-Type: {upload.content_type}\r\n\r\n".encode("ascii"),
					upload.content,
					b"\r\n",
				]
			)
		body_parts.append(f"--{boundary}--\r\n".encode("ascii"))
		request = Request(
			f"{DISCORD_API_BASE_URL}{path}",
			data=b"".join(body_parts),
			headers={
				"Authorization": f"Bot {self.bot_token}",
				"User-Agent": "DiscordBot (https://agents.example.com, 1.0)",
				"Content-Type": f"multipart/form-data; boundary={boundary}",
			},
			method="POST",
		)
		try:
			with self.opener(request, timeout=GENERAL_REST_TIMEOUT_SECONDS) as response:
				status_code = response.status
				response_body = response.read(MAX_GENERAL_RESPONSE_BYTES + 1)
		except HTTPError as error:
			error.read(MAX_GENERAL_RESPONSE_BYTES)
			if error.code == 429:
				raise DiscordRestError("Discord rate-limited the request.") from None
			raise DiscordRestError(
				f"Discord rejected the request with HTTP status {error.code}."
			) from None
		except URLError as error:
			raise DiscordRestError("Could not connect to Discord.") from error
		if status_code not in {200, 201} or len(response_body) > MAX_GENERAL_RESPONSE_BYTES:
			raise DiscordRestError("Discord returned an invalid message response.")
		try:
			return json.loads(response_body)
		except (json.JSONDecodeError, UnicodeDecodeError) as error:
			raise DiscordRestError("Discord returned invalid JSON.") from error
	def get_gateway_url(self) -> str:
		"""Retrieve Discord's current bot Gateway base URL."""
		value = self._request_json("/gateway/bot", "GET")
		gateway_url = value.get("url") if isinstance(value, dict) else None
		if not isinstance(gateway_url, str) or not gateway_url.startswith("wss://"):
			raise DiscordRestError("Discord returned an invalid Gateway document.")
		return gateway_url

	def _request_json(
		self,
		path: str,
		method: str,
		payload: dict[str, Any] | None = None,
	) -> Any:
		"""Perform one bounded authenticated Discord request and decode its JSON."""
		request_body = None
		headers = {
			"Authorization": f"Bot {self.bot_token}",
			"User-Agent": "DiscordBot (https://agents.example.com, 1.0)",
		}
		if payload is not None:
			request_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
			headers["Content-Type"] = "application/json"
		request = Request(
			f"{DISCORD_API_BASE_URL}{path}",
			data=request_body,
			headers=headers,
			method=method,
		)
		try:
			with self.opener(request, timeout=GENERAL_REST_TIMEOUT_SECONDS) as response:
				status_code = response.status
				response_body = response.read(MAX_GENERAL_RESPONSE_BYTES + 1)
		except HTTPError as error:
			error.read(MAX_GENERAL_RESPONSE_BYTES)
			if error.code == 429:
				raise DiscordRestError("Discord rate-limited the request.") from None
			raise DiscordRestError(
				f"Discord rejected the request with HTTP status {error.code}."
			) from None
		except URLError as error:
			raise DiscordRestError("Could not connect to Discord.") from error
		if status_code not in {200, 201}:
			raise DiscordRestError(
				f"Discord returned unexpected HTTP status {status_code}."
			)
		if len(response_body) > MAX_GENERAL_RESPONSE_BYTES:
			raise DiscordRestError("Discord returned an oversized response.")
		try:
			return json.loads(response_body)
		except (json.JSONDecodeError, UnicodeDecodeError) as error:
			raise DiscordRestError("Discord returned invalid JSON.") from error


def _validate_upload_content(upload: DiscordUpload) -> None:
	"""Reject mislabeled or corrupt outbound files before sending them to Discord."""
	suffix = Path(upload.filename).suffix.lower()
	content = upload.content
	if suffix == ".zip":
		if not zipfile.is_zipfile(BytesIO(content)):
			raise DiscordRestError("The ZIP upload is invalid.")
		return
	if suffix == ".pdf" and not content.startswith(b"%PDF-"):
		raise DiscordRestError("The PDF upload signature is invalid.")
	if suffix == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
		raise DiscordRestError("The PNG upload signature is invalid.")
	if suffix in {".jpg", ".jpeg"} and not (
		content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")
	):
		raise DiscordRestError("The JPEG upload signature is invalid.")
	if suffix in {".txt", ".md", ".json", ".csv", ".log"}:
		try:
			content.decode("utf-8-sig")
		except UnicodeDecodeError as error:
			raise DiscordRestError("The text upload is not valid UTF-8.") from error


@dataclass(frozen=True, slots=True)
class InteractionWebhookClient:
	"""Edit deferred interaction responses without requiring a Discord bot token."""

	opener: Callable[..., Any] = field(default=urlopen, repr=False)

	def edit_original_response(
		self,
		application_id: str,
		interaction_token: str,
		content: str,
	) -> None:
		"""Replace the loading response through Discord's short-lived interaction webhook."""
		if not application_id.isdecimal() or len(application_id) > 32:
			raise DiscordRestError("The application identifier is invalid.")
		if not interaction_token or len(interaction_token) > 512:
			raise DiscordRestError("The interaction token is invalid.")
		if not isinstance(content, str) or len(content) > 2_000:
			raise DiscordRestError("The deferred response content is invalid.")
		payload = json.dumps(
			{
				"content": content,
				"allowed_mentions": {
					"parse": [],
					"roles": [],
					"users": [],
					"replied_user": False,
				},
			},
			separators=(",", ":"),
		).encode("utf-8")
		request = Request(
			(
				f"{DISCORD_API_BASE_URL}/webhooks/{application_id}/"
				f"{quote(interaction_token, safe='')}/messages/@original"
			),
			data=payload,
			headers={
				"Content-Type": "application/json",
				"User-Agent": "DiscordBot (https://agents.example.com, 1.0)",
			},
			method="PATCH",
		)
		try:
			with self.opener(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:
				status_code = response.status
				response_body = response.read(MAX_WEBHOOK_RESPONSE_BYTES + 1)
		except HTTPError as error:
			error.read(MAX_WEBHOOK_RESPONSE_BYTES)
			raise DiscordRestError(
				f"Discord rejected the deferred response with HTTP status {error.code}."
			) from None
		except URLError as error:
			raise DiscordRestError("Could not connect to Discord for the deferred response.") from error

		if status_code != 200:
			raise DiscordRestError(
				f"Discord returned unexpected HTTP status {status_code} for the deferred response."
			)
		if len(response_body) > MAX_WEBHOOK_RESPONSE_BYTES:
			raise DiscordRestError("Discord returned an oversized deferred-response document.")


def _parse_message(value: object) -> RecentMessage:
	"""Extract bounded display fields without retaining the complete Discord message."""
	if not isinstance(value, dict):
		raise DiscordRestError("Discord returned an invalid message object.")
	author = value.get("author")
	if not isinstance(author, dict):
		raise DiscordRestError("Discord returned a message without a valid author.")

	author_name = author.get("global_name") or author.get("username") or "unknown"
	content = value.get("content", "")
	timestamp = value.get("timestamp", "")
	if not isinstance(author_name, str) or not isinstance(content, str) or not isinstance(timestamp, str):
		raise DiscordRestError("Discord returned invalid message display fields.")
	return RecentMessage(
		author_name=author_name[:100],
		content=content,
		timestamp=timestamp[:40],
	)
