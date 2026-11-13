from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from inspection_system.platform.auth_policy import (
    AuthPolicyError,
    validate_supabase_auth_policy,
)


class SupabaseAuthPolicyTests(unittest.TestCase):
    @patch("inspection_system.platform.auth_policy._read_settings")
    def test_accepts_disabled_signup_and_required_email_confirmation(self, read_settings):
        read_settings.return_value = (200, json.dumps({
            "disable_signup": True,
            "mailer_autoconfirm": False,
        }).encode())

        validate_supabase_auth_policy("https://project-ref.supabase.co", "public-test-key")

        request = read_settings.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            request.full_url,
            "https://project-ref.supabase.co/auth/v1/settings",
        )
        self.assertEqual(request.get_header("Apikey"), "public-test-key")

    @patch("inspection_system.platform.auth_policy._read_settings", return_value=(200, b'{"disable_signup":false,"mailer_autoconfirm":false}'))
    def test_rejects_public_signup(self, _read_settings):
        with self.assertRaisesRegex(AuthPolicyError, "sign-ups to be disabled"):
            validate_supabase_auth_policy("https://project-ref.supabase.co", "public-test-key")

    @patch("inspection_system.platform.auth_policy._read_settings", return_value=(200, b'{"disable_signup":true,"mailer_autoconfirm":true}'))
    def test_rejects_automatic_email_confirmation(self, _read_settings):
        with self.assertRaisesRegex(AuthPolicyError, "email confirmation"):
            validate_supabase_auth_policy("https://project-ref.supabase.co", "public-test-key")

    @patch("inspection_system.platform.auth_policy._read_settings")
    def test_rejects_missing_or_non_boolean_policy_fields(self, read_settings):
        for body in (b"{}", b'{"disable_signup":1,"mailer_autoconfirm":false}'):
            with self.subTest(body=body):
                read_settings.return_value = (200, body)
                with self.assertRaises(AuthPolicyError):
                    validate_supabase_auth_policy(
                        "https://project-ref.supabase.co", "public-test-key")

    @patch("inspection_system.platform.auth_policy._read_settings")
    def test_rejects_invalid_project_url_before_network(self, read_settings):
        for url in (
            "http://project-ref.supabase.co",
            "https://project-ref.supabase.co/path",
            "https://project-ref.supabase.co?next=example.test",
            "https://project-ref.other.supabase.co",
        ):
            with self.subTest(url=url), self.assertRaises(AuthPolicyError):
                validate_supabase_auth_policy(url, "public-test-key")
        read_settings.assert_not_called()

    @patch("inspection_system.platform.auth_policy._read_settings")
    def test_rejects_missing_or_header_injection_api_key_before_network(self, read_settings):
        for key in ("", "key\r\nAuthorization: Bearer secret"):
            with self.subTest(key=key), self.assertRaises(AuthPolicyError):
                validate_supabase_auth_policy("https://project-ref.supabase.co", key)
        read_settings.assert_not_called()

    @patch("inspection_system.platform.auth_policy._read_settings", return_value=(503, b"private response"))
    def test_http_errors_do_not_echo_response_or_credentials(self, _read_settings):
        with self.assertRaises(AuthPolicyError) as raised:
            validate_supabase_auth_policy(
                "https://project-ref.supabase.co", "never-print-this-test-key")
        self.assertNotIn("private response", str(raised.exception))
        self.assertNotIn("never-print-this-test-key", str(raised.exception))

    @patch("inspection_system.platform.auth_policy._read_settings", return_value=(200, b"[]"))
    def test_rejects_unexpected_json_shape(self, _read_settings):
        with self.assertRaisesRegex(AuthPolicyError, "unexpected shape"):
            validate_supabase_auth_policy("https://project-ref.supabase.co", "public-test-key")


if __name__ == "__main__":
    unittest.main()
