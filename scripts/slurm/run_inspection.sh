#!/usr/bin/env bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:30:00

set -Eeuo pipefail

WORK_DIR="${SLURM_SUBMIT_DIR:?Slurm did not provide SLURM_SUBMIT_DIR}"
PROJECT_DIR="$WORK_DIR/project"
MANIFEST="$WORK_DIR/mission.json"
RESULT_DIR="$WORK_DIR/results"
mkdir -p "$RESULT_DIR"
export PYTHONPATH="$PROJECT_DIR/src:$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"

python3 - "$MANIFEST" "${INSPECTION_MANIFEST_SHA256:-}" <<'PY'
import hashlib
import pathlib
import sys

manifest = pathlib.Path(sys.argv[1]).read_bytes()
expected = sys.argv[2]
actual = hashlib.sha256(manifest).hexdigest()
if not expected or actual != expected:
    raise SystemExit("Mission manifest checksum mismatch; refusing to run.")
PY

SOURCE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["source"])' "$MANIFEST")"

case "$SOURCE" in
  synthetic_simulation)
    python3 -m inspection_system.platform.job_runner \
      --manifest "$MANIFEST" \
      --output-dir "$RESULT_DIR"
    ;;
  isaac_sim)
    ISAAC_PYTHON="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["simulator"]["python_path"])' "$MANIFEST")"
    if [[ "$ISAAC_PYTHON" != /* || ! -x "$ISAAC_PYTHON" ]]; then
      echo "Configured Isaac Sim Python launcher is missing or not executable." >&2
      exit 2
    fi
    "$ISAAC_PYTHON" -m inspection_system.platform.isaac_runner \
      --manifest "$MANIFEST" \
      --output-dir "$RESULT_DIR"
    ;;
  *)
    echo "Unsupported mission source: $SOURCE" >&2
    exit 2
    ;;
esac
