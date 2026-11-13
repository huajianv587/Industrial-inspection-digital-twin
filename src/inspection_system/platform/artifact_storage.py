from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import threading
import time
from typing import BinaryIO, Iterator, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import uuid

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .settings import Settings


_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_SIZE = 1024 * 1024
_MISSING_OBJECT_CODES = {"404", "NoSuchKey", "NotFound"}


class ArtifactStorageError(RuntimeError):
    pass


class ArtifactNotFoundError(ArtifactStorageError):
    pass


class ArtifactIntegrityError(ArtifactStorageError):
    pass


class ArtifactStorage(Protocol):
    max_bytes: int
    def initialize(self) -> None: ...
    def put_bytes(self, run_id: str, digest: str, content: bytes) -> str: ...
    def put_file(self, run_id: str, digest: str, stream: BinaryIO, size: int) -> str: ...
    def read_bytes(self, reference: str) -> bytes: ...
    def iter_bytes(self, reference: str) -> Iterator[bytes]: ...
    def validate_reference(self, reference: str, run_id: str, digest: str) -> bool: ...
    def verify_artifact(self, reference: str, run_id: str, digest: str, size: int) -> bool: ...


@dataclass(frozen=True)
class LocalArtifactStorage:
    root: Path
    max_bytes: int

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _destination(self, run_id: str, digest: str) -> Path:
        if not _RUN_ID.fullmatch(run_id) or not _SHA256.fullmatch(digest):
            raise ArtifactStorageError("Invalid content-addressed artifact key.")
        return self.root / run_id / digest

    def put_bytes(self, run_id: str, digest: str, content: bytes) -> str:
        return self.put_file(run_id, digest, BytesIO(content), len(content))

    def put_file(self, run_id: str, digest: str, stream: BinaryIO, size: int) -> str:
        if size < 0 or size > self.max_bytes:
            raise ArtifactStorageError("Artifact exceeds the configured storage limit.")
        destination = self._destination(run_id, digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.parent / f".tmp-{uuid.uuid4().hex}"
        hasher = hashlib.sha256()
        written = 0
        try:
            with temp.open("xb") as target:
                while chunk := stream.read(_CHUNK_SIZE):
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise ArtifactStorageError(
                            "Artifact exceeds the configured storage limit.")
                    hasher.update(chunk)
                    target.write(chunk)
                target.flush()
            if written != size or hasher.hexdigest() != digest:
                raise ArtifactStorageError("Artifact content failed its size or SHA-256 check.")
            if destination.exists():
                self._verify_file(destination, digest, size)
                temp.unlink(missing_ok=True)
            else:
                temp.replace(destination)
        finally:
            temp.unlink(missing_ok=True)
        return str(destination)

    @staticmethod
    def _verify_file(path: Path, digest: str, size: int) -> None:
        if not path.is_file() or path.stat().st_size != size:
            raise ArtifactStorageError("Stored artifact size does not match its metadata.")
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ArtifactStorageError("Stored artifact failed its SHA-256 check.")

    def read_bytes(self, reference: str) -> bytes:
        path = Path(reference).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            raise ArtifactNotFoundError("Artifact content is unavailable.")
        if path.stat().st_size > self.max_bytes:
            raise ArtifactStorageError("Stored artifact exceeds the configured storage limit.")
        return path.read_bytes()

    def iter_bytes(self, reference: str) -> Iterator[bytes]:
        path = Path(reference).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            raise ArtifactNotFoundError("Artifact content is unavailable.")
        with path.open("rb") as stream:
            while chunk := stream.read(_CHUNK_SIZE):
                yield chunk

    def validate_reference(self, reference: str, run_id: str, digest: str) -> bool:
        try:
            path = Path(reference).resolve()
            return (path.is_relative_to(self.root.resolve())
                    and path.name == digest and path.parent.name == run_id)
        except (OSError, ValueError):
            return False

    def verify_artifact(self, reference: str, run_id: str, digest: str, size: int) -> bool:
        if not self.validate_reference(reference, run_id, digest):
            return False
        try:
            self._verify_file(Path(reference), digest, size)
        except (OSError, ArtifactStorageError):
            return False
        return True


@dataclass
class _AuthSession:
    access_token: str = field(repr=False)
    expires_at: float


class _SupabaseStorageAuth:
    def __init__(self, settings: Settings):
        self.url = (settings.supabase_url or "").rstrip("/")
        self.anon_key = settings.supabase_anon_key or ""
        self.email = settings.storage_user_email or ""
        self.password = settings.storage_user_password or ""
        self.timeout = settings.storage_auth_timeout_seconds
        self._session: _AuthSession | None = None
        self._lock = threading.Lock()

    def access_token(self) -> str:
        with self._lock:
            if self._session and time.monotonic() < self._session.expires_at - 60:
                return self._session.access_token
            self._session = self._sign_in()
            return self._session.access_token

    def _sign_in(self) -> _AuthSession:
        endpoint = f"{self.url}/auth/v1/token?grant_type=password"
        payload = json.dumps({"email": self.email, "password": self.password}).encode()
        request = Request(endpoint, data=payload, headers={
            "apikey": self.anon_key,
            "Content-Type": "application/json",
        })
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read(1024 * 1024))
        except HTTPError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage identity sign-in failed (HTTP {exc.code}).") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ArtifactStorageError(
                f"Supabase Storage identity is unavailable ({type(exc).__name__}).") from None
        token = result.get("access_token") if isinstance(result, dict) else None
        expires_in = result.get("expires_in") if isinstance(result, dict) else None
        user = result.get("user") if isinstance(result, dict) else None
        if (not isinstance(token, str) or not token
                or not isinstance(expires_in, (int, float)) or expires_in <= 60
                or not isinstance(user, dict) or not isinstance(user.get("id"), str)):
            raise ArtifactStorageError("Supabase Auth returned an invalid Storage session.")
        self.user_id = user["id"]
        return _AuthSession(token, time.monotonic() + float(expires_in))


class SupabaseS3ArtifactStorage:
    def __init__(self, settings: Settings):
        self.endpoint = settings.storage_endpoint or ""
        self.region = settings.storage_region or ""
        self.bucket = settings.storage_bucket
        self.max_bytes = settings.max_upload_bytes
        parsed = urlparse(settings.supabase_url or "")
        self.project_ref = (parsed.hostname or "").split(".")[0]
        self.auth = _SupabaseStorageAuth(settings)

    def initialize(self) -> None:
        try:
            self._client().head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            raise ArtifactStorageError(
                f"Supabase Storage access check failed ({code}).") from None
        except BotoCoreError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage is unavailable ({type(exc).__name__}).") from None

    def _client(self):
        token = self.auth.access_token()
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=self.region,
            aws_access_key_id=self.project_ref,
            aws_secret_access_key=self.auth.anon_key,
            aws_session_token=token,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def _key(self, run_id: str, digest: str) -> str:
        if not _RUN_ID.fullmatch(run_id) or not _SHA256.fullmatch(digest):
            raise ArtifactStorageError("Invalid content-addressed artifact key.")
        return f"{run_id}/{digest}"

    def _reference(self, key: str) -> str:
        return f"supabase-s3://{self.bucket}/{key}"

    def _parse_reference(self, reference: str) -> str:
        parsed = urlparse(reference)
        if parsed.scheme != "supabase-s3" or parsed.netloc != self.bucket:
            raise ArtifactStorageError("Artifact reference is not in the configured bucket.")
        key = parsed.path.lstrip("/")
        parts = key.split("/")
        if (len(parts) != 2 or not _RUN_ID.fullmatch(parts[0])
                or not _SHA256.fullmatch(parts[1])):
            raise ArtifactStorageError("Artifact reference is invalid.")
        return key

    def put_bytes(self, run_id: str, digest: str, content: bytes) -> str:
        return self.put_file(run_id, digest, BytesIO(content), len(content))

    def put_file(self, run_id: str, digest: str, stream: BinaryIO, size: int) -> str:
        if size < 0 or size > self.max_bytes:
            raise ArtifactStorageError("Artifact exceeds the configured storage limit.")
        key = self._key(run_id, digest)
        try:
            start = stream.tell()
            if not stream.seekable():
                raise ArtifactStorageError("Artifact stream must be seekable for integrity checks.")
            hasher = hashlib.sha256()
            read_size = 0
            while chunk := stream.read(_CHUNK_SIZE):
                read_size += len(chunk)
                if read_size > self.max_bytes:
                    raise ArtifactStorageError("Artifact exceeds the configured storage limit.")
                hasher.update(chunk)
            if read_size != size or hasher.hexdigest() != digest:
                raise ArtifactStorageError("Artifact content failed its size or SHA-256 check.")
            stream.seek(start)
        except (OSError, ValueError) as exc:
            raise ArtifactStorageError("Artifact stream could not be verified.") from exc

        try:
            client = self._client()
            try:
                existing = client.head_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "unknown")
                if code not in _MISSING_OBJECT_CODES:
                    raise
            else:
                if (existing.get("ContentLength") != size
                        or not self._verify_remote_content(client, key, digest, size)):
                    raise ArtifactStorageError(
                        "Existing content-addressed artifact failed its SHA-256 check.")
                return self._reference(key)
            client.upload_fileobj(
                stream,
                self.bucket,
                key,
                ExtraArgs={"ContentType": "application/octet-stream"},
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            raise ArtifactStorageError(f"Supabase Storage upload failed ({code}).") from None
        except S3UploadFailedError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage upload failed ({type(exc).__name__}).") from None
        except BotoCoreError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage upload failed ({type(exc).__name__}).") from None
        return self._reference(key)

    def _verify_remote_content(
        self, client, key: str, digest: str, expected_size: int,
    ) -> bool:
        try:
            response = client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            if code in _MISSING_OBJECT_CODES:
                return False
            raise ArtifactStorageError(
                f"Supabase Storage read failed ({code}).") from None
        except BotoCoreError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage read failed ({type(exc).__name__}).") from None

        body = response["Body"]
        hasher = hashlib.sha256()
        size = 0
        try:
            for chunk in body.iter_chunks(chunk_size=_CHUNK_SIZE):
                if chunk:
                    size += len(chunk)
                    if size > min(expected_size, self.max_bytes):
                        return False
                    hasher.update(chunk)
            return size == expected_size and hasher.hexdigest() == digest
        except BotoCoreError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage read failed ({type(exc).__name__}).") from None
        finally:
            body.close()

    def read_bytes(self, reference: str) -> bytes:
        key = self._parse_reference(reference)
        try:
            response = self._client().get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                content = body.read(self.max_bytes + 1)
            finally:
                body.close()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            if code in _MISSING_OBJECT_CODES:
                raise ArtifactNotFoundError("Artifact content is unavailable.") from None
            raise ArtifactStorageError(f"Supabase Storage read failed ({code}).") from None
        except BotoCoreError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage read failed ({type(exc).__name__}).") from None
        if len(content) > self.max_bytes:
            raise ArtifactStorageError("Stored artifact exceeds the configured storage limit.")
        expected_digest = key.rsplit("/", 1)[-1]
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise ArtifactIntegrityError("Stored artifact failed its SHA-256 check.")
        return content

    def iter_bytes(self, reference: str) -> Iterator[bytes]:
        key = self._parse_reference(reference)
        try:
            body = self._client().get_object(Bucket=self.bucket, Key=key)["Body"]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            if code in _MISSING_OBJECT_CODES:
                raise ArtifactNotFoundError("Artifact content is unavailable.") from None
            raise ArtifactStorageError(f"Supabase Storage read failed ({code}).") from None
        except BotoCoreError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage read failed ({type(exc).__name__}).") from None
        hasher = hashlib.sha256()
        size = 0
        try:
            for chunk in body.iter_chunks(chunk_size=_CHUNK_SIZE):
                if chunk:
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ArtifactStorageError(
                            "Stored artifact exceeds the configured storage limit.")
                    hasher.update(chunk)
                    yield chunk
            expected_digest = key.rsplit("/", 1)[-1]
            if hasher.hexdigest() != expected_digest:
                raise ArtifactIntegrityError("Stored artifact failed its SHA-256 check.")
        except BotoCoreError as exc:
            raise ArtifactStorageError(
                f"Supabase Storage read failed ({type(exc).__name__}).") from None
        finally:
            body.close()

    def validate_reference(self, reference: str, run_id: str, digest: str) -> bool:
        try:
            return self._parse_reference(reference) == self._key(run_id, digest)
        except ArtifactStorageError:
            return False

    def verify_artifact(self, reference: str, run_id: str, digest: str, size: int) -> bool:
        if not self.validate_reference(reference, run_id, digest):
            return False
        return self._verify_remote_content(
            self._client(), self._parse_reference(reference), digest, size)


def create_artifact_storage(settings: Settings) -> ArtifactStorage:
    if settings.artifact_storage_backend == "local":
        return LocalArtifactStorage(settings.artifact_dir, settings.max_upload_bytes)
    if settings.artifact_storage_backend == "supabase_s3":
        return SupabaseS3ArtifactStorage(settings)
    raise ValueError("Unsupported artifact storage backend.")
