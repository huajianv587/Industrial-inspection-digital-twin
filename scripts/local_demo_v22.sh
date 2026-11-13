#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# v22 is an isolated local replay with the completed industrial environment
# and a first-run bootstrap mission. It never mutates the v16-v21 trees.
export LOCAL_DEMO_DIR="${LOCAL_DEMO_DIR:-$ROOT_DIR/outputs/local-demo-v22-ultra}"
export SITE_CONFIG_PATH="${SITE_CONFIG_PATH:-$ROOT_DIR/configs/industrial_site_v12.json}"
export INDUSTRIAL_SITE_CONFIG_PATH="${INDUSTRIAL_SITE_CONFIG_PATH:-$SITE_CONFIG_PATH}"
export LOCAL_DEMO_BOOTSTRAP_MISSION="${LOCAL_DEMO_BOOTSTRAP_MISSION:-1}"
export LOCAL_DEMO_BOOTSTRAP_SEED="${LOCAL_DEMO_BOOTSTRAP_SEED:-42}"
export LOCAL_DEMO_BOOTSTRAP_RENDER_QUALITY="${LOCAL_DEMO_BOOTSTRAP_RENDER_QUALITY:-production}"
export LOCAL_DEMO_BOOTSTRAP_RENDER_RESOLUTION="${LOCAL_DEMO_BOOTSTRAP_RENDER_RESOLUTION:-768}"
export LOCAL_DEMO_BOOTSTRAP_IDEMPOTENCY_KEY="${LOCAL_DEMO_BOOTSTRAP_IDEMPOTENCY_KEY:-local-demo-v22-bootstrap}"

exec "$ROOT_DIR/scripts/local_demo.sh"
