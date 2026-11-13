#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# v25 is an isolated MCC service-detail replay. It keeps v23/v24 immutable and
# imports the locally rendered v25 scene into a fresh SQLite demo database.
export LOCAL_DEMO_DIR="${LOCAL_DEMO_DIR:-$ROOT_DIR/outputs/local-demo-v25-ultra}"
export SITE_CONFIG_PATH="${SITE_CONFIG_PATH:-$ROOT_DIR/configs/industrial_site_v12.json}"
export INDUSTRIAL_SITE_CONFIG_PATH="${INDUSTRIAL_SITE_CONFIG_PATH:-$SITE_CONFIG_PATH}"
export LOCAL_DEMO_BOOTSTRAP_MISSION=0
export LOCAL_DEMO_PREBUILT_IMPORT=1
export LOCAL_DEMO_PREBUILT_SCENE_DIR="${LOCAL_DEMO_PREBUILT_SCENE_DIR:-$ROOT_DIR/outputs/industrial-v25-full-768}"
export LOCAL_DEMO_PREBUILT_SOURCE_DB="${LOCAL_DEMO_PREBUILT_SOURCE_DB:-$ROOT_DIR/outputs/local-demo-v24-ultra/inspection.db}"
export LOCAL_DEMO_PREBUILT_SOURCE_RUN_ID="${LOCAL_DEMO_PREBUILT_SOURCE_RUN_ID:-RUN-V24-OPERATIONALFINISH}"
export LOCAL_DEMO_PREBUILT_RUN_ID="${LOCAL_DEMO_PREBUILT_RUN_ID:-RUN-V25-MCC-SERVICEDETAIL}"
export LOCAL_DEMO_PREBUILT_SCENE_NAME="${LOCAL_DEMO_PREBUILT_SCENE_NAME:-industrial-v25-full-768}"
export LOCAL_DEMO_SCENE_DETAIL_LEVEL="${LOCAL_DEMO_SCENE_DETAIL_LEVEL:-factory_environment_v25_mcc_service_detail}"
export LOCAL_DEMO_PREBUILT_IDEMPOTENCY_KEY="${LOCAL_DEMO_PREBUILT_IDEMPOTENCY_KEY:-local-demo-v25-prebuilt}"

exec "$ROOT_DIR/scripts/local_demo.sh"
