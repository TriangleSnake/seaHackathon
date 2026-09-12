from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactConflictError(FileExistsError):
    """Raised when an immutable artifact version already has different content."""


class FileArtifactPublisher:
    """Publish deterministic, immutable JSON artifacts into one configured root."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def publish(self, version: str, artifact: Mapping[str, Any]) -> str:
        if not isinstance(version, str) or not _SAFE_VERSION.fullmatch(version):
            raise ValueError(f"Unsafe artifact version: {version!r}")
        if artifact.get("version") != version:
            raise ValueError("Artifact version must match its published filename")

        payload = (
            json.dumps(
                dict(artifact),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._root / f"{version}.json"

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{version}.", suffix=".tmp", dir=self._root
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o644)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())

            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                try:
                    existing = self._read_existing_regular_file(target)
                except OSError as read_error:
                    raise ArtifactConflictError(
                        f"Artifact version already exists and cannot be compared: {version}"
                    ) from read_error
                if existing != payload:
                    raise ArtifactConflictError(
                        f"Artifact version already exists with different content: {version}"
                    ) from exc
            else:
                self._fsync_root()

            return str(target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_existing_regular_file(target: Path) -> bytes:
        if not stat.S_ISREG(target.lstat().st_mode):
            raise OSError("Existing artifact is not a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("Existing artifact is not a regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(descriptor)

    def _fsync_root(self) -> None:
        descriptor = os.open(self._root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
