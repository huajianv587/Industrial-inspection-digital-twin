from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 1_000_000
AUTH_SETTINGS_TIMEOUT_SECONDS = 10


class AuthPolicyError(ValueError):
    pass


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_settings(request: Request) -> tuple[int, bytes]:
    opener = build_opener(_NoRedirectHandler)
    try:
        with opener.open(request, timeout=AUTH_SETTINGS_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise AuthPolicyError("Supabase Auth settings response exceeded the size limit.")
            return response.status, body
    except HTTPError as exc:
        exc.close()
        return exc.code, b""
    except (URLError, TimeoutError, OSError) as exc:
        raise AuthPolicyError("Could not read Supabase Auth settings.") from exc


def validate_supabase_auth_policy(supabase_url: str, anon_key: str) -> None:
    parsed = urlsplit(supabase_url)
    host = (parsed.hostname or "").lower()
    project_ref = host.removesuffix(".supabase.co")
    if (parsed.scheme != "https" or not project_ref or "." in project_ref
            or not host.endswith(".supabase.co") or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise AuthPolicyError("SUPABASE_URL must identify this project's HTTPS Supabase URL.")
    if not anon_key or "\r" in anon_key or "\n" in anon_key:
        raise AuthPolicyError("SUPABASE_ANON_KEY is required for the Auth policy check.")

    request = Request(
        f"{supabase_url.rstrip('/')}/auth/v1/settings",
        headers={"apikey": anon_key, "Accept": "application/json"},
        method="GET",
    )
    status, body = _read_settings(request)
    if status != 200:
        raise AuthPolicyError(f"Supabase Auth settings returned HTTP {status}.")
    try:
        settings = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuthPolicyError("Supabase Auth settings response was not valid JSON.") from exc
    if not isinstance(settings, dict):
        raise AuthPolicyError("Supabase Auth settings response had an unexpected shape.")
    if settings.get("disable_signup") is not True:
        raise AuthPolicyError("Production requires public Supabase sign-ups to be disabled.")
    if settings.get("mailer_autoconfirm") is not False:
        raise AuthPolicyError("Production requires email confirmation for Supabase Auth users.")
