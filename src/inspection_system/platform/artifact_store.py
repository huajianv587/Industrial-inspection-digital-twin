from __future__ import annotations

import hashlib
import re
import uuid
from typing import BinaryIO
from sqlalchemy import select
from sqlalchemy.orm import Session
from .artifact_storage import ArtifactStorage
from .entities import ArtifactRecord


ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,255}$")
ARTIFACT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def store_artifact_bytes(
    session: Session,
    storage: ArtifactStorage,
    run_id: str,
    name: str,
    content: bytes,
    source: str,
) -> ArtifactRecord:
    if not ARTIFACT_NAME_RE.fullmatch(name) or name in {".", ".."}:
        raise ValueError("Invalid artifact name.")
    existing = session.scalar(select(ArtifactRecord).where(
        ArtifactRecord.run_id == run_id, ArtifactRecord.name == name))
    digest = hashlib.sha256(content).hexdigest()
    if existing:
        if existing.sha256 == digest and existing.size_bytes == len(content):
            return existing
        raise ValueError(f"Artifact {name} is immutable and already has different content.")
    storage_path = storage.put_bytes(run_id, digest, content)
    record = ArtifactRecord(
        artifact_id=uuid.uuid4().hex,
        run_id=run_id,
        name=name,
        sha256=digest,
        size_bytes=len(content),
        storage_path=storage_path,
        source=source,
    )
    session.add(record)
    session.flush()
    return record


def store_artifact_file(
    session: Session,
    storage: ArtifactStorage,
    run_id: str,
    name: str,
    stream: BinaryIO,
    digest: str,
    size: int,
    source: str,
) -> ArtifactRecord:
    if not ARTIFACT_NAME_RE.fullmatch(name) or name in {".", ".."}:
        raise ValueError("Invalid artifact name.")
    if (not isinstance(digest, str) or not ARTIFACT_SHA256_RE.fullmatch(digest)
            or isinstance(size, bool)
            or not isinstance(size, int) or size < 0):
        raise ValueError("Invalid artifact integrity metadata.")
    existing = session.scalar(select(ArtifactRecord).where(
        ArtifactRecord.run_id == run_id, ArtifactRecord.name == name))
    if existing:
        if existing.sha256 == digest and existing.size_bytes == size:
            return existing
        raise ValueError(f"Artifact {name} is immutable and already has different content.")
    storage_path = storage.put_file(run_id, digest, stream, size)
    record = ArtifactRecord(
        artifact_id=uuid.uuid4().hex,
        run_id=run_id,
        name=name,
        sha256=digest,
        size_bytes=size,
        storage_path=storage_path,
        source=source,
    )
    session.add(record)
    session.flush()
    return record
