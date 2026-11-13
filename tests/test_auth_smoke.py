from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

from inspection_system.platform.auth_smoke import (
    AuthSmokeError,
    read_secret_file,
    run_auth_smoke,
)


class AuthSmokeTests(unittest.TestCase):
    @patch.dict(os.environ, {
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_ANON_KEY": "public-key",
        "API_BASE_URL": "http://127.0.0.1:18011/api/v1",
    }, clear=True)
    @patch("inspection_system.platform.auth_smoke._request")
    def test_missing_test_account_files_fail_before_network(self, request_mock):
        with self.assertRaisesRegex(AuthSmokeError, "SUPABASE_E2E_EMAIL_SECRET_FILE"):
            run_auth_smoke()
        request_mock.assert_not_called()

    @patch.dict(os.environ, {
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_ANON_KEY": "public-key",
        "API_BASE_URL": "http://127.0.0.1:18011/api/v1",
    })
    @patch("inspection_system.platform.auth_smoke.read_secret_file",
           side_effect=["operator@example.invalid", "test-password"])
    @patch("inspection_system.platform.auth_smoke._request")
    def test_signs_in_and_checks_read_only_api_routes(self, request_mock, _secret_mock):
        request_mock.side_effect = [
            (200, json.dumps({"access_token": "opaque-token"}).encode()),
            (200, b"{}"),
            (200, b"{}"),
            (200, b"[]"),
            (200, b"[]"),
        ]

        results = run_auth_smoke()

        self.assertEqual(results, {
            "auth_login": 200,
            "dashboard": 200,
            "sites": 200,
            "missions": 200,
            "work_orders": 200,
        })
        requests = [call.args[0] for call in request_mock.call_args_list]
        self.assertEqual(requests[0].get_method(), "POST")
        self.assertEqual(json.loads(requests[0].data), {
            "email": "operator@example.invalid",
            "password": "test-password",
        })
        for request in requests[1:]:
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Authorization"), "Bearer opaque-token")

    @patch.dict(os.environ, {
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_ANON_KEY": "public-key",
        "API_BASE_URL": "http://127.0.0.1:18011/api/v1",
    })
    @patch("inspection_system.platform.auth_smoke.read_secret_file",
           side_effect=["operator@example.invalid", "test-password"])
    @patch("inspection_system.platform.auth_smoke._request", side_effect=[
        (200, b'{"access_token":"opaque-token"}'),
        (403, b'{"detail":"APPLICATION_ROLE_REQUIRED"}'),
    ])
    def test_roleless_account_fails_without_leaking_credentials(self, _request_mock, _secret_mock):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(AuthSmokeError) as raised:
            run_auth_smoke()
        message = str(raised.exception) + output.getvalue()
        self.assertIn("HTTP 403", message)
        self.assertNotIn("operator@example.invalid", message)
        self.assertNotIn("test-password", message)
        self.assertNotIn("opaque-token", message)

    def test_secret_file_must_be_private_and_inside_secrets_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secrets_dir = root / "secrets"
            secrets_dir.mkdir()
            secret = secrets_dir / "account"
            secret.write_text("test@example.invalid\n", encoding="utf-8")
            secret.chmod(0o600)
            with patch.dict(os.environ, {"TEST_SECRET_FILE": "./secrets/account"}):
                self.assertEqual(read_secret_file("TEST_SECRET_FILE", project_root=root),
                                 "test@example.invalid")

            secret.chmod(0o644)
            with patch.dict(os.environ, {"TEST_SECRET_FILE": "./secrets/account"}):
                with self.assertRaisesRegex(AuthSmokeError, "permissions"):
                    read_secret_file("TEST_SECRET_FILE", project_root=root)

            outside = root / "outside"
            outside.write_text("not allowed", encoding="utf-8")
            outside.chmod(0o600)
            with patch.dict(os.environ, {"TEST_SECRET_FILE": str(outside)}):
                with self.assertRaisesRegex(AuthSmokeError, "under secrets"):
                    read_secret_file("TEST_SECRET_FILE", project_root=root)

    @patch.dict(os.environ, {
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_ANON_KEY": "public-key",
        "API_BASE_URL": "https://collector.example/api/v1",
    })
    @patch("inspection_system.platform.auth_smoke.read_secret_file")
    def test_refuses_to_send_access_token_to_non_local_api(self, secret_mock):
        with self.assertRaisesRegex(AuthSmokeError, "local /api/v1"):
            run_auth_smoke()
        secret_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
