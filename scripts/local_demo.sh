#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

UV_BIN="${UV:-uv}"
DEMO_DIR="${LOCAL_DEMO_DIR:-$ROOT_DIR/outputs/local-demo}"
DB_PATH="$DEMO_DIR/inspection.db"
ARTIFACT_DIR="$DEMO_DIR/artifacts"
API_LOG="$DEMO_DIR/api.log"
WORKER_LOG="$DEMO_DIR/worker.log"
WEB_LOG="$DEMO_DIR/web.log"
API_PORT="${API_PORT:-8010}"
WEB_PORT="${WEB_PORT:-5173}"

mkdir -p "$DEMO_DIR" "$ARTIFACT_DIR"

if [[ "${LOCAL_DEMO_PREBUILT_IMPORT:-0}" == "1" ]]; then
  "$UV_BIN" run python "$ROOT_DIR/scripts/import_prebuilt_virtual_world.py" \
    --demo-dir "$DEMO_DIR" \
    --scene-dir "${LOCAL_DEMO_PREBUILT_SCENE_DIR:?LOCAL_DEMO_PREBUILT_SCENE_DIR is required}" \
    --source-db "${LOCAL_DEMO_PREBUILT_SOURCE_DB:?LOCAL_DEMO_PREBUILT_SOURCE_DB is required}" \
    --source-run-id "${LOCAL_DEMO_PREBUILT_SOURCE_RUN_ID:-RUN-B97F9E32E8DE4852}" \
    --site-config "$INDUSTRIAL_SITE_CONFIG_PATH" \
    --run-id "${LOCAL_DEMO_PREBUILT_RUN_ID:-RUN-V23-HIGHGRANULARITY}" \
    --prebuilt-scene-name "${LOCAL_DEMO_PREBUILT_SCENE_NAME:-industrial-v23-full-768}" \
    --scene-detail-level "${LOCAL_DEMO_SCENE_DETAIL_LEVEL:-factory_environment_v23_high_granularity}" \
    --idempotency-key "${LOCAL_DEMO_PREBUILT_IDEMPOTENCY_KEY:-local-demo-v23-prebuilt}" \
    --scenario "${LOCAL_DEMO_PREBUILT_SCENARIO:-source}" \
    --render-resolution "${LOCAL_DEMO_PREBUILT_RENDER_RESOLUTION:-768}" \
    --render-quality "${LOCAL_DEMO_PREBUILT_RENDER_QUALITY:-ultra}"
  export LOCAL_DEMO_BOOTSTRAP_MISSION=0
fi

if [[ "${LOCAL_DEMO_PREBUILT_IMPORT_SECONDARY:-0}" == "1" ]]; then
  "$UV_BIN" run python "$ROOT_DIR/scripts/import_prebuilt_virtual_world.py" \
    --demo-dir "$DEMO_DIR" \
    --scene-dir "${LOCAL_DEMO_PREBUILT_SECONDARY_SCENE_DIR:-${LOCAL_DEMO_PREBUILT_SCENE_DIR:?LOCAL_DEMO_PREBUILT_SCENE_DIR is required}}" \
    --source-db "${LOCAL_DEMO_PREBUILT_SECONDARY_SOURCE_DB:-${LOCAL_DEMO_PREBUILT_SOURCE_DB:?LOCAL_DEMO_PREBUILT_SOURCE_DB is required}}" \
    --source-run-id "${LOCAL_DEMO_PREBUILT_SECONDARY_SOURCE_RUN_ID:-${LOCAL_DEMO_PREBUILT_SOURCE_RUN_ID:-RUN-B97F9E32E8DE4852}}" \
    --site-config "$INDUSTRIAL_SITE_CONFIG_PATH" \
    --run-id "${LOCAL_DEMO_PREBUILT_SECONDARY_RUN_ID:?LOCAL_DEMO_PREBUILT_SECONDARY_RUN_ID is required}" \
    --prebuilt-scene-name "${LOCAL_DEMO_PREBUILT_SECONDARY_SCENE_NAME:-${LOCAL_DEMO_PREBUILT_SCENE_NAME:-industrial-v23-full-768}}" \
    --scene-detail-level "${LOCAL_DEMO_SECONDARY_SCENE_DETAIL_LEVEL:-${LOCAL_DEMO_SCENE_DETAIL_LEVEL:-factory_environment_v23_high_granularity}}" \
    --idempotency-key "${LOCAL_DEMO_PREBUILT_SECONDARY_IDEMPOTENCY_KEY:-local-demo-secondary-prebuilt}" \
    --scenario "${LOCAL_DEMO_PREBUILT_SECONDARY_SCENARIO:-synthetic_anomaly}" \
    --render-resolution "${LOCAL_DEMO_PREBUILT_SECONDARY_RENDER_RESOLUTION:-${LOCAL_DEMO_PREBUILT_RENDER_RESOLUTION:-768}}" \
    --render-quality "${LOCAL_DEMO_PREBUILT_SECONDARY_RENDER_QUALITY:-${LOCAL_DEMO_PREBUILT_RENDER_QUALITY:-ultra}}"
fi

export APP_ENV=local_demo
export LOCAL_DATABASE_URL="sqlite:///$DB_PATH"
export INSPECTION_AUTH_MODE=development
export INSPECTION_EXECUTOR=offline
export SLURM_RESULT_SOURCE=synthetic_simulation
export SITE_CONFIG_PATH="${SITE_CONFIG_PATH:-$ROOT_DIR/configs/site.json}"
export INDUSTRIAL_SITE_CONFIG_PATH="${INDUSTRIAL_SITE_CONFIG_PATH:-$SITE_CONFIG_PATH}"
export ARTIFACT_DIR
export ARTIFACT_STORAGE_BACKEND=local
export SLURM_POLL_SECONDS="${SLURM_POLL_SECONDS:-1}"
export WORKER_HEARTBEAT_STALE_SECONDS="${WORKER_HEARTBEAT_STALE_SECONDS:-10}"
export RESULT_IMPORT_RETRY_SECONDS="${RESULT_IMPORT_RETRY_SECONDS:-2}"
export VITE_LOCAL_DEMO=1
export VITE_API_BASE_URL=/api/v1
export VITE_DEV_API_TARGET="${VITE_DEV_API_TARGET:-http://127.0.0.1:${API_PORT}}"

api_pid=""
worker_pid=""
web_pid=""

cleanup() {
  trap - EXIT INT TERM
  for pid in "$web_pid" "$worker_pid" "$api_pid"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$web_pid" "$worker_pid" "$api_pid"; do
    if [[ -n "$pid" ]]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

echo "Starting local virtual inspection demo..."
echo "  API:      http://127.0.0.1:${API_PORT}"
echo "  Console:  http://127.0.0.1:${WEB_PORT}"
echo "  Data:     $DEMO_DIR"

"$UV_BIN" run python -m uvicorn inspection_system.platform.api:create_app --factory \
  --host 127.0.0.1 --port "$API_PORT" --log-config configs/logging.json \
  >"$API_LOG" 2>&1 &
api_pid=$!

ready=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/healthz" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done
if [[ "$ready" != 1 ]]; then
  echo "Local API did not become ready. See $API_LOG." >&2
  exit 1
fi

"$UV_BIN" run inspection-worker >"$WORKER_LOG" 2>&1 &
worker_pid=$!

if [[ "${LOCAL_DEMO_BOOTSTRAP_MISSION:-0}" == "1" ]]; then
  mission_count="$(python3 - "$DB_PATH" <<'PY'
import sqlite3
import sys

database = sys.argv[1]
try:
    with sqlite3.connect(database) as connection:
        print(connection.execute("select count(*) from missions").fetchone()[0])
except (sqlite3.Error, OSError):
    print(0)
PY
)"
  if [[ "$mission_count" == "0" ]]; then
    payload="$(python3 - "$SITE_CONFIG_PATH" "${LOCAL_DEMO_BOOTSTRAP_SEED:-42}" \
      "${LOCAL_DEMO_BOOTSTRAP_RENDER_QUALITY:-production}" \
      "${LOCAL_DEMO_BOOTSTRAP_RENDER_RESOLUTION:-1280}" <<'PY'
import json
from pathlib import Path
import sys

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps({
    "site_id": config["site_id"],
    "waypoint_ids": [item["waypoint_id"] for item in config["waypoints"]],
    "seed": int(sys.argv[2]),
    "render_backend": "blender",
    "render_quality": sys.argv[3],
    "render_resolution": int(sys.argv[4]),
}, ensure_ascii=False, separators=(",", ":")))
PY
)"
    curl -fsS -X POST "http://127.0.0.1:${API_PORT}/api/v1/missions" \
      -H 'Authorization: Bearer local-demo-token' \
      -H 'X-Actor-Role: admin' \
      -H "Idempotency-Key: ${LOCAL_DEMO_BOOTSTRAP_IDEMPOTENCY_KEY:-local-demo-bootstrap}" \
      -H 'Content-Type: application/json' \
      -d "$payload" >"$DEMO_DIR/bootstrap-mission.json"
    echo "Bootstrap mission queued. Render parameters: ${LOCAL_DEMO_BOOTSTRAP_RENDER_QUALITY:-production}/${LOCAL_DEMO_BOOTSTRAP_RENDER_RESOLUTION:-1280}px"
  fi
fi

(
  cd web
  npm run dev -- --host 127.0.0.1 --port "$WEB_PORT"
) >"$WEB_LOG" 2>&1 &
web_pid=$!

echo "Ready. Open http://127.0.0.1:${WEB_PORT}/"
echo "Press Ctrl-C to stop API, worker, and web console."

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null \
      && kill -0 "$web_pid" 2>/dev/null; do
  sleep 2
done

echo "A local demo process stopped. Logs: $API_LOG, $WORKER_LOG, $WEB_LOG" >&2
exit 1
