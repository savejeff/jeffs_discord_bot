"""Bounded workspace attachment storage for Discord thread jobs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import zipfile

from codex_agent_worker.agent_config import validate_agent_tag

MAX_ATTACHMENT_COUNT = 3
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 20 * 1024 * 1024
INBOUND_ATTACHMENT_SUFFIXES = frozenset(
	{".txt", ".md", ".json", ".csv", ".log", ".pdf", ".jpg", ".jpeg", ".png"}
)
OUTBOUND_ATTACHMENT_SUFFIXES = INBOUND_ATTACHMENT_SUFFIXES | frozenset({".zip"})
ATTACHMENT_CONTENT_TYPES = {
	".txt": "text/plain",
	".md": "text/markdown",
	".json": "application/json",
	".csv": "text/csv",
	".log": "text/plain",
	".pdf": "application/pdf",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".png": "image/png",
	".zip": "application/zip",
}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ATTACHMENT_ID_PATTERN = re.compile(r"^[0-9]{1,32}$")
SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")


class WorkspaceArtifactError(RuntimeError):
	"""Identify an unsafe or unsupported workspace attachment operation."""


@dataclass(frozen=True, slots=True)
class WorkspaceArtifact:
	"""Describe one validated file available for Discord upload."""

	filename: str
	content_type: str
	size: int
	sha256: str

	def as_dict(self) -> dict[str, object]:
		"""Return the bounded JSON representation used by the worker protocol."""
		return {
			"filename": self.filename,
			"content_type": self.content_type,
			"size": self.size,
			"sha256": self.sha256,
		}


class WorkspaceArtifactStore:
	"""Own inbound and outbound temporary files beneath tagged workspaces."""

	def __init__(self, workspaces_root: Path) -> None:
		"""Resolve the immutable root used for all artifact path checks."""
		self._workspaces_root = workspaces_root.resolve()

	def stage_download(
		self,
		agent_tag: str,
		request_id: str,
		attachment_id: str,
		filename: str,
		content: bytes,
	) -> str:
		"""Atomically store one validated Discord attachment under tmp/download."""
		validated_tag = validate_agent_tag(agent_tag)
		_validate_request_id(request_id)
		if not ATTACHMENT_ID_PATTERN.fullmatch(attachment_id):
			raise WorkspaceArtifactError("Attachment identifier is invalid.")
		validated_filename = _validate_filename(filename, INBOUND_ATTACHMENT_SUFFIXES)
		if len(content) > MAX_ATTACHMENT_BYTES:
			raise WorkspaceArtifactError("Attachment is too large.")
		_validate_file_content(validated_filename, content, allow_zip=False)

		directory = self._safe_job_directory(
			validated_tag,
			"download",
			request_id,
			create=True,
		)
		stored_filename = f"{attachment_id}_{validated_filename}"
		target = directory / stored_filename
		if target.exists():
			if target.is_symlink() or target.read_bytes() != content:
				raise WorkspaceArtifactError("Attachment staging conflicts with an existing file.")
			return target.relative_to(self._workspace(validated_tag)).as_posix()

		existing_files = tuple(
			entry for entry in directory.iterdir() if entry.is_file() and not entry.is_symlink()
		)
		if len(existing_files) >= MAX_ATTACHMENT_COUNT:
			raise WorkspaceArtifactError("Too many attachments were supplied.")
		existing_size = sum(entry.stat().st_size for entry in existing_files)
		if existing_size + len(content) > MAX_TOTAL_ATTACHMENT_BYTES:
			raise WorkspaceArtifactError("Combined attachment size is too large.")

		temporary_name: str | None = None
		try:
			with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
				temporary.write(content)
				temporary_name = temporary.name
			os.replace(temporary_name, target)
		except OSError as error:
			if temporary_name is not None:
				Path(temporary_name).unlink(missing_ok=True)
			raise WorkspaceArtifactError("Could not store the attachment.") from error
		return target.relative_to(self._workspace(validated_tag)).as_posix()

	def prepare_upload_directory(self, agent_tag: str, request_id: str) -> Path:
		"""Create the request-specific tmp/upload directory before Codex starts."""
		validated_tag = validate_agent_tag(agent_tag)
		_validate_request_id(request_id)
		return self._safe_job_directory(validated_tag, "upload", request_id, create=True)

	def list_uploads(self, agent_tag: str, request_id: str) -> tuple[WorkspaceArtifact, ...]:
		"""Validate and describe files the agent selected for Discord delivery."""
		validated_tag = validate_agent_tag(agent_tag)
		_validate_request_id(request_id)
		directory = self._safe_job_directory(validated_tag, "upload", request_id)
		if not directory.exists():
			return ()
		entries = tuple(sorted(directory.iterdir(), key=lambda entry: entry.name))
		if any(entry.is_symlink() or not entry.is_file() for entry in entries):
			raise WorkspaceArtifactError("Upload directory contains an unsupported entry.")
		if len(entries) > MAX_ATTACHMENT_COUNT:
			raise WorkspaceArtifactError("Too many upload files were produced.")

		artifacts: list[WorkspaceArtifact] = []
		total_size = 0
		for entry in entries:
			filename = _validate_filename(entry.name, OUTBOUND_ATTACHMENT_SUFFIXES)
			size = entry.stat().st_size
			if size > MAX_ATTACHMENT_BYTES:
				raise WorkspaceArtifactError("An upload file is too large.")
			total_size += size
			if total_size > MAX_TOTAL_ATTACHMENT_BYTES:
				raise WorkspaceArtifactError("Combined upload size is too large.")
			content = entry.read_bytes()
			_validate_file_content(filename, content, allow_zip=True)
			artifacts.append(
				WorkspaceArtifact(
					filename=filename,
					content_type=_content_type(filename),
					size=size,
					sha256=hashlib.sha256(content).hexdigest(),
				)
			)
		return tuple(artifacts)

	def read_upload(
		self,
		agent_tag: str,
		request_id: str,
		filename: str,
		expected_sha256: str,
	) -> tuple[WorkspaceArtifact, bytes]:
		"""Read one upload only when it still matches its advertised digest."""
		validated_filename = _validate_filename(filename, OUTBOUND_ATTACHMENT_SUFFIXES)
		if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
			raise WorkspaceArtifactError("Upload digest is invalid.")
		artifacts = {
			artifact.filename: artifact
			for artifact in self.list_uploads(agent_tag, request_id)
		}
		artifact = artifacts.get(validated_filename)
		if artifact is None or artifact.sha256 != expected_sha256:
			raise WorkspaceArtifactError("Upload file is unavailable or changed.")
		directory = self._safe_job_directory(
			validate_agent_tag(agent_tag),
			"upload",
			request_id,
		)
		content = (directory / validated_filename).read_bytes()
		if len(content) != artifact.size:
			raise WorkspaceArtifactError("Upload file changed while being read.")
		return artifact, content

	def _workspace(self, agent_tag: str) -> Path:
		"""Resolve one tag without permitting a symlink or sibling traversal."""
		workspace = self._workspaces_root / agent_tag
		if workspace.is_symlink():
			raise WorkspaceArtifactError("Agent workspace is an unsafe symbolic link.")
		resolved = workspace.resolve()
		if resolved.parent != self._workspaces_root:
			raise WorkspaceArtifactError("Agent workspace resolved outside its root.")
		return resolved

	def _safe_job_directory(
		self,
		agent_tag: str,
		direction: str,
		request_id: str,
		create: bool = False,
	) -> Path:
		"""Resolve a fixed tmp direction and reject agent-created symlink escapes."""
		workspace = self._workspace(agent_tag)
		tmp_directory = workspace / "tmp"
		direction_directory = tmp_directory / direction
		job_directory = direction_directory / request_id
		for directory in (tmp_directory, direction_directory, job_directory):
			if directory.is_symlink():
				raise WorkspaceArtifactError("Artifact path contains a symbolic link.")
		if create:
			job_directory.mkdir(parents=True, exist_ok=True)
		resolved = job_directory.resolve()
		expected_parent = (workspace / "tmp" / direction).resolve()
		if resolved.parent != expected_parent:
			raise WorkspaceArtifactError("Artifact path resolved outside the workspace.")
		return resolved


def _validate_request_id(request_id: str) -> None:
	if not REQUEST_ID_PATTERN.fullmatch(request_id):
		raise WorkspaceArtifactError("Artifact request identifier is invalid.")


def _validate_filename(filename: str, allowed_suffixes: frozenset[str]) -> str:
	if (
		not SAFE_FILENAME_PATTERN.fullmatch(filename)
		or Path(filename).suffix.lower() not in allowed_suffixes
	):
		raise WorkspaceArtifactError("Attachment filename or type is unsupported.")
	return filename


def _validate_file_content(filename: str, content: bytes, allow_zip: bool) -> None:
	"""Require basic file signatures and reject renamed ZIP input without extracting it."""
	suffix = Path(filename).suffix.lower()
	zip_signature = content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
	if zip_signature and suffix != ".zip":
		raise WorkspaceArtifactError("A ZIP archive cannot be accepted under another name.")
	if suffix == ".zip":
		if not allow_zip or not zipfile.is_zipfile(BytesIO(content)):
			raise WorkspaceArtifactError("Upload ZIP file is invalid.")
		return
	if suffix == ".pdf" and not content.startswith(b"%PDF-"):
		raise WorkspaceArtifactError("PDF attachment signature is invalid.")
	if suffix == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
		raise WorkspaceArtifactError("PNG attachment signature is invalid.")
	if suffix in {".jpg", ".jpeg"} and not (
		content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")
	):
		raise WorkspaceArtifactError("JPEG attachment signature is invalid.")
	if suffix in {".txt", ".md", ".json", ".csv", ".log"}:
		try:
			content.decode("utf-8-sig")
		except UnicodeDecodeError as error:
			raise WorkspaceArtifactError("Text attachment is not valid UTF-8.") from error


def _content_type(filename: str) -> str:
	return ATTACHMENT_CONTENT_TYPES[Path(filename).suffix.lower()]
