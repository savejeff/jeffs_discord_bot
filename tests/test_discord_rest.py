"""Offline tests for scoped and bounded Discord message-history access."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from uuid import uuid4
import zipfile

import pytest

from discord_agent_bot.discord_rest import (
	DISCORD_API_BASE_URL,
	DiscordRestClient,
	DiscordRestError,
	DiscordUpload,
	InteractionWebhookClient,
	RecentMessage,
)

CHANNEL_ID = "100000000000000002"


class _FakeResponse:
	"""Provide a bounded successful urllib response for offline REST verification."""

	status = 200

	def __init__(self, body: bytes) -> None:
		self._body = body

	def __enter__(self) -> _FakeResponse:
		return self

	def __exit__(self, *_args: object) -> None:
		return None

	def read(self, limit: int) -> bytes:
		return self._body[:limit]


def test_history_read_targets_only_supplied_channel_with_bounded_limit() -> None:
	"""Verify authorization, URL scope, timeout, and minimal message extraction offline."""
	token = uuid4().hex
	captured: dict[str, Any] = {}
	body = json.dumps(
		[
			{
				"author": {"global_name": "Developer", "username": "developer"},
				"content": "newest",
				"timestamp": "2026-08-29T12:00:00Z",
			},
			{
				"author": {"global_name": None, "username": "operator"},
				"content": "older",
				"timestamp": "2026-08-29T11:59:00Z",
			},
		]
	).encode("utf-8")

	def fake_opener(request: Any, timeout: float) -> _FakeResponse:
		"""Capture the REST request and return local message JSON."""
		captured["request"] = request
		captured["timeout"] = timeout
		return _FakeResponse(body)

	client = DiscordRestClient(token, opener=fake_opener)
	messages = client.get_recent_messages(CHANNEL_ID, 2)
	request = captured["request"]

	assert messages == [
		RecentMessage("Developer", "newest", "2026-08-29T12:00:00Z"),
		RecentMessage("operator", "older", "2026-08-29T11:59:00Z"),
	]
	assert request.full_url == f"{DISCORD_API_BASE_URL}/channels/{CHANNEL_ID}/messages?limit=2"
	assert request.method == "GET"
	assert request.get_header("Authorization") == f"Bot {token}"
	assert captured["timeout"] == 2.0
	assert token not in repr(client)


@pytest.mark.parametrize("limit", [0, 101])
def test_history_limit_is_rejected_before_network_access(limit: int) -> None:
	"""Prevent requests outside Discord's one-to-one-hundred message bound."""
	def unexpected_opener(*_args: object, **_kwargs: object) -> None:
		"""Fail if invalid input reaches the network boundary."""
		raise AssertionError("network access should not occur")

	client = DiscordRestClient(uuid4().hex, opener=unexpected_opener)
	with pytest.raises(DiscordRestError, match="outside the supported range"):
		client.get_recent_messages(CHANNEL_ID, limit)


def test_deferred_response_edits_original_without_bot_authorization() -> None:
	"""Use the interaction webhook token only and keep mentions disabled in completion text."""
	interaction_token = uuid4().hex
	captured: dict[str, Any] = {}

	def fake_opener(request: Any, timeout: float) -> _FakeResponse:
		"""Capture the deferred response request without contacting Discord."""
		captured["request"] = request
		captured["timeout"] = timeout
		return _FakeResponse(b"{}")

	client = InteractionWebhookClient(opener=fake_opener)
	client.edit_original_response("100000000000000006", interaction_token, "done @everyone")
	request = captured["request"]
	payload = json.loads(request.data)

	assert request.full_url == (
		f"{DISCORD_API_BASE_URL}/webhooks/100000000000000006/"
		f"{interaction_token}/messages/@original"
	)
	assert request.method == "PATCH"
	assert request.get_header("Authorization") is None
	assert captured["timeout"] == 5.0
	assert payload["content"] == "done @everyone"
	assert payload["allowed_mentions"]["parse"] == []


def test_thread_creation_and_message_delivery_are_bounded_and_mention_safe() -> None:
	"""Verify the public-thread and nonce-deduplicated message REST contracts offline."""
	captured: list[tuple[Any, float]] = []
	responses = [
		json.dumps({"id": "100000000000000010", "parent_id": CHANNEL_ID}).encode(),
		json.dumps({"id": "100000000000000011"}).encode(),
		json.dumps({"url": "wss://gateway.discord.gg"}).encode(),
	]

	def fake_opener(request: Any, timeout: float) -> _FakeResponse:
		"""Capture sequential bot REST calls and return matching local documents."""
		captured.append((request, timeout))
		return _FakeResponse(responses[len(captured) - 1])

	client = DiscordRestClient(uuid4().hex, opener=fake_opener)
	thread = client.create_public_thread(CHANNEL_ID, "agent-project_alpha")
	message_id = client.create_message(
		thread.thread_id,
		"answer @everyone",
		"100000000000000020",
	)
	gateway_url = client.get_gateway_url()

	thread_payload = json.loads(captured[0][0].data)
	message_payload = json.loads(captured[1][0].data)
	assert thread.thread_id == "100000000000000010"
	assert thread.parent_channel_id == CHANNEL_ID
	assert thread_payload == {
		"name": "agent-project_alpha",
		"auto_archive_duration": 10_080,
		"type": 11,
	}
	assert message_id == "100000000000000011"
	assert message_payload["content"] == "answer @everyone"
	assert message_payload["allowed_mentions"]["parse"] == []
	assert message_payload["nonce"] == "100000000000000020"
	assert message_payload["enforce_nonce"] is True
	assert gateway_url == "wss://gateway.discord.gg"
	assert all(timeout == 5.0 for _request, timeout in captured)


def test_attachment_download_and_multipart_message_are_bounded() -> None:
	"""Fetch only Discord CDN bytes and post them as a mention-safe multipart file."""
	captured: list[tuple[Any, float]] = []
	attachment_content = b"report body"
	responses = [
		attachment_content,
		json.dumps({"id": "100000000000000011"}).encode(),
	]

	def fake_opener(request: Any, timeout: float) -> _FakeResponse:
		"""Capture the CDN download and subsequent Discord message upload."""
		captured.append((request, timeout))
		return _FakeResponse(responses[len(captured) - 1])

	client = DiscordRestClient(uuid4().hex, opener=fake_opener)
	downloaded = client.download_attachment(
		"https://cdn.discordapp.com/attachments/100/200/report.md?ex=abc",
		len(attachment_content),
	)
	message_id = client.create_message(
		CHANNEL_ID,
		"attached @everyone",
		"100000000000000020",
		(DiscordUpload("report.md", "text/markdown", downloaded),),
	)

	upload_request = captured[1][0]
	content_type = upload_request.get_header("Content-type")
	assert message_id == "100000000000000011"
	assert captured[0][0].get_header("Authorization") is None
	assert content_type.startswith("multipart/form-data; boundary=discord-agent-")
	assert b'name="payload_json"' in upload_request.data
	assert b'name="files[0]"; filename="report.md"' in upload_request.data
	assert b'"allowed_mentions":{"parse":[]' in upload_request.data
	assert attachment_content in upload_request.data


def test_attachment_download_rejects_non_discord_origin() -> None:
	"""Prevent a crafted Gateway payload from turning the observer into an SSRF client."""
	client = DiscordRestClient(uuid4().hex, opener=lambda *_args, **_kwargs: None)

	with pytest.raises(DiscordRestError, match="approved Discord CDN"):
		client.download_attachment("https://example.com/private.txt", 1)


def test_message_upload_allows_valid_generated_zip() -> None:
	"""Permit a worker-generated ZIP as output without making it an inbound format."""
	captured: dict[str, Any] = {}
	zip_buffer = BytesIO()
	with zipfile.ZipFile(zip_buffer, "w") as archive:
		archive.writestr("result.txt", "result")

	def fake_opener(request: Any, timeout: float) -> _FakeResponse:
		"""Capture the ZIP multipart request without contacting Discord."""
		captured["request"] = request
		captured["timeout"] = timeout
		return _FakeResponse(json.dumps({"id": "100000000000000011"}).encode())

	client = DiscordRestClient(uuid4().hex, opener=fake_opener)
	message_id = client.create_message(
		CHANNEL_ID,
		"generated archive",
		attachments=(
			DiscordUpload("results.zip", "application/zip", zip_buffer.getvalue()),
		),
	)

	assert message_id == "100000000000000011"
	assert b'filename="results.zip"' in captured["request"].data
	assert zip_buffer.getvalue() in captured["request"].data
