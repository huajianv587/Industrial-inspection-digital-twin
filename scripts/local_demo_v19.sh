#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Keep the v19 Ultra replay on its own artifact/database tree. It is a local
# synthetic replay and does not modify the verified v16-v18 output folders.
export LOCAL_DEMO_DIR="${LOCAL_DEMO_DIR:-$ROOT_DIR/outputs/local-demo-v19-ultra}"
export SITE_CONFIG_PATH="${SITE_CONFIG_PATH:-$ROOT_DIR/configs/industrial_site_v12.json}"
export INDUSTRIAL_SITE_CONFIG_PATH="${INDUSTRIAL_SITE_CONFIG_PATH:-$SITE_CONFIG_PATH}"

exec "$ROOT_DIR/scripts/local_demo.sh"
