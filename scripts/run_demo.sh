#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src python -m inspection_system.cli demo --config configs/site.json --output-dir outputs/demo
