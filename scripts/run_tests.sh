#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --extra test python -m unittest discover -s tests -v
