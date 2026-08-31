"""Durable Discord thread bindings and creator-only prompt delivery state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from time import time

AGENT_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MESSAGE_STATUSES = frozenset(
	{
		"staging",
		"pending",
		"processing",
		"answer_ready",
		"delivering",
		"delivered",
		"cancelled",
	}
)
class ThreadBindingStoreError(RuntimeError):
	"""Identify invalid or conflicting durable thread-binding operations."""


@dataclass(frozen=True, slots=True)
class ThreadBinding:
	"""Describe one Discord thread's persistent owner and selected agent."""

	thread_id: str
	guild_id: str
	parent_channel_id: str
	agent_tag: str
	creator_user_id: str
	active: bool


@dataclass(frozen=True, slots=True)
class ThreadPromptJob:
	"""Hold one creator message while it moves through Codex and Discord delivery."""

	message_id: str
	thread_id: str
	guild_id: str
	agent_tag: str
	author_user_id: str
	prompt: str
	status: str
	answer: str | None
	attachments_json: str
	attempts: int


class ThreadBindingStore:
	"""Coordinate thread creation and observer delivery across separate processes."""

	def __init__(
		self,
		database_path: Path,
		clock: Callable[[], float] = time,
		recover_interrupted: bool = False,
	) -> None:
		"""Create the shared schema and optionally recover observer-owned delivery work."""
		self._database_path = database_path
		self._clock = clock
		database_path.parent.mkdir(parents=True, exist_ok=True)
		with self._connect() as connection:
			connection.execute("PRAGMA journal_mode = WAL")
			connection.executescript(
				"""
				CREATE TABLE IF NOT EXISTS agent_thread_bindings (
					thread_id TEXT PRIMARY KEY,
					guild_id TEXT NOT NULL,
					parent_channel_id TEXT NOT NULL,
					agent_tag TEXT NOT NULL,
					creator_user_id TEXT NOT NULL,
					active INTEGER NOT NULL,
					created_at REAL NOT NULL,
					closed_at REAL,
					close_reason TEXT
				);
				CREATE INDEX IF NOT EXISTS agent_thread_bindings_agent_tag
					ON agent_thread_bindings(agent_tag);
				CREATE TABLE IF NOT EXISTS agent_thread_messages (
					message_id TEXT PRIMARY KEY,
					thread_id TEXT NOT NULL,
					guild_id TEXT NOT NULL,
					agent_tag TEXT NOT NULL,
					author_user_id TEXT NOT NULL,
					prompt TEXT NOT NULL,
					status TEXT NOT NULL,
					answer TEXT,
					attachments_json TEXT NOT NULL DEFAULT '[]',
					response_message_id TEXT,
					attempts INTEGER NOT NULL DEFAULT 0,
					next_attempt_at REAL NOT NULL,
					created_at REAL NOT NULL,
					updated_at REAL NOT NULL
				);
				CREATE INDEX IF NOT EXISTS agent_thread_messages_status
					ON agent_thread_messages(status, next_attempt_at, created_at);
				"""
			)
			columns = {
				str(row["name"])
				for row in connection.execute(
					"PRAGMA table_info(agent_thread_messages)"
				).fetchall()
			}
			if "attachments_json" not in columns:
				connection.execute(
					"ALTER TABLE agent_thread_messages "
					"ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'"
				)
			if recover_interrupted:
				connection.executescript(
					"""
					UPDATE agent_thread_messages
					SET status = 'answer_ready', prompt = '',
						answer = 'The attachment transfer was interrupted. Please send the message and files again.'
					WHERE status = 'staging' AND EXISTS (
						SELECT 1 FROM agent_thread_bindings AS binding
						WHERE binding.thread_id = agent_thread_messages.thread_id
							AND binding.active = 1
					);
					UPDATE agent_thread_messages
					SET status = 'cancelled', prompt = '', answer = NULL, attachments_json = '[]'
					WHERE status IN ('staging', 'pending', 'processing', 'answer_ready', 'delivering')
						AND EXISTS (
							SELECT 1 FROM agent_thread_bindings AS binding
							WHERE binding.thread_id = agent_thread_messages.thread_id
								AND binding.active = 0
						);
					UPDATE agent_thread_messages SET status = 'pending'
						WHERE status = 'processing';
					UPDATE agent_thread_messages SET status = 'answer_ready'
						WHERE status = 'delivering';
					"""
				)

	def _connect(self) -> sqlite3.Connection:
		"""Open one short-lived process-safe connection with bounded lock waiting."""
		connection = sqlite3.connect(self._database_path, timeout=5)
		connection.row_factory = sqlite3.Row
		connection.execute("PRAGMA busy_timeout = 5000")
		return connection

	def bind_thread(
		self,
		thread_id: str,
		guild_id: str,
		parent_channel_id: str,
		agent_tag: str,
		creator_user_id: str,
	) -> ThreadBinding:
		"""Persist one newly created thread without replacing an existing binding."""
		for identifier in (thread_id, guild_id, parent_channel_id, creator_user_id):
			if not identifier.isdecimal() or len(identifier) > 32:
				raise ThreadBindingStoreError("A Discord binding identifier is invalid.")
		if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise ThreadBindingStoreError("The agent tag is invalid.")
		now = self._clock()
		try:
			with self._connect() as connection:
				connection.execute(
					"""
					INSERT INTO agent_thread_bindings (
						thread_id, guild_id, parent_channel_id, agent_tag,
						creator_user_id, active, created_at
					) VALUES (?, ?, ?, ?, ?, 1, ?)
					""",
					(
						thread_id,
						guild_id,
						parent_channel_id,
						agent_tag,
						creator_user_id,
						now,
					),
				)
		except sqlite3.IntegrityError as error:
			raise ThreadBindingStoreError("The Discord thread is already bound.") from error
		return ThreadBinding(
			thread_id,
			guild_id,
			parent_channel_id,
			agent_tag,
			creator_user_id,
			True,
		)

	def get_binding(self, thread_id: str) -> ThreadBinding | None:
		"""Return one binding without exposing queued message content."""
		with self._connect() as connection:
			row = connection.execute(
				"SELECT * FROM agent_thread_bindings WHERE thread_id = ?",
				(thread_id,),
			).fetchone()
		return None if row is None else self._binding_from_row(row)

	def list_agent_tags(self) -> tuple[str, ...]:
		"""List tags from active and closed bindings because agents outlive threads."""
		with self._connect() as connection:
			rows = connection.execute(
				"SELECT DISTINCT agent_tag FROM agent_thread_bindings ORDER BY agent_tag"
			).fetchall()
		return tuple(str(row["agent_tag"]) for row in rows)

	def close_binding(self, thread_id: str, reason: str) -> bool:
		"""Deactivate a thread and cancel its undelivered local messages only."""
		if not thread_id.isdecimal() or not 1 <= len(reason) <= 32:
			return False
		with self._connect() as connection:
			now = self._clock()
			cursor = connection.execute(
				"""
				UPDATE agent_thread_bindings
				SET active = 0, closed_at = ?, close_reason = ?
				WHERE thread_id = ? AND active = 1
				""",
				(now, reason, thread_id),
			)
			connection.execute(
				"""
				UPDATE agent_thread_messages
				SET status = 'cancelled', prompt = '', answer = NULL,
					attachments_json = '[]', updated_at = ?
				WHERE thread_id = ?
					AND status IN ('staging', 'pending', 'processing', 'answer_ready', 'delivering')
				""",
				(now, thread_id),
			)
		return cursor.rowcount == 1

	def delete_agent_bindings(self, agent_tag: str) -> None:
		"""Erase all thread bindings and local delivery records for a deleted agent."""
		if not AGENT_TAG_PATTERN.fullmatch(agent_tag):
			raise ThreadBindingStoreError("The agent tag is invalid.")
		with self._connect() as connection:
			connection.execute(
				"DELETE FROM agent_thread_messages WHERE agent_tag = ?",
				(agent_tag,),
			)
			connection.execute(
				"DELETE FROM agent_thread_bindings WHERE agent_tag = ?",
				(agent_tag,),
			)

	def enqueue_creator_message(
		self,
		message_id: str,
		thread_id: str,
		guild_id: str,
		author_user_id: str,
		prompt: str,
	) -> bool:
		"""Atomically accept one unique text message only from the binding creator."""
		return self.reserve_creator_message(
			message_id,
			thread_id,
			guild_id,
			author_user_id,
			prompt,
			staging=False,
		) is not None

	def reserve_creator_message(
		self,
		message_id: str,
		thread_id: str,
		guild_id: str,
		author_user_id: str,
		prompt: str,
		staging: bool,
	) -> str | None:
		"""Reserve one creator message and return its tag before attachment staging."""
		if any(
			not identifier.isdecimal() or len(identifier) > 32
			for identifier in (message_id, thread_id, guild_id, author_user_id)
		):
			return None
		bounded_prompt = prompt.strip()
		if (not bounded_prompt and not staging) or len(bounded_prompt) > 4_000:
			return None
		with self._connect() as connection:
			binding = connection.execute(
				"""
				SELECT agent_tag FROM agent_thread_bindings
				WHERE thread_id = ? AND guild_id = ? AND creator_user_id = ? AND active = 1
				""",
				(thread_id, guild_id, author_user_id),
			).fetchone()
			if binding is None:
				return None
			now = self._clock()
			status = "staging" if staging else "pending"
			cursor = connection.execute(
				"""
				INSERT OR IGNORE INTO agent_thread_messages (
					message_id, thread_id, guild_id, agent_tag, author_user_id,
					prompt, status, next_attempt_at, created_at, updated_at
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(
					message_id,
					thread_id,
					guild_id,
					str(binding["agent_tag"]),
					author_user_id,
					bounded_prompt,
					status,
					now,
					now,
					now,
				),
			)
		return str(binding["agent_tag"]) if cursor.rowcount == 1 else None

	def finish_staging(self, message_id: str, prompt: str) -> bool:
		"""Release a reserved message after every attachment reached its workspace."""
		bounded_prompt = prompt.strip()
		if not bounded_prompt or len(bounded_prompt) > 4_000:
			return False
		with self._connect() as connection:
			cursor = connection.execute(
				"""
				UPDATE agent_thread_messages
				SET status = 'pending', prompt = ?, updated_at = ?
				WHERE message_id = ? AND status = 'staging' AND EXISTS (
					SELECT 1 FROM agent_thread_bindings AS binding
					WHERE binding.thread_id = agent_thread_messages.thread_id
						AND binding.active = 1
				)
				""",
				(bounded_prompt, self._clock(), message_id),
			)
		return cursor.rowcount == 1

	def fail_staging(self, message_id: str, answer: str) -> bool:
		"""Turn an attachment-policy or transfer failure into a durable safe reply."""
		bounded_answer = answer.strip()[:2_000]
		if not bounded_answer:
			return False
		with self._connect() as connection:
			now = self._clock()
			cursor = connection.execute(
				"""
				UPDATE agent_thread_messages
				SET status = 'answer_ready', prompt = '', answer = ?,
					next_attempt_at = ?, updated_at = ?
				WHERE message_id = ? AND status = 'staging' AND EXISTS (
					SELECT 1 FROM agent_thread_bindings AS binding
					WHERE binding.thread_id = agent_thread_messages.thread_id
						AND binding.active = 1
				)
				""",
				(bounded_answer, now, now, message_id),
			)
		return cursor.rowcount == 1

	def claim_prompt(self) -> ThreadPromptJob | None:
		"""Claim the oldest pending creator message for sequential worker submission."""
		with self._connect() as connection:
			connection.execute("BEGIN IMMEDIATE")
			row = connection.execute(
				"""
				SELECT message.* FROM agent_thread_messages AS message
				JOIN agent_thread_bindings AS binding
					ON binding.thread_id = message.thread_id
				WHERE message.status = 'pending' AND binding.active = 1
				ORDER BY message.created_at LIMIT 1
				"""
			).fetchone()
			if row is None:
				return None
			connection.execute(
				"UPDATE agent_thread_messages SET status = 'processing', updated_at = ? WHERE message_id = ?",
				(self._clock(), row["message_id"]),
			)
			return self._job_from_row(row, "processing")

	def store_answer(
		self,
		message_id: str,
		answer: str,
		attachments_json: str = "[]",
	) -> bool:
		"""Persist an answer only while its creator-owned binding remains active."""
		if len(attachments_json.encode("utf-8")) > 4_096:
			raise ThreadBindingStoreError("The attachment manifest is too large.")
		with self._connect() as connection:
			now = self._clock()
			cursor = connection.execute(
				"""
				UPDATE agent_thread_messages
				SET status = 'answer_ready', answer = ?, attachments_json = ?,
					next_attempt_at = ?, updated_at = ?
				WHERE message_id = ? AND status = 'processing' AND EXISTS (
					SELECT 1 FROM agent_thread_bindings AS binding
					WHERE binding.thread_id = agent_thread_messages.thread_id
						AND binding.active = 1
				)
				""",
				(answer[:2_000], attachments_json, now, now, message_id),
			)
			if cursor.rowcount != 1:
				connection.execute(
					"""
					UPDATE agent_thread_messages
					SET status = 'cancelled', prompt = '', answer = NULL,
						attachments_json = '[]', updated_at = ?
					WHERE message_id = ? AND status = 'processing'
					""",
					(now, message_id),
				)
		return cursor.rowcount == 1

	def claim_answer(self) -> ThreadPromptJob | None:
		"""Claim one due answer whose thread binding remains active."""
		with self._connect() as connection:
			connection.execute("BEGIN IMMEDIATE")
			row = connection.execute(
				"""
				SELECT message.* FROM agent_thread_messages AS message
				JOIN agent_thread_bindings AS binding
					ON binding.thread_id = message.thread_id
				WHERE message.status = 'answer_ready'
					AND message.next_attempt_at <= ? AND binding.active = 1
				ORDER BY message.created_at LIMIT 1
				""",
				(self._clock(),),
			).fetchone()
			if row is None:
				return None
			connection.execute(
				"UPDATE agent_thread_messages SET status = 'delivering', updated_at = ? WHERE message_id = ?",
				(self._clock(), row["message_id"]),
			)
			return self._job_from_row(row, "delivering")

	def reschedule_answer(self, message_id: str, delay_seconds: float) -> None:
		"""Return one failed Discord delivery to the queue with bounded backoff."""
		with self._connect() as connection:
			now = self._clock()
			connection.execute(
				"""
				UPDATE agent_thread_messages
				SET status = 'answer_ready', attempts = attempts + 1,
					next_attempt_at = ?, updated_at = ?
				WHERE message_id = ? AND status = 'delivering'
				""",
				(now + max(1.0, delay_seconds), now, message_id),
			)

	def mark_delivered(self, message_id: str, response_message_id: str) -> None:
		"""Finish one response and erase retained prompt/answer content from this store."""
		with self._connect() as connection:
			connection.execute(
				"""
				UPDATE agent_thread_messages
				SET status = 'delivered', response_message_id = ?, prompt = '',
					answer = NULL, attachments_json = '[]', updated_at = ?
				WHERE message_id = ? AND status = 'delivering'
				""",
				(response_message_id, self._clock(), message_id),
			)

	def cancel_message(self, message_id: str) -> None:
		"""Cancel one job whose binding closed while Codex was processing it."""
		with self._connect() as connection:
			connection.execute(
				"""
				UPDATE agent_thread_messages
				SET status = 'cancelled', prompt = '', answer = NULL,
					attachments_json = '[]', updated_at = ?
				WHERE message_id = ? AND status != 'delivered'
				""",
				(self._clock(), message_id),
			)

	def binding_is_active(self, thread_id: str) -> bool:
		"""Check whether a response may still be delivered to its source thread."""
		binding = self.get_binding(thread_id)
		return binding is not None and binding.active

	@staticmethod
	def _binding_from_row(row: sqlite3.Row) -> ThreadBinding:
		"""Convert one SQLite binding row into an immutable boundary object."""
		return ThreadBinding(
			thread_id=str(row["thread_id"]),
			guild_id=str(row["guild_id"]),
			parent_channel_id=str(row["parent_channel_id"]),
			agent_tag=str(row["agent_tag"]),
			creator_user_id=str(row["creator_user_id"]),
			active=bool(row["active"]),
		)

	@staticmethod
	def _job_from_row(row: sqlite3.Row, status: str) -> ThreadPromptJob:
		"""Convert one SQLite message row into a bounded queue job."""
		if status not in MESSAGE_STATUSES:
			raise ThreadBindingStoreError("The thread-message status is invalid.")
		return ThreadPromptJob(
			message_id=str(row["message_id"]),
			thread_id=str(row["thread_id"]),
			guild_id=str(row["guild_id"]),
			agent_tag=str(row["agent_tag"]),
			author_user_id=str(row["author_user_id"]),
			prompt=str(row["prompt"]),
			status=status,
			answer=None if row["answer"] is None else str(row["answer"]),
			attachments_json=str(row["attachments_json"]),
			attempts=int(row["attempts"]),
		)
