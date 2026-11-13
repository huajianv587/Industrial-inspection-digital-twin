from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import math
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError

from inspection_system.platform.artifact_storage import (
    ArtifactStorageError,
    LocalArtifactStorage,
    SupabaseS3ArtifactStorage,
)
from inspection_system.platform.settings import Settings
from scripts.validate_supabase_storage import migration_is_applied


class StorageMigrationValidationTests(unittest.TestCase):
    def test_storage_validation_accepts_descendant_revision_and_rejects_older_schema(self):
        self.assertTrue(migration_is_applied("20261020_0005"))
        self.assertFalse(migration_is_applied("20261020_0003"))
        self.assertFalse(migration_is_applied(None))


class _Body:
    def __init__(self, content: bytes):
        self.content = BytesIO(content)
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self.content.read(size)

    def iter_chunks(self, chunk_size: int):
        while chunk := self.content.read(chunk_size):
            yield chunk

    def close(self) -> None:
        self.closed = True


class _S3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.head_bucket_calls: list[str] = []
        self.upload_calls = 0
        self.next_head_error: str | None = None
        self.next_get_error: str | None = None
        self.last_body: _Body | None = None

    @staticmethod
    def _error(code: str, operation: str) -> ClientError:
        return ClientError({
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {"HTTPStatusCode": 404 if code == "404" else 403},
        }, operation)

    def head_bucket(self, *, Bucket: str) -> dict[str, object]:
        self.head_bucket_calls.append(Bucket)
        return {}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if self.next_head_error:
            code, self.next_head_error = self.next_head_error, None
            raise self._error(code, "HeadObject")
        item = self.objects.get((Bucket, Key))
        if item is None:
            raise self._error("404", "HeadObject")
        content = item["content"]
        return {"ContentLength": len(content)}

    def upload_fileobj(self, stream, bucket: str, key: str, *, ExtraArgs):
        self.upload_calls += 1
        content = stream.read()
        self.objects[(bucket, key)] = {
            "content": content,
        }

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if self.next_get_error:
            code, self.next_get_error = self.next_get_error, None
            raise self._error(code, "GetObject")
        item = self.objects.get((Bucket, Key))
        if item is None:
            raise self._error("NoSuchKey", "GetObject")
        self.last_body = _Body(item["content"])
        return {"Body": self.last_body}


class _Auth:
    user_id = "storage-user"
    anon_key = "public-test-key"

    def access_token(self) -> str:
        return "test-token"


class ArtifactStorageTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            supabase_url="https://project-ref.supabase.co",
            supabase_anon_key="public-test-key",
            storage_endpoint="https://project-ref.storage.supabase.co/storage/v1/s3",
            storage_region="ap-southeast-1",
            storage_user_email="storage@example.test",
            storage_user_password="not-a-real-secret",
            max_upload_bytes=64,
        )
        self.storage = SupabaseS3ArtifactStorage(self.settings)
        self.client = _S3Client()
        self.storage.auth = _Auth()
        self.storage._client = lambda: self.client

    def test_initialization_checks_configured_bucket(self):
        self.storage.initialize()
        self.assertEqual(self.client.head_bucket_calls, ["inspection-artifacts"])

    def test_s3_client_uses_only_required_sdk_checksum_headers(self):
        storage = SupabaseS3ArtifactStorage(self.settings)
        storage.auth = _Auth()
        with patch("inspection_system.platform.artifact_storage.boto3.client") as client:
            storage._client()
        config = client.call_args.kwargs["config"]
        self.assertEqual(config.request_checksum_calculation, "when_required")
        self.assertEqual(config.response_checksum_validation, "when_required")

    def test_s3_upload_is_content_verified_and_idempotent_without_custom_metadata(self):
        content = b"validated artifact"
        digest = sha256(content).hexdigest()
        reference = self.storage.put_bytes("RUN-123", digest, content)
        self.assertEqual(reference, f"supabase-s3://inspection-artifacts/RUN-123/{digest}")
        self.assertEqual(self.client.upload_calls, 1)
        self.assertEqual(
            self.client.objects[("inspection-artifacts", f"RUN-123/{digest}")]["content"],
            content,
        )

        repeated = self.storage.put_bytes("RUN-123", digest, content)
        self.assertEqual(repeated, reference)
        self.assertEqual(self.client.upload_calls, 1)

    def test_invalid_content_never_reaches_object_storage(self):
        with self.assertRaisesRegex(ArtifactStorageError, "SHA-256"):
            self.storage.put_file("RUN-123", "0" * 64, BytesIO(b"wrong"), 5)
        self.assertEqual(self.client.upload_calls, 0)

    def test_size_limit_is_checked_before_upload(self):
        with self.assertRaisesRegex(ArtifactStorageError, "storage limit"):
            self.storage.put_bytes("RUN-123", sha256(b"x" * 65).hexdigest(), b"x" * 65)
        self.assertEqual(self.client.upload_calls, 0)

    def test_corrupt_existing_content_addressed_object_is_not_overwritten(self):
        content = b"artifact"
        digest = sha256(content).hexdigest()
        self.client.objects[("inspection-artifacts", f"RUN-123/{digest}")] = {
            "content": b"corrupt!",
        }
        with self.assertRaisesRegex(ArtifactStorageError, "SHA-256 check"):
            self.storage.put_bytes("RUN-123", digest, content)
        self.assertEqual(self.client.upload_calls, 0)

    def test_verify_artifact_hashes_remote_bytes_instead_of_trusting_size(self):
        content = b"same-size"
        digest = sha256(content).hexdigest()
        reference = self.storage.put_bytes("RUN-123", digest, content)
        object_key = ("inspection-artifacts", f"RUN-123/{digest}")
        self.assertTrue(self.storage.verify_artifact(
            reference, "RUN-123", digest, len(content)))

        self.client.objects[object_key]["content"] = b"tampered!"
        self.assertFalse(self.storage.verify_artifact(
            reference, "RUN-123", digest, len(content)))

    def test_reads_check_the_content_digest(self):
        content = b"readable artifact"
        digest = sha256(content).hexdigest()
        reference = self.storage.put_bytes("RUN-123", digest, content)
        self.assertEqual(self.storage.read_bytes(reference), content)

        self.client.objects[("inspection-artifacts", f"RUN-123/{digest}")]["content"] = b"corrupt"
        with self.assertRaisesRegex(ArtifactStorageError, "SHA-256"):
            self.storage.read_bytes(reference)

    def test_streaming_read_closes_body_and_rejects_corruption(self):
        content = b"streamed artifact"
        digest = sha256(content).hexdigest()
        reference = self.storage.put_bytes("RUN-123", digest, content)
        self.assertEqual(b"".join(self.storage.iter_bytes(reference)), content)
        self.assertTrue(self.client.last_body.closed)

        self.client.objects[("inspection-artifacts", f"RUN-123/{digest}")]["content"] = b"broken"
        with self.assertRaisesRegex(ArtifactStorageError, "SHA-256"):
            b"".join(self.storage.iter_bytes(reference))
        self.assertTrue(self.client.last_body.closed)

    def test_access_denied_is_not_reported_as_missing_content(self):
        self.client.next_get_error = "AccessDenied"
        with self.assertRaisesRegex(ArtifactStorageError, "AccessDenied"):
            self.storage.verify_artifact(
                f"supabase-s3://inspection-artifacts/RUN-123/{'a' * 64}",
                "RUN-123", "a" * 64, 1,
            )

    def test_local_storage_validates_digest_and_reference_scope(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as root:
            storage = LocalArtifactStorage(__import__("pathlib").Path(root), 64)
            storage.initialize()
            content = b"local test artifact"
            digest = sha256(content).hexdigest()
            reference = storage.put_bytes("RUN-123", digest, content)
            self.assertTrue(storage.verify_artifact(reference, "RUN-123", digest, len(content)))
            self.assertFalse(storage.validate_reference(reference, "RUN-OTHER", digest))
            with self.assertRaisesRegex(ArtifactStorageError, "SHA-256"):
                storage.put_bytes("RUN-123", "0" * 64, content)


class StorageSettingsTests(unittest.TestCase):
    def _settings(self, endpoint: str) -> Settings:
        return Settings(
            database_url="sqlite://",
            environment="test",
            auth_mode="development",
            artifact_storage_backend="supabase_s3",
            supabase_url="https://project-ref.supabase.co",
            supabase_anon_key="public-test-key",
            storage_endpoint=endpoint,
            storage_region="ap-southeast-1",
            storage_user_email="storage@example.test",
            storage_user_password="not-a-real-secret",
        )

    def test_valid_s3_endpoint_is_accepted(self):
        self._settings(
            "https://project-ref.storage.supabase.co/storage/v1/s3").validate()

    def test_wrong_project_or_missing_s3_path_is_rejected(self):
        for endpoint in (
            "https://other-ref.storage.supabase.co/storage/v1/s3",
            "https://project-ref.storage.supabase.co",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(ValueError, "S3 endpoint"):
                    self._settings(endpoint).validate()

    def test_bucket_must_match_the_migration_managed_bucket(self):
        settings = replace(self._settings(
            "https://project-ref.storage.supabase.co/storage/v1/s3"),
            storage_bucket="other-bucket",
        )
        with self.assertRaisesRegex(ValueError, "migration-managed bucket"):
            settings.validate()

    def test_upload_limit_cannot_exceed_the_bucket_limit(self):
        settings = replace(self._settings(
            "https://project-ref.storage.supabase.co/storage/v1/s3"),
            max_upload_bytes=200 * 1024 * 1024 + 1,
        )
        with self.assertRaisesRegex(ValueError, "200 MiB"):
            settings.validate()

    def test_storage_auth_timeout_must_be_finite_and_positive(self):
        base = self._settings("https://project-ref.storage.supabase.co/storage/v1/s3")
        for timeout in (0, -1, math.nan, math.inf):
            with self.subTest(timeout=timeout):
                settings = replace(base, storage_auth_timeout_seconds=timeout)
                with self.assertRaisesRegex(ValueError, "SUPABASE_STORAGE_AUTH_TIMEOUT_SECONDS"):
                    settings.validate()


if __name__ == "__main__":
    unittest.main()
