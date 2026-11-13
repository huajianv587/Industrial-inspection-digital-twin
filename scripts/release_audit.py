from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "outputs" / "release_audit.json"
MAX_OUTPUT_CHARS = 4000


def _tail(value: str) -> str:
    value = value.strip()
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return "...[truncated]...\n" + value[-MAX_OUTPUT_CHARS:]


def run_check(
    check_id: str,
    command: Sequence[str],
    *,
    cwd: Path,
    kind: str = "local",
    timeout: int = 180,
) -> dict[str, Any]:
    tool = shutil.which(command[0])
    if tool is None:
        return {
            "id": check_id,
            "kind": kind,
            "status": "BLOCKED",
            "reason": f"Required command is unavailable: {command[0]}",
            "command": list(command),
        }

    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "id": check_id,
            "kind": kind,
            "status": "FAILED",
            "reason": f"Command exceeded {timeout} seconds.",
            "command": list(command),
            "stdout": _tail(exc.stdout or ""),
            "stderr": _tail(exc.stderr or ""),
        }

    result: dict[str, Any] = {
        "id": check_id,
        "kind": kind,
        "status": "PASSED" if completed.returncode == 0 else "FAILED",
        "returncode": completed.returncode,
        "command": list(command),
        "stdout": _tail(completed.stdout),
        "stderr": _tail(completed.stderr),
    }
    if completed.returncode != 0:
        result["reason"] = "Command returned a non-zero exit code."
    return result


def _compose_command() -> list[str] | None:
    docker = shutil.which("docker")
    if docker is None:
        return None
    probe = subprocess.run(
        [docker, "compose", "version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    return [docker, "compose"]


def _external_checks() -> list[dict[str, Any]]:
    secrets_dir = ROOT / "secrets"
    storage_ready = all(
        (secrets_dir / name).is_file()
        for name in ("supabase_storage_email", "supabase_storage_password")
    )
    auth_ready = all(
        (secrets_dir / name).is_file()
        for name in ("supabase_e2e_email", "supabase_e2e_password")
    )
    compose_ready = _compose_command() is not None

    return [
        {
            "id": "supabase_auth_e2e",
            "kind": "external",
            "status": "READY_TO_RUN" if auth_ready else "BLOCKED",
            "verification_command": "make smoke-auth-api",
            "reason": (
                "Dedicated non-production Auth credentials are present; the live user flow "
                "is still unverified."
                if auth_ready
                else "Dedicated non-production Auth credential files are missing under secrets/."
            ),
        },
        {
            "id": "supabase_storage_io",
            "kind": "external",
            "status": "READY_TO_RUN" if storage_ready else "BLOCKED",
            "verification_command": "make smoke-storage",
            "reason": (
                "Storage credentials are present; live upload/download is still unverified."
                if storage_ready
                else "Dedicated Storage credential files are missing under secrets/."
            ),
        },
        {
            "id": "compose_runtime",
            "kind": "external",
            "status": "READY_TO_RUN" if compose_ready else "BLOCKED",
            "verification_command": "make up-tls",
            "reason": (
                "Docker Compose is available; no services were started by this audit."
                if compose_ready
                else "Docker Compose plugin or daemon is unavailable; runtime was not started."
            ),
        },
        {
            "id": "slurm_isaac_ros2",
            "kind": "external",
            "status": "NOT_VALIDATED",
            "verification_command": "Authorized target-cluster smoke job",
            "reason": (
                "SSH reachability, GPU/driver/container compatibility, Isaac Sim, ROS 2 "
                "and result return must be verified on the target cluster."
            ),
        },
        {
            "id": "field_robot_eam",
            "kind": "external",
            "status": "NOT_VALIDATED",
            "verification_command": "Authorized field acceptance procedure",
            "reason": (
                "Unitree SDK, Nav2, safety interlocks, E-stop, calibration and EAM vendor "
                "integration are outside the local software audit."
            ),
        },
    ]


def overall_status(checks: Sequence[dict[str, Any]]) -> str:
    local_checks = [
        item for item in checks if item.get("kind") in {"local", "synthetic"}
    ]
    if any(item.get("status") in {"FAILED", "BLOCKED"} for item in local_checks):
        return "LOCAL_CHECKS_FAILED"
    if any(
        item.get("kind") == "external" and item.get("status") != "PASSED"
        for item in checks
    ):
        return "LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED"
    return "READY_FOR_RELEASE"


def build_report() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="inspection-release-audit-") as temp_dir:
        temp_path = Path(temp_dir)
        checks = [
            run_check(
                "backend_regression",
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                cwd=ROOT,
            ),
            run_check(
                "site_config",
                [
                    sys.executable,
                    "-m",
                    "inspection_system.cli",
                    "validate-config",
                    "--config",
                    "configs/site.json",
                ],
                cwd=ROOT,
            ),
            run_check(
                "offline_mission_demo",
                [
                    sys.executable,
                    "-m",
                    "inspection_system.cli",
                    "demo",
                    "--config",
                    "configs/site.json",
                    "--output-dir",
                    str(temp_path / "demo"),
                ],
                cwd=ROOT,
                kind="synthetic",
            ),
            run_check(
                "deterministic_software_acceptance",
                [
                    sys.executable,
                    "-m",
                    "inspection_system.cli",
                    "evaluate",
                    "--config",
                    "configs/site.json",
                    "--output",
                    str(temp_path / "acceptance_report.json"),
                ],
                cwd=ROOT,
                kind="synthetic",
            ),
            run_check(
                "frontend_production_build",
                ["npm", "run", "build"],
                cwd=ROOT / "web",
            ),
            run_check(
                "desktop_browser_regression",
                ["npm", "run", "test:e2e"],
                cwd=ROOT / "web",
                timeout=240,
            ),
            run_check(
                "python_dependency_audit",
                ["uv", "audit", "--locked"],
                cwd=ROOT,
            ),
            run_check(
                "node_dependency_audit",
                ["npm", "audit", "--audit-level=moderate"],
                cwd=ROOT / "web",
            ),
            run_check(
                "compose_yaml_syntax",
                [
                    "ruby",
                    "-e",
                    (
                        "require 'yaml'; ARGV.each { |f| "
                        "Psych.safe_load(File.read(f), permitted_classes: [], "
                        "permitted_symbols: [], aliases: true); puts \"#{f}: YAML OK\" }"
                    ),
                    "docker-compose.yml",
                    "docker-compose.slurm.yml",
                    "docker-compose.tls.yml",
                    ".github/workflows/ci.yml",
                ],
                cwd=ROOT,
            ),
        ]
        for check in checks:
            check["command"] = [
                argument.replace(str(temp_path), "<temporary-audit-dir>")
                for argument in check.get("command", [])
            ]

    checks.extend(_external_checks())
    local_passed = sum(
        item.get("status") == "PASSED"
        for item in checks
        if item.get("kind") in {"local", "synthetic"}
    )
    local_total = sum(
        item.get("kind") in {"local", "synthetic"}
        for item in checks
    )
    status = overall_status(checks)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": "unitree_isaac_inspection_system",
        "status": status,
        "release_ready": status == "READY_FOR_RELEASE",
        "local_checks_passed": local_passed,
        "local_checks_total": local_total,
        "checks": checks,
        "interpretation": {
            "synthetic_results_are_not_field_evidence": True,
            "external_checks_are_not_started_automatically": True,
            "target_environment_validation_required": True,
        },
    }


def main() -> int:
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "local_checks": f"{report['local_checks_passed']}/{report['local_checks_total']}",
        "report": str(REPORT_PATH),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] != "LOCAL_CHECKS_FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
