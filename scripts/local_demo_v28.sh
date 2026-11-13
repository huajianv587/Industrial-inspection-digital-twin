#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# v28 adds route-indexed robot-head/CCTV image streams and close-range
# manufactured micro-geometry. It keeps v27 immutable and can run on alternate
# ports while the previous local demo remains available for comparison.
export API_PORT="${API_PORT:-8011}"
export WEB_PORT="${WEB_PORT:-5174}"
export LOCAL_DEMO_DIR="${LOCAL_DEMO_DIR:-$ROOT_DIR/outputs/local-demo-v28-ultra}"
export SITE_CONFIG_PATH="${SITE_CONFIG_PATH:-$ROOT_DIR/configs/industrial_site_v12.json}"
export INDUSTRIAL_SITE_CONFIG_PATH="${INDUSTRIAL_SITE_CONFIG_PATH:-$SITE_CONFIG_PATH}"
export LOCAL_DEMO_BOOTSTRAP_MISSION=0
export LOCAL_DEMO_PREBUILT_IMPORT=1
export LOCAL_DEMO_PREBUILT_SCENE_DIR="${LOCAL_DEMO_PREBUILT_SCENE_DIR:-$ROOT_DIR/outputs/industrial-v28-full-768}"
export LOCAL_DEMO_PREBUILT_SOURCE_DB="${LOCAL_DEMO_PREBUILT_SOURCE_DB:-$ROOT_DIR/outputs/local-demo-v26-ultra/inspection.db}"
export LOCAL_DEMO_PREBUILT_SOURCE_RUN_ID="${LOCAL_DEMO_PREBUILT_SOURCE_RUN_ID:-RUN-V26-MCC-OPEN-ENCLOSURE}"
export LOCAL_DEMO_PREBUILT_RUN_ID="${LOCAL_DEMO_PREBUILT_RUN_ID:-RUN-V28-STREAM-READY-PLANT}"
export LOCAL_DEMO_PREBUILT_SCENE_NAME="${LOCAL_DEMO_PREBUILT_SCENE_NAME:-industrial-v28-full-768}"
export LOCAL_DEMO_SCENE_DETAIL_LEVEL="${LOCAL_DEMO_SCENE_DETAIL_LEVEL:-factory_environment_v28_micro_geometry_stream_ready}"
export LOCAL_DEMO_PREBUILT_IDEMPOTENCY_KEY="${LOCAL_DEMO_PREBUILT_IDEMPOTENCY_KEY:-local-demo-v28-prebuilt}"

exec "$ROOT_DIR/scripts/local_demo.sh"
