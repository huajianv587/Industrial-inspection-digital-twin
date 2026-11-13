from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_RESPONSE_BYTES = 2_000_000


class AuthSmokeError(RuntimeError):
    pass


def read_secret_file(env_name: str, *, project_root: Path = PROJECT_ROOT) -> str:
    configured_path = os.getenv(env_name)
    if not configured_path:
        raise AuthSmokeError(f"{env_name} must point to a private file under secrets/.")

    secret_root = project_root / "secrets"
    if secret_root.is_symlink():
        raise AuthSmokeError("The secrets directory must not be a symlink.")
    candidate = Path(configured_path).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    if candidate.is_symlink():
        raise AuthSmokeError(f"{env_name} must not point to a symlink.")
    try:
        path = candidate.resolve(strict=True)
        path.relative_to(secret_root.resolve(strict=True))
        info = path.stat()
    except (OSError, ValueError) as exc:
        raise AuthSmokeError(f"{env_name} must point to a readable file under secrets/.") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
        raise AuthSmokeError(f"{env_name} must point to a small regular file.")
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        raise AuthSmokeError(f"{env_name} file permissions must not allow group or other access.")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise AuthSmokeError(f"{env_name} could not be read as UTF-8.") from exc
    if not value or "\n" in value or "\r" in value or "\0" in value:
        raise AuthSmokeError(f"{env_name} must contain one non-empty line.")
    return value


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(request: Request) -> tuple[int, bytes]:
    opener = build_opener(_NoRedirectHandler)
    try:
        with opener.open(request, timeout=15) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise AuthSmokeError("Auth smoke response exceeded the size limit.")
            return response.status, body
    except HTTPError as exc:
        exc.close()
        return exc.code, b""
    except (URLError, TimeoutError, OSError) as exc:
        raise AuthSmokeError("Supabase or local API request failed.") from exc


def _validate_endpoints(supabase_url: str, api_base_url: str) -> tuple[str, str]:
    supabase = urlsplit(supabase_url)
    if (supabase.scheme != "https" or not supabase.hostname
            or not supabase.hostname.endswith((".supabase.co", ".supabase.com"))
            or supabase.username or supabase.password or supabase.query or supabase.fragment):
        raise AuthSmokeError("SUPABASE_URL must be this project's HTTPS Supabase URL.")

    api = urlsplit(api_base_url)
    if (api.scheme != "http" or api.hostname not in {"127.0.0.1", "localhost", "::1"}
            or api.username or api.password or api.path.rstrip("/") != "/api/v1"
            or api.query or api.fragment):
        raise AuthSmokeError("API_BASE_URL must target the local /api/v1 smoke server.")
    return supabase_url.rstrip("/"), api_base_url.rstrip("/")


def _json_response(status_code: int, body: bytes, *, expected: type, label: str) -> Any:
    if status_code != 200:
        raise AuthSmokeError(
            f"Authenticated {label} request returned HTTP {status_code}; verify the account role and API access.")
    try:
        payload = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuthSmokeError(f"Authenticated {label} response was not valid JSON.") from exc
    if not isinstance(payload, expected):
        raise AuthSmokeError(f"Authenticated {label} response had an unexpected shape.")
    return payload


def run_auth_smoke() -> dict[str, int]:
    supabase_url = os.getenv("SUPABASE_URL", "")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    api_base_url = os.getenv("API_BASE_URL", "")
    if not anon_key:
        raise AuthSmokeError("SUPABASE_ANON_KEY is required for Supabase Auth.")
    supabase_url, api_base_url = _validate_endpoints(supabase_url, api_base_url)
    email = read_secret_file("SUPABASE_E2E_EMAIL_SECRET_FILE")
    password = read_secret_file("SUPABASE_E2E_PASSWORD_SECRET_FILE")

    login_request = Request(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": password}).encode("utf-8"),
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        method="POST",
    )
    login_status, login_body = _request(login_request)
    login_payload = _json_response(login_status, login_body, expected=dict, label="Supabase login")
    access_token = login_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise AuthSmokeError("Supabase login response did not contain an access token.")

    endpoints = (
        ("dashboard", "/dashboard", dict),
        ("sites", "/sites", dict),
        ("missions", "/missions?limit=1", list),
        ("work_orders", "/work-orders?limit=1", list),
    )
    results = {"auth_login": login_status}
    for label, path, response_type in endpoints:
        request = Request(
            f"{api_base_url}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            method="GET",
        )
        status_code, body = _request(request)
        _json_response(status_code, body, expected=response_type, label=label)
        results[label] = status_code
    return results


def main() -> int:
    try:
        results = run_auth_smoke()
    except AuthSmokeError as exc:
        print(f"auth_e2e=FAILED reason={exc}", file=sys.stderr)
        return 1
    print(" ".join(f"{name}={code}" for name, code in results.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
