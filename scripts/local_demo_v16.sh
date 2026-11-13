#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Reuse the verified v16 Ultra mission and its local artifact store.
export LOCAL_DEMO_DIR="${LOCAL_DEMO_DIR:-$ROOT_DIR/outputs/local-demo-v16-ultra}"
export SITE_CONFIG_PATH="${SITE_CONFIG_PATH:-$ROOT_DIR/configs/industrial_site_v12.json}"
export INDUSTRIAL_SITE_CONFIG_PATH="${INDUSTRIAL_SITE_CONFIG_PATH:-$SITE_CONFIG_PATH}"

exec "$ROOT_DIR/scripts/local_demo.sh"
