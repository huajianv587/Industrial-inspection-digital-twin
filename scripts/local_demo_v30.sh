#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# v30 is the product-success demonstration profile. It reuses the v28 factory
# scene and synchronized streams with a separate all-normal result set.
export API_PORT="${API_PORT:-8010}"
export WEB_PORT="${WEB_PORT:-5173}"
export LOCAL_DEMO_DIR="${LOCAL_DEMO_DIR:-$ROOT_DIR/outputs/local-demo-v30-final}"
export SITE_CONFIG_PATH="${SITE_CONFIG_PATH:-$ROOT_DIR/configs/industrial_site_v12.json}"
export INDUSTRIAL_SITE_CONFIG_PATH="${INDUSTRIAL_SITE_CONFIG_PATH:-$SITE_CONFIG_PATH}"
export LOCAL_DEMO_BOOTSTRAP_MISSION=0
export LOCAL_DEMO_PREBUILT_IMPORT=1
export LOCAL_DEMO_PREBUILT_SCENE_DIR="${LOCAL_DEMO_PREBUILT_SCENE_DIR:-$ROOT_DIR/outputs/industrial-v30-final-768}"
export LOCAL_DEMO_PREBUILT_SOURCE_DB="${LOCAL_DEMO_PREBUILT_SOURCE_DB:-$ROOT_DIR/outputs/local-demo-v28-ultra/inspection.db}"
export LOCAL_DEMO_PREBUILT_SOURCE_RUN_ID="${LOCAL_DEMO_PREBUILT_SOURCE_RUN_ID:-RUN-V28-STREAM-READY-PLANT}"
export LOCAL_DEMO_PREBUILT_RUN_ID="${LOCAL_DEMO_PREBUILT_RUN_ID:-RUN-V30-FINAL-PRODUCT-DEMO-SUCCESS}"
export LOCAL_DEMO_PREBUILT_SCENE_NAME="${LOCAL_DEMO_PREBUILT_SCENE_NAME:-industrial-v30-final-768}"
export LOCAL_DEMO_SCENE_DETAIL_LEVEL="${LOCAL_DEMO_SCENE_DETAIL_LEVEL:-factory_environment_v30_flattened_pbr_micro_geometry_stream_ready_product_demo}"
export LOCAL_DEMO_PREBUILT_IDEMPOTENCY_KEY="${LOCAL_DEMO_PREBUILT_IDEMPOTENCY_KEY:-local-demo-v30-final-product-success}"
export LOCAL_DEMO_PREBUILT_SCENARIO="${LOCAL_DEMO_PREBUILT_SCENARIO:-successful}"

exec "$ROOT_DIR/scripts/local_demo.sh"
