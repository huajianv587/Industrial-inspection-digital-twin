from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException

from inspection_system.platform.auth import Actor, actor_from_request, require_roles
from inspection_system.platform.result_bundle import (
    BundleError,
    extract_result_bundle,
    read_result_bundle,
)
from inspection_system.platform.slurm import SlurmClient, SlurmError, SlurmResultError
from inspection_system.platform.settings import Settings


class AuthRoleTests(unittest.TestCase):
    @staticmethod
    def actor_for_claims(claims):
        settings = Settings(
            auth_mode="oidc",
            oidc_issuer="https://auth.example.test",
            oidc_audience="authenticated",
        )
        request = SimpleNamespace(app=SimpleNamespace(
            state=SimpleNamespace(settings=settings)))
        jwk_client = SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(
            key="test-signing-key"))
        with patch("inspection_system.platform.auth._jwk_client", return_value=jwk_client), \
                patch("inspection_system.platform.auth.jwt.decode", return_value=claims):
            return actor_from_request(request, authorization="Bearer test-token")

    def test_untrusted_role_claims_do_not_assign_application_access(self):
        with self.assertRaises(HTTPException) as raised:
            self.actor_for_claims({
                "sub": "user-1",
                "roles": ["admin"],
                "realm_access": {"roles": ["admin"]},
                "user_metadata": {"roles": ["admin"]},
            })
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "APPLICATION_ROLE_REQUIRED")

    def test_trusted_app_metadata_roles_are_applied(self):
        actor = self.actor_for_claims({
            "sub": "user-2",
            "app_metadata": {"roles": ["reviewer"]},
            "roles": ["admin"],
        })
        self.assertEqual(actor.role, "reviewer")
        self.assertEqual(actor.effective_roles, frozenset({"reviewer"}))

    def test_multiple_trusted_roles_grant_their_combined_permissions(self):
        actor = self.actor_for_claims({
            "sub": "user-6",
            "app_metadata": {"roles": ["operator", "reviewer"]},
        })

        self.assertEqual(actor.role, "reviewer")
        self.assertEqual(actor.effective_roles, frozenset({"operator", "reviewer"}))
        self.assertIs(require_roles("admin", "operator")(actor=actor), actor)
        self.assertIs(require_roles("admin", "reviewer")(actor=actor), actor)
        with self.assertRaises(HTTPException) as raised:
            require_roles("admin")(actor=actor)
        self.assertEqual(raised.exception.detail["code"], "INSUFFICIENT_ROLE")

    def test_malformed_or_missing_app_metadata_roles_are_denied(self):
        for metadata in ({"roles": "admin"}, {}, None):
            with self.subTest(metadata=metadata):
                with self.assertRaises(HTTPException) as raised:
                    self.actor_for_claims({
                        "sub": "user-3",
                        "app_metadata": metadata,
                    })
                self.assertEqual(raised.exception.status_code, 403)
                self.assertEqual(raised.exception.detail["code"], "APPLICATION_ROLE_REQUIRED")

    def test_insufficient_endpoint_role_has_distinct_error_code(self):
        with self.assertRaises(HTTPException) as raised:
            require_roles("admin")(Actor("user-5", "viewer"))
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "INSUFFICIENT_ROLE")

    def test_explicit_viewer_role_is_retained(self):
        actor = self.actor_for_claims({
            "sub": "user-4",
            "app_metadata": {"roles": ["viewer"]},
        })
        self.assertEqual(actor.role, "viewer")


class SlurmStateMappingTests(unittest.TestCase):
    def test_scheduler_states_map_to_platform_states(self):
        cases = {
            "PENDING": "PENDING",
            "CONFIGURING": "PENDING",
            "RUNNING": "RUNNING",
            "COMPLETING": "RUNNING",
            "COMPLETED": "COMPLETED",
            "CANCELLED by 1234": "CANCELLED",
            "TIMEOUT": "TIMEOUT",
            "OUT_OF_MEMORY": "FAILED",
            "NODE_FAIL": "FAILED",
            "SOMETHING_NEW": "UNKNOWN",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(SlurmClient._map_state(source), expected)

    def test_stale_job_lookup_batches_names_and_merges_scheduler_states(self):
        first = "RUN-0000000000000001"
        second = "RUN-0000000000000002"
        outputs = iter([
            f"101|insp-{first.lower()}|RUNNING\n",
            f"101|insp-{first.lower()}|RUNNING\n"
            f"102|insp-{second.lower()}|COMPLETED\n",
        ])
        commands = []
        client = object.__new__(SlurmClient)
        client._remote = lambda command: (commands.append(command), next(outputs))[1]

        found = SlurmClient.find_jobs_for_runs(client, [first, second])

        self.assertEqual(found, {
            first: {"101": "RUNNING"},
            second: {"102": "COMPLETED"},
        })
        self.assertEqual(len(commands), 2)
        self.assertIn(first.lower(), commands[0])
        self.assertIn(second.lower(), commands[0])
        self.assertIn("--name=", commands[1])

    def test_stale_job_lookup_fails_closed_when_accounting_is_unavailable(self):
        run_id = "RUN-0000000000000001"
        client = object.__new__(SlurmClient)
        outputs = iter([""])

        def remote(_command):
            try:
                return next(outputs)
            except StopIteration as exc:
                raise SlurmError("sacct unavailable") from exc

        client._remote = remote
        with self.assertRaisesRegex(SlurmError, "cannot be retried safely"):
            client.find_jobs_for_runs([run_id])


class ResultBundleTests(unittest.TestCase):
    @staticmethod
    def _write_bundle(path: Path, contents: dict[str, bytes]) -> None:
        manifest = {
            "schema_version": 1,
            "run_id": "RUN-0000000000000001",
            "source": "isaac_sim",
            "software_version": "isaac-sim/1.2.3",
            "config_sha256": "0" * 64,
            "artifacts": [{
                "name": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            } for name, content in contents.items()],
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in contents.items():
                archive.writestr(name, content)
            archive.writestr("result_manifest.json", json.dumps(manifest))

    def test_bundle_rejects_artifact_checksum_mismatch(self):
        contents = {
            "inspection_run.json": json.dumps({"run_id": "RUN-0000000000000001"}).encode(),
            "inspection_report.md": b"verified report",
            "work_orders.json": b"[]",
        }
        manifest = {
            "schema_version": 1,
            "run_id": "RUN-0000000000000001",
            "source": "synthetic_simulation",
            "artifacts": [{"name": name,
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "size_bytes": len(content)} for name, content in contents.items()],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "bundle.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("result_manifest.json", json.dumps(manifest))
                for name, content in contents.items():
                    archive.writestr(name, b"tampered" if name == "work_orders.json" else content)
            with self.assertRaisesRegex(BundleError, "(size|checksum) mismatch"):
                read_result_bundle(archive_path)

    def test_extraction_returns_bounded_files_for_optional_binary_artifacts(self):
        contents = {
            "inspection_run.json": json.dumps({
                "run_id": "RUN-0000000000000001",
            }).encode(),
            "inspection_report.md": b"run RUN-0000000000000001",
            "work_orders.json": b"[]",
            "camera_frame.bin": bytes(range(256)) * 8192,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "result_bundle.zip"
            self._write_bundle(archive_path, contents)
            manifest, inspection_run, artifacts = extract_result_bundle(
                archive_path, root / "staged")

            self.assertEqual(manifest["run_id"], "RUN-0000000000000001")
            self.assertEqual(inspection_run["run_id"], "RUN-0000000000000001")
            self.assertIsInstance(artifacts["camera_frame.bin"], Path)
            self.assertEqual(
                artifacts["camera_frame.bin"].stat().st_size,
                len(contents["camera_frame.bin"]),
            )

    def test_extraction_rejects_zip_path_traversal(self):
        contents = {
            "inspection_run.json": b"{}",
            "inspection_report.md": b"report",
            "work_orders.json": b"[]",
            "../outside.bin": b"not safe",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "result_bundle.zip"
            self._write_bundle(archive_path, contents)
            with self.assertRaisesRegex(BundleError, "invalid artifact name"):
                extract_result_bundle(archive_path, Path(temp_dir) / "staged")

    def test_slurm_fetch_checks_remote_size_and_extracts_to_caller_workspace(self):
        contents = {
            "inspection_run.json": b"{}",
            "inspection_report.md": b"report",
            "work_orders.json": b"[]",
            "depth_frame.bin": b"\x00\x01" * 100,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_bundle = root / "remote-result.zip"
            self._write_bundle(remote_bundle, contents)
            client = object.__new__(SlurmClient)
            client.target = "inspection@test.cluster"
            client._scp_options = lambda: []
            client._remote = lambda _command: str(remote_bundle.stat().st_size)
            client._run = lambda argv, **_kwargs: shutil.copyfile(remote_bundle, argv[-1])

            result = client.fetch_result(
                "/remote/RUN-0000000000000001", 2 * 1024 * 1024, root / "download")

            self.assertIsInstance(result.artifacts["depth_frame.bin"], Path)
            self.assertEqual(result.artifacts["depth_frame.bin"].read_bytes(), contents[
                "depth_frame.bin"])

            client._remote = lambda _command: "MISSING"
            with self.assertRaisesRegex(SlurmResultError, "no result bundle"):
                client.fetch_result(
                    "/remote/RUN-0000000000000001", 2 * 1024 * 1024,
                    root / "missing-download")


if __name__ == "__main__":
    unittest.main()
