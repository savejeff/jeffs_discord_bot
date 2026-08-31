"""Durable SQLite prompt queue and tagged Codex conversation state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, tzinfo
import json
from pathlib import Path
import sqlite3
import threading
from time import time

from codex_agent_worker.models import CodexRuntimeProfile, PromptJob


class WorkerStoreError(RuntimeError):
	"""Identify a queue request that conflicts with durable worker state."""


class WorkerStore:
	"""Serialize queue operations and recover interrupted prompts after restart."""

	def __init__(self, database_path: Path, clock: Callable[[], float] = time) -> None:
		"""Open the worker database and create its bounded proof-of-concept schema."""
		self._lock = threading.Lock()
		self._clock = clock
		database_path.parent.mkdir(parents=True, exist_ok=True)
		self._connection = sqlite3.connect(database_path, check_same_thread=False)
		self._connection.row_factory = sqlite3.Row
		self._initialize()

	def _initialize(self) -> None:
		"""Create queue/session tables and return interrupted jobs to pending state."""
		with self._lock, self._connection:
			self._connection.executescript(
				"""
				CREATE TABLE IF NOT EXISTS metadata (
					key TEXT PRIMARY KEY,
					value TEXT NOT NULL
				);
				CREATE TABLE IF NOT EXISTS jobs (
					request_id TEXT PRIMARY KEY,
					agent_tag TEXT NOT NULL DEFAULT 'dev1',
					prompt TEXT NOT NULL,
					metadata_json TEXT NOT NULL,
					status TEXT NOT NULL,
					response TEXT,
					error TEXT,
					created_at REAL NOT NULL,
					updated_at REAL NOT NULL
				);
				CREATE TABLE IF NOT EXISTS activity_intervals (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					request_id TEXT NOT NULL,
					started_at REAL NOT NULL,
					last_seen_at REAL NOT NULL,
					ended_at REAL
				);
				CREATE INDEX IF NOT EXISTS activity_intervals_request_id
				ON activity_intervals(request_id);
				UPDATE activity_intervals SET ended_at = last_seen_at
				WHERE ended_at IS NULL;
				UPDATE jobs SET status = 'pending', error = NULL
				WHERE status = 'processing';
				"""
			)
			columns = {
				str(row["name"])
				for row in self._connection.execute("PRAGMA table_info(jobs)").fetchall()
			}
			if "agent_tag" not in columns:
				self._connection.execute(
					"ALTER TABLE jobs ADD COLUMN agent_tag TEXT NOT NULL DEFAULT 'dev1'"
				)

	def close(self) -> None:
		"""Close the database after the worker loop has stopped."""
		with self._lock:
			self._connection.close()

	def enqueue(
		self,
		request_id: str,
		prompt: str,
		metadata_json: str,
		agent_tag: str = "dev1",
	) -> PromptJob:
		"""Persist one idempotent prompt or return the matching existing job."""
		now = self._clock()
		with self._lock, self._connection:
			self._connection.execute(
				"DELETE FROM metadata WHERE key = ?",
				(f"agent_deleted:{agent_tag}",),
			)
			row = self._connection.execute(
				"SELECT * FROM jobs WHERE request_id = ?",
				(request_id,),
			).fetchone()
			if row is not None:
				if (
					row["prompt"] != prompt
					or row["metadata_json"] != metadata_json
					or row["agent_tag"] != agent_tag
				):
					raise WorkerStoreError("The request identifier is already in use.")
				return self._job_from_row(row)
			self._connection.execute(
				"""
				INSERT INTO jobs (
					request_id, agent_tag, prompt, metadata_json, status, created_at, updated_at
				) VALUES (?, ?, ?, ?, 'pending', ?, ?)
				""",
				(request_id, agent_tag, prompt, metadata_json, now, now),
			)
			row = self._connection.execute(
				"SELECT * FROM jobs WHERE request_id = ?",
				(request_id,),
			).fetchone()
		assert row is not None
		return self._job_from_row(row)

	def claim_next(self) -> PromptJob | None:
		"""Claim the oldest pending prompt from the shared tagged-agent queue."""
		with self._lock, self._connection:
			row = self._connection.execute(
				"SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at LIMIT 1"
			).fetchone()
			if row is None:
				return None
			now = self._clock()
			self._connection.execute(
				"""
				UPDATE jobs SET status = 'processing', error = NULL, updated_at = ?
				WHERE request_id = ?
				""",
				(now, row["request_id"]),
			)
			self._connection.execute(
				"""
				INSERT INTO activity_intervals (
					request_id, started_at, last_seen_at, ended_at
				) VALUES (?, ?, ?, NULL)
				""",
				(row["request_id"], now, now),
			)
			return PromptJob(
				request_id=str(row["request_id"]),
				prompt=str(row["prompt"]),
				metadata_json=str(row["metadata_json"]),
				status="processing",
				agent_tag=str(row["agent_tag"]),
			)

	def get_job(self, request_id: str) -> PromptJob | None:
		"""Read one job for WebSocket status delivery without changing it."""
		with self._lock:
			row = self._connection.execute(
				"SELECT * FROM jobs WHERE request_id = ?",
				(request_id,),
			).fetchone()
		return None if row is None else self._job_from_row(row)

	def queue_position(self, request_id: str) -> int:
		"""Return the one-based position among queued and active jobs."""
		with self._lock:
			row = self._connection.execute(
				"SELECT created_at FROM jobs WHERE request_id = ?",
				(request_id,),
			).fetchone()
			if row is None:
				return 0
			count = self._connection.execute(
				"""
				SELECT COUNT(*) AS count FROM jobs
				WHERE status IN ('pending', 'processing') AND created_at <= ?
				""",
				(row["created_at"],),
			).fetchone()
		return 0 if count is None else int(count["count"])

	def mark_completed(self, request_id: str, response: str) -> None:
		"""Persist the final response for later delivery or reconnect retrieval."""
		with self._lock, self._connection:
			now = self._clock()
			self._finish_activity_locked(request_id, now)
			self._connection.execute(
				"""
				UPDATE jobs SET status = 'completed', response = ?, error = NULL, updated_at = ?
				WHERE request_id = ?
				""",
				(response, now, request_id),
			)

	def mark_failed(self, request_id: str, error: str) -> None:
		"""Persist only a bounded redacted failure diagnostic for one prompt."""
		with self._lock, self._connection:
			now = self._clock()
			self._finish_activity_locked(request_id, now)
			self._connection.execute(
				"""
				UPDATE jobs SET status = 'failed', error = ?, updated_at = ?
				WHERE request_id = ?
				""",
				(error[:500], now, request_id),
			)

	def heartbeat_activity(self, request_id: str) -> None:
		"""Advance the durable heartbeat for the currently executing Codex child."""
		with self._lock, self._connection:
			self._connection.execute(
				"""
				UPDATE activity_intervals SET last_seen_at = ?
				WHERE id = (
					SELECT id FROM activity_intervals
					WHERE request_id = ? AND ended_at IS NULL
					ORDER BY id DESC LIMIT 1
				)
				""",
				(self._clock(), request_id),
			)

	def status_snapshot(
		self,
		time_zone: tzinfo,
		agent_tag: str,
		recent_limit: int = 10,
	) -> dict[str, object]:
		"""Aggregate one tag's queue, active-time, and recent-command status."""
		if not 1 <= recent_limit <= 25:
			raise ValueError("Recent command limit is outside the supported range.")
		now = self._clock()
		local_now = datetime.fromtimestamp(now, time_zone)
		today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
		with self._lock:
			status_rows = self._connection.execute(
				"""
				SELECT status, COUNT(*) AS count FROM jobs
				WHERE agent_tag = ? GROUP BY status
				""",
				(agent_tag,),
			).fetchall()
			interval_rows = self._connection.execute(
				"""
				SELECT activity.started_at, activity.ended_at
				FROM activity_intervals AS activity
				JOIN jobs AS job ON job.request_id = activity.request_id
				WHERE job.agent_tag = ?
				""",
				(agent_tag,),
			).fetchall()
			recent_rows = self._connection.execute(
				"""
				SELECT metadata_json, status, created_at FROM jobs
				WHERE agent_tag = ? ORDER BY created_at DESC LIMIT ?
				""",
				(agent_tag, recent_limit),
			).fetchall()
			runtime_profile = self._runtime_profile_locked(agent_tag)

		counts = {str(row["status"]): int(row["count"]) for row in status_rows}
		total_active_seconds = 0.0
		today_active_seconds = 0.0
		for row in interval_rows:
			started_at = float(row["started_at"])
			ended_at = now if row["ended_at"] is None else float(row["ended_at"])
			if ended_at <= started_at:
				continue
			total_active_seconds += ended_at - started_at
			today_active_seconds += max(0.0, ended_at - max(started_at, today_start))

		recent_commands: list[dict[str, object]] = []
		for row in recent_rows:
			try:
				metadata = json.loads(str(row["metadata_json"]))
			except json.JSONDecodeError:
				metadata = {}
			if not isinstance(metadata, dict):
				metadata = {}
			recent_commands.append(
				{
					"received_at": datetime.fromtimestamp(
						float(row["created_at"]), time_zone
					).isoformat(timespec="seconds"),
					"command": self._metadata_identifier(metadata, "command", "unknown"),
					"status": str(row["status"]),
					"user_id": self._metadata_identifier(metadata, "user_id", None),
					"channel_id": self._metadata_identifier(metadata, "channel_id", None),
				}
			)

		queued = counts.get("pending", 0)
		processing = counts.get("processing", 0)
		completed = counts.get("completed", 0)
		failed = counts.get("failed", 0)
		return {
			"state": "running" if processing else "idle",
			"model": None if runtime_profile is None else runtime_profile.model,
			"reasoning_level": (
				None if runtime_profile is None else runtime_profile.reasoning_level
			),
			"runtime_profile_scope": (
				"unavailable" if runtime_profile is None else "most_recent"
			),
			"queued": queued,
			"processing": processing,
			"processed": completed + failed,
			"completed": completed,
			"failed": failed,
			"total_active_seconds": total_active_seconds,
			"today_active_seconds": today_active_seconds,
			"time_zone": getattr(time_zone, "key", str(time_zone)),
			"recent_commands": recent_commands,
		}

	def set_runtime_profile(
		self,
		profile: CodexRuntimeProfile,
		agent_tag: str = "dev1",
	) -> None:
		"""Persist the latest model profile observed in a Codex turn context."""
		metadata_key = f"codex_runtime_profile:{agent_tag}"
		value = json.dumps(
			{
				"model": profile.model,
				"reasoning_level": profile.reasoning_level,
				"observed_at": profile.observed_at,
			},
			separators=(",", ":"),
			sort_keys=True,
		)
		with self._lock, self._connection:
			self._connection.execute(
				"""
				INSERT INTO metadata(key, value) VALUES (?, ?)
				ON CONFLICT(key) DO UPDATE SET value = excluded.value
				""",
				(metadata_key, value),
			)

	def _runtime_profile_locked(self, agent_tag: str) -> CodexRuntimeProfile | None:
		"""Read a validated runtime profile while the store lock is already held."""
		row = self._connection.execute(
			"SELECT value FROM metadata WHERE key = ?",
			(f"codex_runtime_profile:{agent_tag}",),
		).fetchone()
		if row is None:
			return None
		try:
			value = json.loads(str(row["value"]))
		except json.JSONDecodeError:
			return None
		if not isinstance(value, dict):
			return None
		model = value.get("model")
		reasoning_level = value.get("reasoning_level")
		observed_at = value.get("observed_at")
		if (
			not isinstance(model, str)
			or not model
			or len(model) > 128
			or (reasoning_level is not None and not isinstance(reasoning_level, str))
			or (isinstance(reasoning_level, str) and len(reasoning_level) > 64)
			or type(observed_at) not in {int, float}
		):
			return None
		return CodexRuntimeProfile(model, reasoning_level, float(observed_at))

	def _finish_activity_locked(self, request_id: str, ended_at: float) -> None:
		"""Close the newest open activity interval while the store lock is held."""
		self._connection.execute(
			"""
			UPDATE activity_intervals SET last_seen_at = ?, ended_at = ?
			WHERE id = (
				SELECT id FROM activity_intervals
				WHERE request_id = ? AND ended_at IS NULL
				ORDER BY id DESC LIMIT 1
			)
			""",
			(ended_at, ended_at, request_id),
		)

	@staticmethod
	def _metadata_identifier(
		metadata: dict[str, object],
		field_name: str,
		default: str | None,
	) -> str | None:
		"""Return one bounded numeric or command metadata value for status reporting."""
		value = metadata.get(field_name)
		if not isinstance(value, str) or len(value) > 64:
			return default
		if field_name == "command" and (
			not value
			or len(value) > 32
			or any(
				character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
				for character in value
			)
		):
			return default
		if field_name != "command" and not value.isdecimal():
			return default
		return value

	def get_thread_id(self, agent_tag: str = "dev1") -> str | None:
		"""Return the persisted Codex conversation identifier for one agent tag."""
		metadata_key = f"codex_thread_id:{agent_tag}"
		with self._lock, self._connection:
			row = self._connection.execute(
				"SELECT value FROM metadata WHERE key = ?",
				(metadata_key,),
			).fetchone()
			# Preserve the original proof-of-concept conversation when dev1 is upgraded.
			if row is None and agent_tag == "dev1":
				row = self._connection.execute(
					"SELECT value FROM metadata WHERE key = 'codex_thread_id'"
				).fetchone()
				if row is not None and row["value"]:
					self._connection.execute(
						"INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)",
						(metadata_key, row["value"]),
					)
		return None if row is None or not row["value"] else str(row["value"])

	def set_thread_id(self, thread_id: str, agent_tag: str = "dev1") -> None:
		"""Persist one conversation identifier under its assigned agent tag."""
		metadata_key = f"codex_thread_id:{agent_tag}"
		with self._lock, self._connection:
			self._connection.execute(
				"""
				INSERT INTO metadata(key, value) VALUES (?, ?)
				ON CONFLICT(key) DO UPDATE SET value = excluded.value
				""",
				(metadata_key, thread_id),
			)

	def latest_agent_tag(self, default_agent_tag: str = "dev1") -> str:
		"""Return the active or most recently updated durable job's agent tag."""
		with self._lock:
			row = self._connection.execute(
				"""
				SELECT agent_tag FROM jobs
				ORDER BY (status = 'processing') DESC, updated_at DESC
				LIMIT 1
				"""
			).fetchone()
		if row is None or not row["agent_tag"]:
			return default_agent_tag
		return str(row["agent_tag"])

	def list_agent_tags(self) -> tuple[str, ...]:
		"""Return every distinct tag represented in the durable prompt queue."""
		with self._lock:
			rows = self._connection.execute(
				"SELECT DISTINCT agent_tag FROM jobs ORDER BY agent_tag"
			).fetchall()
		return tuple(str(row["agent_tag"]) for row in rows if row["agent_tag"])

	def has_unfinished_jobs(self, agent_tag: str) -> bool:
		"""Report whether a tagged agent still has queued or processing work."""
		with self._lock:
			row = self._connection.execute(
				"""
				SELECT 1 FROM jobs
				WHERE agent_tag = ? AND status IN ('pending', 'processing')
				LIMIT 1
				""",
				(agent_tag,),
			).fetchone()
		return row is not None

	def set_agent_runtime_config(
		self,
		agent_tag: str,
		model: str,
		reasoning_level: str,
	) -> None:
		"""Persist a moderator-selected runtime profile for one tagged agent."""
		value = json.dumps(
			{"model": model, "reasoning_level": reasoning_level},
			separators=(",", ":"),
			sort_keys=True,
		)
		with self._lock, self._connection:
			self._connection.execute(
				"""
				INSERT INTO metadata(key, value) VALUES (?, ?)
				ON CONFLICT(key) DO UPDATE SET value = excluded.value
				""",
				(f"agent_runtime_config:{agent_tag}", value),
			)
			self._connection.execute(
				"DELETE FROM metadata WHERE key = ?",
				(f"agent_deleted:{agent_tag}",),
			)

	def get_agent_runtime_config(self, agent_tag: str) -> tuple[str, str] | None:
		"""Read one previously validated runtime profile override."""
		with self._lock:
			row = self._connection.execute(
				"SELECT value FROM metadata WHERE key = ?",
				(f"agent_runtime_config:{agent_tag}",),
			).fetchone()
		if row is None:
			return None
		try:
			value = json.loads(str(row["value"]))
		except json.JSONDecodeError:
			return None
		if not isinstance(value, dict):
			return None
		model = value.get("model")
		reasoning_level = value.get("reasoning_level")
		if not isinstance(model, str) or not isinstance(reasoning_level, str):
			return None
		return model, reasoning_level

	def list_runtime_config_tags(self) -> tuple[str, ...]:
		"""List tags that have durable runtime configuration overrides."""
		prefix = "agent_runtime_config:"
		with self._lock:
			rows = self._connection.execute(
				"SELECT key FROM metadata WHERE key LIKE ? ORDER BY key",
				(f"{prefix}%",),
			).fetchall()
		return tuple(str(row["key"])[len(prefix):] for row in rows)

	def list_deleted_agent_tags(self) -> tuple[str, ...]:
		"""List tombstoned tags so static config does not recreate deleted agents."""
		prefix = "agent_deleted:"
		with self._lock:
			rows = self._connection.execute(
				"SELECT key FROM metadata WHERE key LIKE ? ORDER BY key",
				(f"{prefix}%",),
			).fetchall()
		return tuple(str(row["key"])[len(prefix):] for row in rows)

	def is_agent_deleted(self, agent_tag: str) -> bool:
		"""Check whether a lifecycle command explicitly removed this tag."""
		with self._lock:
			row = self._connection.execute(
				"SELECT 1 FROM metadata WHERE key = ?",
				(f"agent_deleted:{agent_tag}",),
			).fetchone()
		return row is not None

	def delete_agent_state(self, agent_tag: str) -> None:
		"""Erase one idle agent's queue history, conversation, profile, and override."""
		with self._lock, self._connection:
			unfinished = self._connection.execute(
				"""
				SELECT 1 FROM jobs
				WHERE agent_tag = ? AND status IN ('pending', 'processing')
				LIMIT 1
				""",
				(agent_tag,),
			).fetchone()
			if unfinished is not None:
				raise WorkerStoreError("The agent still has queued or active work.")
			self._connection.execute(
				"""
				DELETE FROM activity_intervals
				WHERE request_id IN (SELECT request_id FROM jobs WHERE agent_tag = ?)
				""",
				(agent_tag,),
			)
			self._connection.execute("DELETE FROM jobs WHERE agent_tag = ?", (agent_tag,))
			for metadata_key in (
				f"codex_thread_id:{agent_tag}",
				f"codex_runtime_profile:{agent_tag}",
				f"agent_runtime_config:{agent_tag}",
			):
				self._connection.execute(
					"DELETE FROM metadata WHERE key = ?",
					(metadata_key,),
				)
			if agent_tag == "dev1":
				self._connection.execute(
					"DELETE FROM metadata WHERE key = 'codex_thread_id'"
				)
			self._connection.execute(
				"""
				INSERT INTO metadata(key, value) VALUES (?, '1')
				ON CONFLICT(key) DO UPDATE SET value = excluded.value
				""",
				(f"agent_deleted:{agent_tag}",),
			)

	@staticmethod
	def _job_from_row(row: sqlite3.Row) -> PromptJob:
		"""Convert one SQLite row into the immutable job boundary."""
		return PromptJob(
			request_id=str(row["request_id"]),
			prompt=str(row["prompt"]),
			metadata_json=str(row["metadata_json"]),
			status=str(row["status"]),
			agent_tag=str(row["agent_tag"]),
			response=row["response"],
			error=row["error"],
		)
