from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
import re
import tempfile

from ..config import load_site_config, waypoints_from_config
from ..mission.orchestrator import MissionOrchestrator
from .logging_config import configure_logging
from .result_bundle import build_result_bundle

logger = logging.getLogger(__name__)
_RUN_ID = re.compile(r"^RUN-[0-9A-F]{16}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def run_job(manifest_path: Path, output_dir: Path) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict)
            or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1):
        raise ValueError("Unsupported mission manifest version.")
    if manifest.get("source") != "synthetic_simulation":
        raise ValueError(
            "The packaged runner only produces synthetic_simulation results; "
            "Isaac Sim data requires a separately validated runner.")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("Manifest run_id is invalid.")
    seed = manifest.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Manifest seed must be a non-negative 32-bit integer.")
    site_config = manifest.get("site_config")
    if not isinstance(site_config, dict):
        raise ValueError("Manifest is missing its frozen site_config.")
    with tempfile.TemporaryDirectory(prefix="inspection-config-") as temp_dir:
        config_path = Path(temp_dir) / "site.json"
        config_path.write_text(json.dumps(site_config, ensure_ascii=False), encoding="utf-8")
        config = load_site_config(config_path)
    if manifest.get("site_id") != config["site_id"]:
        raise ValueError("Manifest site_id does not match frozen site_config.")
    if manifest.get("robot_id") != config["robot"]["robot_id"]:
        raise ValueError("Manifest robot_id does not match frozen site_config.")
    waypoints = waypoints_from_config(config)
    expected = manifest.get("waypoint_ids")
    if expected != [item.waypoint_id for item in waypoints]:
        raise ValueError("Manifest waypoint order does not match frozen configuration.")
    config_digest = hashlib.sha256(json.dumps(
        config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    if (not isinstance(manifest.get("config_sha256"), str)
            or not _SHA256.fullmatch(manifest["config_sha256"])):
        raise ValueError("Manifest config_sha256 is invalid.")
    if manifest["config_sha256"] != config_digest:
        raise ValueError("Frozen site_config checksum does not match config_sha256.")

    log_context = {"run_id": run_id, "execution_backend": "slurm"}
    logger.info("Synthetic inspection job started", extra=log_context)
    try:
        runner = MissionOrchestrator(
            site_id=manifest["site_id"],
            robot_id=manifest["robot_id"],
            waypoints=waypoints,
            run_id=run_id,
        )
        run = runner.run()
        bundle = build_result_bundle(output_dir, run, manifest["config_sha256"])
    except Exception as exc:
        logger.exception(
            "Synthetic inspection job failed",
            extra={**log_context, "error_type": type(exc).__name__},
        )
        raise
    logger.info(
        "Synthetic inspection job finished",
        extra={**log_context, "result_status": run.status},
    )
    return bundle


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    configure_logging(project_root / "configs" / "logging.json")
    parser = argparse.ArgumentParser(description="Run a versioned inspection job manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_job(args.manifest, args.output_dir)
    except Exception as exc:
        logger.exception(
            "Synthetic Slurm runner failed",
            extra={"execution_backend": "slurm", "error_type": type(exc).__name__},
        )
        return 2
    print(f"result_bundle={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
