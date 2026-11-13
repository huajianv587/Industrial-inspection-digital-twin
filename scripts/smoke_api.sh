#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

port=${API_SMOKE_PORT:-18011}
case "$port" in
  ''|*[!0-9]*) printf '%s\n' "API_SMOKE_PORT must be a port number." >&2; exit 2 ;;
esac

if ! python3 -c 'import socket,sys; p=int(sys.argv[1]); 1024 <= p <= 65535 or sys.exit(1); s=socket.socket(); s.bind(("127.0.0.1",p)); s.close()' "$port" 2>/dev/null; then
  printf 'API smoke port %s is invalid or already in use.\n' "$port" >&2
  exit 2
fi

if [ ! -f .env ]; then
  printf '%s\n' "Missing .env with the remote Supabase runtime database URL." >&2
  exit 2
fi

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/inspection-api-smoke.XXXXXX")
server_pid=
cleanup() {
  if [ -n "$server_pid" ] && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$tmp_dir"
}
fail() {
  printf '%s\n' "$1" >&2
  if [ -f "$tmp_dir/api.log" ]; then
    cat "$tmp_dir/api.log" >&2
  fi
  exit 1
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

APP_ENV=development \
INSPECTION_EXECUTOR=offline \
SLURM_RESULT_SOURCE=synthetic_simulation \
SITE_CONFIG_PATH=configs/site.json \
ARTIFACT_DIR=artifacts \
ARTIFACT_STORAGE_BACKEND=local \
uv run --env-file .env uvicorn inspection_system.platform.api:create_app \
  --factory --host 127.0.0.1 --port "$port" --log-config configs/logging.json \
  >"$tmp_dir/api.log" 2>&1 &
server_pid=$!
base_url="http://127.0.0.1:$port"

attempt=0
until curl -fsS --max-time 2 "$base_url/healthz" >/dev/null 2>&1; do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    fail "API process exited before health check passed."
  fi
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    fail "API did not become healthy within 30 seconds."
  fi
  sleep 1
done

health_code=$(curl -sS -o "$tmp_dir/health.json" -w '%{http_code}' --max-time 5 "$base_url/healthz" || true)
ready_code=$(curl -sS -o "$tmp_dir/ready.json" -w '%{http_code}' --max-time 10 "$base_url/readyz" || true)
anonymous_code=$(curl -sS -o "$tmp_dir/anonymous.json" -w '%{http_code}' --max-time 5 "$base_url/api/v1/dashboard" || true)

[ "$health_code" = 200 ] || fail "Expected /healthz=200; got $health_code."
[ "$ready_code" = 200 ] || fail "Expected /readyz=200 against Supabase; got $ready_code."
[ "$anonymous_code" = 401 ] || fail "Expected anonymous dashboard access to be denied with 401; got $anonymous_code."

printf 'health=%s ready=%s anonymous_dashboard=%s\n' "$health_code" "$ready_code" "$anonymous_code"

if [ "${SMOKE_AUTH_E2E:-0}" = "1" ]; then
  API_BASE_URL="$base_url/api/v1" uv run --env-file .env python -m inspection_system.platform.auth_smoke \
    || fail "Authenticated Supabase API smoke failed."
fi
