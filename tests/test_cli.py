from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from inspection_system import cli
from inspection_system.platform.settings import Settings


class RuntimeValidationCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        identity_file = root / "id_ed25519"
        known_hosts_file = root / "known_hosts"
        identity_file.write_text("test-only identity", encoding="utf-8")
        known_hosts_file.write_text("cluster.example.test ssh-ed25519 test-key", encoding="utf-8")
        self.settings = Settings(
            database_url=(
                "postgresql://inspection_app:test@db.project-ref.supabase.co/postgres"
            ),
            environment="production",
            site_config_path=Path(__file__).parents[1] / "configs" / "site.json",
            artifact_storage_backend="supabase_s3",
            supabase_url="https://project-ref.supabase.co",
            supabase_anon_key="test-anon-key",
            storage_endpoint=(
                "https://project-ref.storage.supabase.co/storage/v1/s3"
            ),
            storage_region="ap-southeast-1",
            storage_user_email="storage@example.test",
            storage_user_password="never-print-this-test-secret",
            executor_mode="slurm",
            auth_mode="oidc",
            oidc_issuer="https://project-ref.supabase.co/auth/v1",
            oidc_audience="authenticated",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_identity_file=identity_file,
            slurm_known_hosts_file=known_hosts_file,
            slurm_remote_root="/remote/inspection-test",
            slurm_source="isaac_sim",
            isaac_sim_version="4.5.0",
            isaac_robot_usd_path="/cluster/assets/go2.usd",
            isaac_sim_python="/opt/isaac-sim/python.sh",
            isaac_sim_adapter="inspection_system.adapters.site:create_adapter",
            isaac_model_manifest_path="/cluster/models/manifest.json",
            isaac_model_manifest_sha256="0" * 64,
            isaac_model_artifact_sha256="1" * 64,
            isaac_model_id="inspection-baseline",
            isaac_model_version="1.2.3",
            isaac_slurm_gres="gpu:1",
        )

    def test_valid_production_configuration_passes_without_printing_secrets(self):
        stdout = StringIO()
        with patch("inspection_system.cli.Settings.from_env", return_value=self.settings), \
                patch("inspection_system.cli.validate_supabase_auth_policy") as auth_policy, \
                redirect_stdout(stdout):
            result = cli.main(["validate-runtime"])

        self.assertEqual(result, 0)
        self.assertIn("环境=production", stdout.getvalue())
        self.assertIn("执行器=slurm", stdout.getvalue())
        self.assertIn("航点=3", stdout.getvalue())
        self.assertNotIn("never-print-this-test-secret", stdout.getvalue())
        auth_policy.assert_called_once_with("https://project-ref.supabase.co", "test-anon-key")

    def test_invalid_production_executor_fails_closed_without_printing_secrets(self):
        invalid = Settings(
            database_url=self.settings.database_url,
            environment="production",
            executor_mode="offline",
            storage_user_password="never-print-this-test-secret",
        )
        stderr = StringIO()
        with patch("inspection_system.cli.Settings.from_env", return_value=invalid), \
                patch("inspection_system.cli.validate_supabase_auth_policy") as auth_policy, \
                redirect_stderr(stderr):
            result = cli.main(["validate-runtime"])

        self.assertEqual(result, 2)
        self.assertIn("Production requires INSPECTION_EXECUTOR=slurm", stderr.getvalue())
        self.assertNotIn("never-print-this-test-secret", stderr.getvalue())
        auth_policy.assert_not_called()

    def test_auth_policy_command_checks_project_binding_before_http(self):
        stdout = StringIO()
        with patch("inspection_system.cli.Settings.from_env", return_value=self.settings), \
                patch("inspection_system.cli.validate_supabase_auth_policy") as auth_policy, \
                redirect_stdout(stdout):
            result = cli.main(["validate-auth-policy"])

        self.assertEqual(result, 0)
        auth_policy.assert_called_once_with("https://project-ref.supabase.co", "test-anon-key")
        self.assertIn("公开注册已关闭", stdout.getvalue())

    def test_runtime_preflight_fails_when_remote_auth_policy_is_open(self):
        stderr = StringIO()
        with patch("inspection_system.cli.Settings.from_env", return_value=self.settings), \
                patch("inspection_system.cli.validate_supabase_auth_policy",
                      side_effect=ValueError("Production requires public Supabase sign-ups to be disabled.")), \
                redirect_stderr(stderr):
            result = cli.main(["validate-runtime"])

        self.assertEqual(result, 2)
        self.assertIn("public Supabase sign-ups to be disabled", stderr.getvalue())
        self.assertNotIn("test-anon-key", stderr.getvalue())

    def test_preflight_rejects_runtime_database_from_another_project(self):
        settings = replace(
            self.settings,
            database_url=(
                "postgresql://inspection_app:test@db.other-ref.supabase.co/postgres"
            ),
        )
        with self.assertRaisesRegex(ValueError, "must target the project"):
            settings.validate()

    def test_production_isaac_requires_complete_model_metadata(self):
        settings = replace(self.settings, isaac_model_manifest_path=None)
        with self.assertRaisesRegex(ValueError, "ISAAC_MODEL_MANIFEST_PATH"):
            settings.validate()

    def test_preflight_rejects_oidc_issuer_from_another_project(self):
        settings = replace(
            self.settings,
            oidc_issuer="https://other-ref.supabase.co/auth/v1",
        )
        with self.assertRaisesRegex(ValueError, "Auth issuer for the configured"):
            settings.validate()

    def test_pooler_username_binds_runtime_database_to_project(self):
        settings = replace(
            self.settings,
            database_url=(
                "postgresql://inspection_app.project-ref:test@"
                "aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
            ),
        )
        settings.validate()

    def test_migration_owner_url_must_match_configured_project(self):
        with self.assertRaisesRegex(ValueError, "must target the project"):
            self.settings.validate_supabase_project_binding(
                database_url=(
                    "postgresql://postgres:owner@db.other-ref.supabase.co/postgres"
                ),
                required=True,
            )


if __name__ == "__main__":
    unittest.main()
