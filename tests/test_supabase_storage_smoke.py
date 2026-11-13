from __future__ import annotations

from hashlib import sha256
import unittest
from unittest.mock import MagicMock, patch

from inspection_system.platform.artifact_storage import ArtifactStorageError
from inspection_system.platform.settings import Settings
from scripts import smoke_supabase_storage


class _SmokeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.initialize_calls = 0
        self.put_calls = 0
        self.verify_calls = 0
        self.verified = True

    def initialize(self):
        self.initialize_calls += 1

    def put_bytes(self, run_id: str, digest: str, content: bytes) -> str:
        self.put_calls += 1
        if sha256(content).hexdigest() != digest:
            raise ArtifactStorageError("unexpected digest")
        key = f"supabase-s3://inspection-artifacts/{run_id}/{digest}"
        existing = self.objects.get(key)
        if existing is not None and existing != content:
            raise ArtifactStorageError("immutable smoke object content changed")
        self.objects[key] = content
        return key

    def read_bytes(self, reference: str) -> bytes:
        return self.objects[reference]

    def verify_artifact(self, reference: str, run_id: str, digest: str, size: int) -> bool:
        self.verify_calls += 1
        content = self.objects.get(reference, b"")
        return self.verified and len(content) == size and sha256(content).hexdigest() == digest


class SupabaseStorageSmokeTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            database_url="postgresql://inspection_app.p-ref@aws-0-ap-southeast-1.pooler.supabase.com/postgres",
            environment="production",
            artifact_storage_backend="supabase_s3",
            supabase_url="https://p-ref.supabase.co",
            supabase_anon_key="public-test-key",
            storage_endpoint="https://p-ref.storage.supabase.co/storage/v1/s3",
            storage_region="ap-southeast-1",
            storage_user_email="storage@example.test",
            storage_user_password="not-a-real-secret",
            executor_mode="slurm",
            slurm_source="isaac_sim",
        )
        self.storage = _SmokeStorage()

    @patch("scripts.smoke_supabase_storage.SupabaseS3ArtifactStorage")
    @patch.object(Settings, "from_env")
    def test_upload_download_and_repeat_use_one_stable_marker(self, from_env, storage_factory):
        settings = MagicMock(wraps=self.settings)
        from_env.return_value = settings
        storage_factory.return_value = self.storage

        result = smoke_supabase_storage.run_smoke()

        self.assertEqual(result["storage_smoke"], "passed")
        self.assertEqual(result["idempotent_reuse"], "verified")
        self.assertEqual(self.storage.initialize_calls, 1)
        self.assertEqual(self.storage.put_calls, 2)
        self.assertEqual(self.storage.verify_calls, 1)
        self.assertEqual(len(self.storage.objects), 1)
        self.assertEqual(
            next(iter(self.storage.objects.values())),
            smoke_supabase_storage.SMOKE_CONTENT,
        )
        settings.validate_database.assert_called_once_with()
        settings.validate_supabase_project_binding.assert_called_once_with(required=True)
        settings.validate_artifact_storage.assert_called_once_with()

    @patch("scripts.smoke_supabase_storage.SupabaseS3ArtifactStorage")
    @patch.object(Settings, "from_env")
    def test_storage_validation_fails_before_any_object_io(self, from_env, storage_factory):
        settings = Settings(
            database_url="postgresql://inspection_app.p-ref@aws-0-ap-southeast-1.pooler.supabase.com/postgres",
            environment="production",
            artifact_storage_backend="local",
            supabase_url="https://p-ref.supabase.co",
        )
        settings_mock = MagicMock(wraps=settings)
        from_env.return_value = settings_mock

        with self.assertRaisesRegex(ValueError, "ARTIFACT_STORAGE_BACKEND=supabase_s3"):
            smoke_supabase_storage.run_smoke()

        settings_mock.validate_database.assert_called_once_with()
        settings_mock.validate_supabase_project_binding.assert_called_once_with(required=True)
        settings_mock.validate_artifact_storage.assert_called_once_with()
        storage_factory.assert_not_called()

    @patch("scripts.smoke_supabase_storage.SupabaseS3ArtifactStorage")
    @patch.object(Settings, "from_env")
    def test_failed_remote_integrity_check_fails_the_smoke(self, from_env, storage_factory):
        from_env.return_value = self.settings
        self.storage.verified = False
        storage_factory.return_value = self.storage

        with self.assertRaisesRegex(ArtifactStorageError, "SHA-256 verification"):
            smoke_supabase_storage.run_smoke()


if __name__ == "__main__":
    unittest.main()
