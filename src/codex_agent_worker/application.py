"""ASGI WebSocket module around sequential persistent tagged Codex agents."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timezone, tzinfo
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from codex_agent_worker.agent_config import (
	AgentConfigError,
	validate_agent_tag,
)
from codex_agent_worker.artifacts import (
	MAX_ATTACHMENT_BYTES,
	WorkspaceArtifact,
	WorkspaceArtifactError,
	WorkspaceArtifactStore,
)
from codex_agent_worker.models import CodexRunResult, CodexRuntimeProfile, PromptJob
from codex_agent_worker.runner_registry import AgentRunnerRegistry
from codex_agent_worker.storage import WorkerStore, WorkerStoreError

LOGGER = logging.getLogger("codex_agent_worker")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_PROMPT_LENGTH = 4_000
MAX_METADATA_BYTES = 4_096
MAX_RESPONSE_LENGTH = 64_000


class Runner(Protocol):
	"""Describe the Codex runner surface required by the queue service."""

	def run(self, prompt: str, thread_id: str | None) -> CodexRunResult:
		"""Run one initial or resumed Codex turn."""

	def cancel(self) -> None:
		"""Cancel any active turn during shutdown."""

	def current_runtime_profile(self) -> CodexRuntimeProfile | None:
		"""Return the actual profile observed for the active turn, when available."""

	def latest_runtime_profile(self, thread_id: str | None) -> CodexRuntimeProfile | None:
		"""Return the latest actual profile recorded for the tagged conversation."""


RunnerResolver = Callable[[str], Runner]
AgentTagLister = Callable[[], tuple[str, ...]]


class AgentLifecycle(Protocol):
	"""Describe safe workspace lifecycle operations supplied by the runner registry."""

	def invalidate(self, agent_tag: str) -> None:
		"""Discard a cached runner after configuration changes."""

	def delete_workspace(self, agent_tag: str) -> None:
		"""Delete one validated workspace tree."""

	def reset_workspace(self, agent_tag: str) -> None:
		"""Recreate one validated workspace from its template."""

	def delete_conversation(self, thread_id: str | None) -> None:
		"""Delete only rollout files for the selected stored conversation."""


class WorkerService:
	"""Process durable prompts sequentially across persistent tagged conversations."""

	def __init__(
		self,
		store: WorkerStore,
		runner_resolver: RunnerResolver,
		agent_tag_lister: AgentTagLister,
		time_zone: tzinfo,
		default_agent_tag: str,
		artifact_store: WorkspaceArtifactStore,
		agent_lifecycle: AgentLifecycle | None = None,
	) -> None:
		"""Bind the tagged runner resolver and global queue without starting work."""
		self._store = store
		self._runner_resolver = runner_resolver
		self._agent_tag_lister = agent_tag_lister
		self._time_zone = time_zone
		self._default_agent_tag = validate_agent_tag(default_agent_tag)
		self._artifact_store = artifact_store
		self._agent_lifecycle = agent_lifecycle
		self._wake = asyncio.Event()
		self._stop = asyncio.Event()
		self._state_lock = asyncio.Lock()
		self._task: asyncio.Task[None] | None = None
		self._active_runner: Runner | None = None
		self._active_agent_tag: str | None = None
		self._shutdown_runner: Runner | None = None

	async def start(self) -> None:
		"""Start the sole queue consumer and recover any pending database work."""
		if self._task is None:
			self._task = asyncio.create_task(self._work_loop(), name="codex-worker-loop")
			self._wake.set()

	async def stop(self) -> None:
		"""Stop accepting background work and terminate the active Codex child."""
		self._stop.set()
		self._wake.set()
		shutdown_runner = self._active_runner or self._shutdown_runner
		if shutdown_runner is not None:
			await asyncio.to_thread(shutdown_runner.cancel)
		if self._task is not None:
			try:
				await asyncio.wait_for(self._task, timeout=15)
			except TimeoutError:
				self._task.cancel()
				await asyncio.gather(self._task, return_exceptions=True)
			self._task = None

	async def submit(
		self,
		request_id: str,
		prompt: str,
		metadata_json: str,
		agent_tag: str,
	) -> PromptJob:
		"""Persist an idempotent prompt and wake the single queue consumer."""
		async with self._state_lock:
			job = await asyncio.to_thread(
				self._store.enqueue,
				request_id,
				prompt,
				metadata_json,
				validate_agent_tag(agent_tag),
			)
		self._wake.set()
		return job

	async def get_job(self, request_id: str) -> PromptJob | None:
		"""Read the current job state without blocking the event loop."""
		return await asyncio.to_thread(self._store.get_job, request_id)

	async def queue_position(self, request_id: str) -> int:
		"""Read the current queue position for acknowledgement metadata."""
		return await asyncio.to_thread(self._store.queue_position, request_id)

	async def status(self, agent_tag: str) -> dict[str, object]:
		"""Return one known tag's counters without invoking that agent."""
		validated_tag = validate_agent_tag(agent_tag)
		if validated_tag not in await self.agent_tags():
			raise WorkerStoreError("The requested agent does not exist.")
		runner = (
			self._active_runner
			if self._active_agent_tag == validated_tag
			else None
		)
		runner_is_active = runner is not None
		if runner is None and not await asyncio.to_thread(
			self._store.is_agent_deleted,
			validated_tag,
		):
			runner = await asyncio.to_thread(self._runner_resolver, validated_tag)
		current_profile = (
			await asyncio.to_thread(runner.current_runtime_profile)
			if runner_is_active and runner is not None
			else None
		)
		if current_profile is not None:
			await asyncio.to_thread(
				self._store.set_runtime_profile,
				current_profile,
				validated_tag,
			)
		status = await asyncio.to_thread(
			self._store.status_snapshot,
			self._time_zone,
			validated_tag,
			10,
		)
		if current_profile is None and status["model"] is None and runner is not None:
			thread_id = await asyncio.to_thread(
				self._store.get_thread_id,
				validated_tag,
			)
			latest_profile = await asyncio.to_thread(
				runner.latest_runtime_profile,
				thread_id,
			)
			if latest_profile is not None:
				await asyncio.to_thread(
					self._store.set_runtime_profile,
					latest_profile,
					validated_tag,
				)
				status = await asyncio.to_thread(
					self._store.status_snapshot,
					self._time_zone,
					validated_tag,
					10,
				)
		if current_profile is not None:
			status.update(
				{
					"model": current_profile.model,
					"reasoning_level": current_profile.reasoning_level,
					"runtime_profile_scope": "current",
				}
			)
		return {"agent_tag": validated_tag, **status}

	async def agent_tags(self) -> tuple[str, ...]:
		"""Return configured, initialized, and queued tags without running Codex."""
		configured_or_initialized, durable, overridden, deleted = await asyncio.gather(
			asyncio.to_thread(self._agent_tag_lister),
			asyncio.to_thread(self._store.list_agent_tags),
			asyncio.to_thread(self._store.list_runtime_config_tags),
			asyncio.to_thread(self._store.list_deleted_agent_tags),
		)
		known = set(configured_or_initialized) | set(durable) | set(overridden)
		return tuple(sorted(known - set(deleted)))

	async def configure_agent(
		self,
		agent_tag: str,
		model: str,
		reasoning_level: str,
	) -> None:
		"""Persist settings and prepare an idle existing or new tagged agent."""
		validated_tag = validate_agent_tag(agent_tag)
		if self._agent_lifecycle is None:
			raise WorkerStoreError("Agent lifecycle management is unavailable.")
		async with self._state_lock:
			if await asyncio.to_thread(self._store.has_unfinished_jobs, validated_tag):
				raise WorkerStoreError("The agent still has queued or active work.")
			await asyncio.to_thread(
				self._store.set_agent_runtime_config,
				validated_tag,
				model,
				reasoning_level,
			)
			await asyncio.to_thread(self._agent_lifecycle.invalidate, validated_tag)
			await asyncio.to_thread(self._runner_resolver, validated_tag)

	async def reset_agent(self, agent_tag: str) -> None:
		"""Replace every file in an idle known agent workspace from the template."""
		validated_tag = validate_agent_tag(agent_tag)
		if self._agent_lifecycle is None:
			raise WorkerStoreError("Agent lifecycle management is unavailable.")
		async with self._state_lock:
			known_tags = set(await self.agent_tags())
			if validated_tag not in known_tags:
				raise WorkerStoreError("The requested agent does not exist.")
			if await asyncio.to_thread(self._store.has_unfinished_jobs, validated_tag):
				raise WorkerStoreError("The agent still has queued or active work.")
			await asyncio.to_thread(self._agent_lifecycle.reset_workspace, validated_tag)

	async def delete_agent(self, agent_tag: str) -> None:
		"""Delete an idle known agent workspace and all durable worker-side state."""
		validated_tag = validate_agent_tag(agent_tag)
		if self._agent_lifecycle is None:
			raise WorkerStoreError("Agent lifecycle management is unavailable.")
		async with self._state_lock:
			known_tags = set(await self.agent_tags())
			if validated_tag not in known_tags:
				raise WorkerStoreError("The requested agent does not exist.")
			if await asyncio.to_thread(self._store.has_unfinished_jobs, validated_tag):
				raise WorkerStoreError("The agent still has queued or active work.")
			thread_id = await asyncio.to_thread(self._store.get_thread_id, validated_tag)
			await asyncio.to_thread(self._agent_lifecycle.delete_workspace, validated_tag)
			await asyncio.to_thread(self._agent_lifecycle.delete_conversation, thread_id)
			await asyncio.to_thread(self._store.delete_agent_state, validated_tag)

	async def stage_attachment(
		self,
		agent_tag: str,
		request_id: str,
		attachment_id: str,
		filename: str,
		content: bytes,
	) -> str:
		"""Prepare a tagged workspace and store one inbound Discord attachment."""
		validated_tag = validate_agent_tag(agent_tag)
		await asyncio.to_thread(self._runner_resolver, validated_tag)
		return await asyncio.to_thread(
			self._artifact_store.stage_download,
			validated_tag,
			request_id,
			attachment_id,
			filename,
			content,
		)

	async def output_attachments(
		self,
		job: PromptJob,
	) -> tuple[WorkspaceArtifact, ...]:
		"""Return validated uploads only for Discord agent-thread requests."""
		if not _is_agent_thread_job(job):
			return ()
		return await asyncio.to_thread(
			self._artifact_store.list_uploads,
			job.agent_tag,
			job.request_id,
		)

	async def read_output_attachment(
		self,
		agent_tag: str,
		request_id: str,
		filename: str,
		sha256: str,
	) -> tuple[WorkspaceArtifact, bytes]:
		"""Read one digest-pinned outbound file from a tagged workspace."""
		return await asyncio.to_thread(
			self._artifact_store.read_upload,
			agent_tag,
			request_id,
			filename,
			sha256,
		)

	@property
	def default_agent_tag(self) -> str:
		"""Expose the default tag used when a prompt omits explicit routing."""
		return self._default_agent_tag

	async def _run_with_heartbeat(
		self,
		runner: Runner,
		job: PromptJob,
		thread_id: str | None,
	) -> CodexRunResult:
		"""Run one blocking Codex turn while persisting an activity heartbeat."""
		run_task = asyncio.create_task(
			asyncio.to_thread(runner.run, job.prompt, thread_id),
			name=f"codex-turn-{job.request_id}",
		)
		while True:
			try:
				return await asyncio.wait_for(asyncio.shield(run_task), timeout=1)
			except TimeoutError:
				await asyncio.to_thread(self._store.heartbeat_activity, job.request_id)

	async def _work_loop(self) -> None:
		"""Claim and finish prompts sequentially until application shutdown."""
		while not self._stop.is_set():
			async with self._state_lock:
				job = await asyncio.to_thread(self._store.claim_next)
			if job is None:
				self._wake.clear()
				try:
					await asyncio.wait_for(self._wake.wait(), timeout=1)
				except TimeoutError:
					pass
				continue

			try:
				runner = await asyncio.to_thread(self._runner_resolver, job.agent_tag)
				self._active_runner = runner
				self._active_agent_tag = job.agent_tag
				self._shutdown_runner = runner
				thread_id = await asyncio.to_thread(
					self._store.get_thread_id,
					job.agent_tag,
				)
				LOGGER.info(
					"codex_job_started request_id=%s agent_tag=%s conversation=%s",
					job.request_id,
					job.agent_tag,
					"resume" if thread_id else "new",
				)
				if _is_agent_thread_job(job):
					await asyncio.to_thread(
						self._artifact_store.prepare_upload_directory,
						job.agent_tag,
						job.request_id,
					)
				result = await self._run_with_heartbeat(runner, job, thread_id)
			except Exception as error:
				LOGGER.error(
					"codex_job_failed request_id=%s error_type=%s",
					job.request_id,
					type(error).__name__,
				)
				await asyncio.to_thread(
					self._store.mark_failed,
					job.request_id,
					"Unexpected Codex runner failure.",
				)
				continue
			finally:
				self._active_runner = None
				self._active_agent_tag = None

			if result.thread_id:
				await asyncio.to_thread(
					self._store.set_thread_id,
					result.thread_id,
					job.agent_tag,
				)
			if result.runtime_profile is not None:
				await asyncio.to_thread(
					self._store.set_runtime_profile,
					result.runtime_profile,
					job.agent_tag,
				)
			if result.returncode == 0 and result.final_message and result.thread_id:
				response = result.final_message[:MAX_RESPONSE_LENGTH]
				await asyncio.to_thread(self._store.mark_completed, job.request_id, response)
				LOGGER.info("codex_job_completed request_id=%s", job.request_id)
			else:
				await asyncio.to_thread(
					self._store.mark_failed,
					job.request_id,
					result.error or "Codex returned an incomplete result.",
				)
				LOGGER.error("codex_job_failed request_id=%s error_type=CodexRunResult")


def _parse_request_document(raw_message: str) -> dict[str, Any]:
	"""Parse one bounded WebSocket JSON object shared by worker request types."""
	maximum_document_bytes = (MAX_PROMPT_LENGTH * 4) + MAX_METADATA_BYTES + 1_024
	if len(raw_message.encode("utf-8")) > maximum_document_bytes:
		raise ValueError("Request document is too large.")
	try:
		message = json.loads(raw_message)
	except json.JSONDecodeError as error:
		raise ValueError("Request must be valid JSON.") from error
	if not isinstance(message, dict):
		raise ValueError("Request must be a JSON object.")
	return message


def _is_agent_thread_job(job: PromptJob) -> bool:
	"""Identify the narrow request class authorized to exchange workspace files."""
	try:
		metadata = json.loads(job.metadata_json)
	except json.JSONDecodeError:
		return False
	return (
		isinstance(metadata, dict)
		and metadata.get("source") == "discord_gateway"
		and metadata.get("command") == "agent_thread"
	)


def _request_id(message: dict[str, Any]) -> str:
	"""Validate and return the correlation identifier shared by worker requests."""
	request_id = message.get("request_id")
	if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
		raise ValueError("Request identifier is invalid.")
	return request_id


def _parse_prompt_message(
	message: dict[str, Any],
	default_agent_tag: str = "dev1",
) -> tuple[str, str, str, str]:
	"""Validate one JSON prompt envelope and canonicalize its metadata."""
	if message.get("type") != "prompt":
		raise ValueError("Request type must be prompt.")
	request_id = _request_id(message)
	agent_tag = message.get("agent_tag", default_agent_tag)
	if not isinstance(agent_tag, str):
		raise ValueError("Agent tag is invalid.")
	validated_agent_tag = validate_agent_tag(agent_tag)
	prompt = message.get("prompt")
	metadata = message.get("metadata", {})
	if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_LENGTH:
		raise ValueError("Prompt is invalid.")
	if not isinstance(metadata, dict):
		raise ValueError("Metadata must be an object.")
	metadata_json = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
	if len(metadata_json.encode("utf-8")) > MAX_METADATA_BYTES:
		raise ValueError("Metadata is too large.")
	return request_id, prompt, metadata_json, validated_agent_tag


def _parse_status_message(message: dict[str, Any]) -> tuple[str, str]:
	"""Validate a tag-scoped status request and return its correlation fields."""
	if message.get("type") != "status" or set(message) != {
		"type",
		"request_id",
		"agent_tag",
	}:
		raise ValueError("Status request is invalid.")
	agent_tag = message.get("agent_tag")
	if not isinstance(agent_tag, str):
		raise ValueError("Agent tag is invalid.")
	return _request_id(message), validate_agent_tag(agent_tag)


def _parse_agent_list_message(message: dict[str, Any]) -> str:
	"""Validate a content-free agent-list request and return its correlation ID."""
	if message.get("type") != "agent_list" or set(message) != {"type", "request_id"}:
		raise ValueError("Agent-list request is invalid.")
	return _request_id(message)


def _parse_agent_tag_message(message: dict[str, Any], request_type: str) -> tuple[str, str]:
	"""Validate one content-free delete or reset lifecycle request."""
	if message.get("type") != request_type or set(message) != {
		"type",
		"request_id",
		"agent_tag",
	}:
		raise ValueError("Agent lifecycle request is invalid.")
	agent_tag = message.get("agent_tag")
	if not isinstance(agent_tag, str):
		raise ValueError("Agent tag is invalid.")
	return _request_id(message), validate_agent_tag(agent_tag)


def _parse_agent_config_message(
	message: dict[str, Any],
) -> tuple[str, str, str, str]:
	"""Validate one explicit runtime-profile configuration request."""
	if message.get("type") != "agent_config" or set(message) != {
		"type",
		"request_id",
		"agent_tag",
		"model",
		"reasoning_level",
	}:
		raise ValueError("Agent configuration request is invalid.")
	agent_tag = message.get("agent_tag")
	model = message.get("model")
	reasoning_level = message.get("reasoning_level")
	if (
		not isinstance(agent_tag, str)
		or model not in {"gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra"}
		or reasoning_level not in {"low", "medium", "high"}
	):
		raise ValueError("Agent configuration values are invalid.")
	return _request_id(message), validate_agent_tag(agent_tag), model, reasoning_level


async def _send_job_result(websocket: WebSocket, service: WorkerService, request_id: str) -> None:
	"""Wait for the durable job and send its terminal response over the same socket."""
	while True:
		job = await service.get_job(request_id)
		if job is None:
			await websocket.send_json(
				{"type": "error", "request_id": request_id, "code": "job_missing"}
			)
			return
		if job.status == "completed" and job.response is not None:
			request_metadata = json.loads(job.metadata_json)
			response_document: dict[str, object] = {
					"type": "response",
					"request_id": request_id,
					"status": "completed",
					"answer": job.response,
					"metadata": {
						"conversation": "tagged",
						"agent_tag": job.agent_tag,
						"request": request_metadata,
					},
				}
			try:
				attachments = await service.output_attachments(job)
			except WorkspaceArtifactError:
				response_document["attachment_warning"] = (
					"Generated attachments were rejected by the file policy."
				)
			else:
				if attachments:
					response_document["attachments"] = [
						attachment.as_dict() for attachment in attachments
					]
			await websocket.send_json(response_document)
			return
		if job.status == "failed":
			await websocket.send_json(
				{
					"type": "error",
					"request_id": request_id,
					"code": "codex_failed",
					"message": "Codex could not complete the prompt.",
				}
			)
			return
		await asyncio.sleep(0.25)


def _default_agent_tag() -> str:
	"""Read and validate the default tag used when routing is omitted."""
	return validate_agent_tag(os.environ.get("CODEX_AGENT_TAG", "dev1"))


def create_app(
	store: WorkerStore | None = None,
	runner: Runner | None = None,
	workspaces_root: Path | None = None,
	agent_lifecycle: AgentLifecycle | None = None,
) -> Starlette:
	"""Create the private worker with environment-backed production dependencies."""
	default_agent_tag = _default_agent_tag()
	active_store = store or WorkerStore(
		Path(os.environ.get("CODEX_WORKER_DATABASE", "/var/lib/codex-worker/worker.db"))
	)
	active_workspaces_root = workspaces_root or Path(
		os.environ.get("CODEX_WORKSPACES_ROOT", "/workspaces")
	)
	if runner is None:
		registry = AgentRunnerRegistry(
			config_path=Path(
				os.environ.get("CODEX_AGENTS_CONFIG", "/app/config/config_agents.json")
			),
			workspaces_root=active_workspaces_root,
			template_source=Path(
				os.environ.get(
					"CODEX_WORKSPACE_TEMPLATE",
					"/opt/codex-workspace-template",
				)
			),
			executable=os.environ.get("CODEX_EXECUTABLE", "codex"),
			timeout_seconds=int(os.environ.get("CODEX_TURN_TIMEOUT_SECONDS", "780")),
			codex_home=Path(
				os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
			),
			runtime_config_loader=active_store.get_agent_runtime_config,
		)
		# Optional fixed-purpose agents should have complete persistent workspaces
		# immediately after the worker starts, before their first prompt arrives.
		registry.prepare_configured_workspaces()
		runner_resolver: RunnerResolver = registry.get
		agent_tag_lister: AgentTagLister = registry.list_tags
		active_agent_lifecycle: AgentLifecycle | None = registry
	else:
		runner_resolver = lambda _agent_tag: runner
		agent_tag_lister = lambda: (default_agent_tag,)
		active_agent_lifecycle = agent_lifecycle
	time_zone_name = os.environ.get("CODEX_WORKER_TIME_ZONE", "UTC")
	active_time_zone = timezone.utc if time_zone_name == "UTC" else ZoneInfo(time_zone_name)
	service = WorkerService(
		active_store,
		runner_resolver,
		agent_tag_lister,
		active_time_zone,
		default_agent_tag,
		WorkspaceArtifactStore(active_workspaces_root),
		active_agent_lifecycle,
	)

	@asynccontextmanager
	async def lifespan(_app: Starlette) -> AsyncIterator[None]:
		"""Start the queue consumer and close its resources during ASGI shutdown."""
		await service.start()
		try:
			yield
		finally:
			await service.stop()
			active_store.close()

	async def health(_request: Request) -> JSONResponse:
		"""Expose a non-secret readiness response for the Compose health check."""
		return JSONResponse(
			{
				"status": "ok",
				"conversation": "tagged",
				"default_agent_tag": service.default_agent_tag,
			}
		)

	async def stage_inbound_attachment(request: Request) -> JSONResponse:
		"""Accept one bounded raw file from the private Discord observer."""
		content_length = request.headers.get("content-length")
		if content_length is None or not content_length.isdecimal():
			return JSONResponse({"error": "Content length is required."}, status_code=411)
		if int(content_length) > MAX_ATTACHMENT_BYTES:
			return JSONResponse({"error": "Attachment is too large."}, status_code=413)
		content = bytearray()
		async for chunk in request.stream():
			content.extend(chunk)
			if len(content) > MAX_ATTACHMENT_BYTES:
				return JSONResponse({"error": "Attachment is too large."}, status_code=413)
		try:
			relative_path = await service.stage_attachment(
				request.query_params.get("agent_tag", ""),
				request.query_params.get("request_id", ""),
				request.query_params.get("attachment_id", ""),
				request.query_params.get("filename", ""),
				bytes(content),
			)
		except (AgentConfigError, WorkspaceArtifactError) as error:
			return JSONResponse({"error": str(error)}, status_code=400)
		return JSONResponse({"relative_path": relative_path}, status_code=201)

	async def retrieve_outbound_attachment(request: Request) -> Response:
		"""Return one digest-pinned worker upload to the private observer."""
		try:
			artifact, content = await service.read_output_attachment(
				request.query_params.get("agent_tag", ""),
				request.query_params.get("request_id", ""),
				request.query_params.get("filename", ""),
				request.query_params.get("sha256", ""),
			)
		except (AgentConfigError, WorkspaceArtifactError) as error:
			return JSONResponse({"error": str(error)}, status_code=400)
		return Response(
			content,
			media_type=artifact.content_type,
			headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
		)

	async def websocket_requests(websocket: WebSocket) -> None:
		"""Serve one bounded prompt or non-agent status request on a private socket."""
		await websocket.accept()
		try:
			raw_message = await websocket.receive_text()
			message = _parse_request_document(raw_message)
			if message.get("type") == "status":
				request_id, agent_tag = _parse_status_message(message)
				await websocket.send_json(
					{
						"type": "status",
						"request_id": request_id,
						"status": await service.status(agent_tag),
					}
				)
			elif message.get("type") == "agent_list":
				request_id = _parse_agent_list_message(message)
				await websocket.send_json(
					{
						"type": "agent_list",
						"request_id": request_id,
						"agent_tags": await service.agent_tags(),
					}
				)
			elif message.get("type") == "agent_config":
				request_id, agent_tag, model, reasoning_level = _parse_agent_config_message(
					message
				)
				await service.configure_agent(agent_tag, model, reasoning_level)
				await websocket.send_json(
					{
						"type": "agent_management",
						"request_id": request_id,
						"operation": "config",
						"agent_tag": agent_tag,
						"model": model,
						"reasoning_level": reasoning_level,
					}
				)
			elif message.get("type") in {"agent_reset", "agent_delete"}:
				operation = str(message["type"])[len("agent_"):]
				request_id, agent_tag = _parse_agent_tag_message(
					message,
					str(message["type"]),
				)
				if operation == "reset":
					await service.reset_agent(agent_tag)
				else:
					await service.delete_agent(agent_tag)
				await websocket.send_json(
					{
						"type": "agent_management",
						"request_id": request_id,
						"operation": operation,
						"agent_tag": agent_tag,
					}
				)
			else:
				request_id, prompt, metadata_json, agent_tag = _parse_prompt_message(
					message,
					service.default_agent_tag,
				)
				job = await service.submit(request_id, prompt, metadata_json, agent_tag)
				await websocket.send_json(
					{
						"type": "accepted",
						"request_id": request_id,
						"status": job.status,
						"metadata": {
							"conversation": "tagged",
							"agent_tag": job.agent_tag,
							"queue_position": await service.queue_position(request_id),
						},
					}
				)
				await _send_job_result(websocket, service, request_id)
		except (AgentConfigError, ValueError, WorkerStoreError) as error:
			await websocket.send_json(
				{"type": "error", "code": "invalid_request", "message": str(error)}
			)
		except WebSocketDisconnect:
			return
		finally:
			try:
				await websocket.close()
			except RuntimeError:
				pass

	return Starlette(
		debug=False,
		lifespan=lifespan,
		routes=[
			Route("/health", health, methods=["GET"]),
			Route("/artifacts/inbound", stage_inbound_attachment, methods=["POST"]),
			Route("/artifacts/outbound", retrieve_outbound_attachment, methods=["GET"]),
			WebSocketRoute("/ws", websocket_requests),
		],
	)
