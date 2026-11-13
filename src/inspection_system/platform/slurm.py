from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile
import tempfile
from typing import Callable

from .settings import PROJECT_ROOT, Settings
from .result_bundle import BundleError, extract_result_bundle

logger = logging.getLogger(__name__)


class SlurmError(RuntimeError):
    pass


class SlurmSubmissionOutcomeUnknown(SlurmError):
    """The scheduler may have accepted sbatch despite a lost response."""


class SlurmResultError(SlurmError):
    """A completed job produced a missing, oversized, or invalid result bundle."""


@dataclass(frozen=True)
class RemoteResult:
    manifest: dict
    inspection_run: dict
    artifacts: dict[str, Path | bytes]


class SlurmClient:
    """OpenSSH-based Slurm adapter with pinned host keys and no password auth."""

    def __init__(self, settings: Settings,
                 command_runner: Callable[..., subprocess.CompletedProcess] | None = None):
        settings.validate()
        self.settings = settings
        self.run_command = command_runner or subprocess.run
        self.target = f"{settings.slurm_user}@{settings.slurm_host}"
        self.remote_root = self._validate_remote_path(settings.slurm_remote_root or "")
        self._validate_remote_identity()

    @staticmethod
    def _validate_remote_path(value: str) -> str:
        if not value.startswith("/") or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
            raise ValueError("SLURM_REMOTE_ROOT must be an absolute path without shell metacharacters.")
        if ".." in PurePosixPath(value).parts:
            raise ValueError("SLURM_REMOTE_ROOT cannot contain parent-directory segments.")
        return value.rstrip("/")

    def _validate_remote_identity(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.settings.slurm_user or ""):
            raise ValueError("SLURM_USER contains unsupported characters.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.settings.slurm_host or ""):
            raise ValueError("SLURM_HOST contains unsupported characters.")
        if not 1 <= self.settings.slurm_port <= 65535:
            raise ValueError("SLURM_PORT must be between 1 and 65535.")

    def _ssh_options(self) -> list[str]:
        return [
            "-F", "/dev/null",
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.settings.slurm_known_hosts_file}",
            "-o", f"ConnectTimeout={max(1, int(self.settings.slurm_command_timeout_seconds))}",
            "-p", str(self.settings.slurm_port),
            "-i", str(self.settings.slurm_identity_file),
        ]

    def _run(self, argv: list[str], *, input_text: str | None = None) -> str:
        try:
            completed = self.run_command(
                argv,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=self.settings.slurm_command_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SlurmError(f"Remote command could not complete: {type(exc).__name__}.") from exc
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "remote command failed").strip()
            raise SlurmError(detail[-2000:])
        return completed.stdout.strip()

    def _remote(self, command: str) -> str:
        return self._run(["ssh", *self._ssh_options(), self.target, command])

    def _scp_options(self) -> list[str]:
        options = self._ssh_options()
        return [item for item in options if item not in {"-p", str(self.settings.slurm_port)}] + [
            "-P", str(self.settings.slurm_port)]

    def _make_source_bundle(self, destination: Path) -> None:
        included = [
            "src/inspection_system", "configs", "isaac_sim", "scripts/slurm", "pyproject.toml"
        ]
        with tarfile.open(destination, "w:gz") as archive:
            for relative in included:
                path = PROJECT_ROOT / relative
                if not path.exists():
                    continue
                paths = [path] if path.is_file() else sorted(path.rglob("*"))
                for item in paths:
                    if item.is_file() and not item.is_symlink():
                        archive.add(item, arcname=item.relative_to(PROJECT_ROOT).as_posix())

    def submit(self, mission: dict) -> tuple[str, str]:
        run_id = mission["run_id"]
        if not re.fullmatch(r"RUN-[0-9A-F]{16}", run_id):
            raise SlurmError("Invalid run_id in mission manifest.")
        if mission.get("source") != self.settings.slurm_source:
            raise SlurmError("Mission result source does not match the configured Slurm runner.")
        resource_args: list[str] = []
        if mission["source"] == "isaac_sim":
            simulator = mission.get("simulator")
            configured = {
                "expected_version": self.settings.isaac_sim_version,
                "robot_usd_path": self.settings.isaac_robot_usd_path,
                "python_path": self.settings.isaac_sim_python,
                "adapter_entrypoint": self.settings.isaac_sim_adapter,
            }
            if self.settings.isaac_model_manifest_path:
                configured["model"] = {
                    "manifest_path": self.settings.isaac_model_manifest_path,
                    "manifest_sha256": self.settings.isaac_model_manifest_sha256,
                    "artifact_sha256": self.settings.isaac_model_artifact_sha256,
                    "model_id": self.settings.isaac_model_id,
                    "model_version": self.settings.isaac_model_version,
                }
            if simulator != configured:
                raise SlurmError("Mission Isaac Sim configuration does not match worker settings.")
            resource_args = [
                "--gres=" + shlex.quote(self.settings.isaac_slurm_gres or ""),
                "--cpus-per-task=" + str(self.settings.isaac_slurm_cpus),
                "--mem=" + shlex.quote(self.settings.isaac_slurm_memory),
                "--time=" + shlex.quote(self.settings.isaac_slurm_time_limit),
            ]
        elif mission["source"] != "synthetic_simulation":
            raise SlurmError("Unsupported Slurm runner source.")
        remote_dir = f"{self.remote_root}/{run_id}"
        self._remote(f"mkdir -p -- {shlex.quote(remote_dir)}")
        with tempfile.TemporaryDirectory(prefix="inspection-slurm-") as temp_dir:
            base = Path(temp_dir)
            bundle = base / "project.tar.gz"
            manifest = base / "mission.json"
            self._make_source_bundle(bundle)
            manifest_bytes = json.dumps(
                mission, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            manifest.write_bytes(manifest_bytes)
            manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
            self._run(["scp", *self._scp_options(), str(bundle), str(manifest),
                       f"{self.target}:{remote_dir}/"])
        command_parts = ["cd", shlex.quote(remote_dir), "&&", "mkdir", "-p", "project", "&&",
                         "tar", "-xzf", "project.tar.gz", "-C", "project", "&&", "sbatch", "--parsable",
                         "--job-name=" + shlex.quote("insp-" + run_id.lower())]
        if self.settings.slurm_partition:
            command_parts.append("--partition=" + shlex.quote(self.settings.slurm_partition))
        if self.settings.slurm_account:
            command_parts.append("--account=" + shlex.quote(self.settings.slurm_account))
        command_parts.append(
            "--export=" + shlex.quote(f"ALL,INSPECTION_MANIFEST_SHA256={manifest_digest}")
        )
        command_parts.extend(resource_args)
        command_parts.append("project/scripts/slurm/run_inspection.sh")
        try:
            output = self._remote(" ".join(command_parts))
        except Exception as exc:
            raise SlurmSubmissionOutcomeUnknown(
                "Slurm did not confirm the submission response."
            ) from exc
        job_id = output.split(";", 1)[0].strip()
        if not re.fullmatch(r"[0-9]+", job_id):
            raise SlurmSubmissionOutcomeUnknown(
                "sbatch returned no verifiable job id."
            )
        return job_id, remote_dir

    def status(self, job_id: str) -> str:
        if not re.fullmatch(r"[0-9]+", job_id):
            raise SlurmError("Invalid Slurm job id.")
        active = self._remote(f"squeue -h -j {shlex.quote(job_id)} -o %T")
        if active:
            return self._map_state(active.splitlines()[0].strip())
        accounting = self._remote(
            f"sacct --noheader --parsable2 -j {shlex.quote(job_id)} --format=State")
        for line in accounting.splitlines():
            state = line.strip().split("|", 1)[0]
            if state and not state.startswith("JobID"):
                return self._map_state(state)
        return "UNKNOWN"

    def find_jobs_for_runs(
        self,
        run_ids: list[str],
        submitted_after: datetime | None = None,
    ) -> dict[str, dict[str, str]]:
        run_ids = list(dict.fromkeys(run_ids))
        if any(not re.fullmatch(r"RUN-[0-9A-F]{16}", run_id) for run_id in run_ids):
            raise SlurmError("Invalid run_id while reconciling Slurm submissions.")
        result = {run_id: {} for run_id in run_ids}
        if not run_ids:
            return result
        names = {"insp-" + run_id.lower(): run_id for run_id in run_ids}
        name_filter = ",".join(names)
        active = self._remote(
            f"squeue -h --name={shlex.quote(name_filter)} -o '%i|%j|%T'")
        accounting_start = ""
        if submitted_after:
            aware_after = (submitted_after.replace(tzinfo=timezone.utc)
                           if submitted_after.tzinfo is None else submitted_after)
            timestamp = aware_after.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            accounting_start = f" --starttime={shlex.quote(timestamp)}"
        try:
            accounting = self._remote(
                f"sacct --noheader --parsable2 --name={shlex.quote(name_filter)}"
                f"{accounting_start} --format=JobIDRaw,JobName,State")
        except SlurmError as exc:
            logger.warning("Slurm accounting lookup unavailable during recovery.")
            raise SlurmError(
                "Slurm accounting lookup failed; submission cannot be retried safely."
            ) from exc
        for output in (accounting, active):
            for line in output.splitlines():
                fields = line.strip().split("|", 2)
                if len(fields) != 3:
                    continue
                job_id, job_name, raw_state = fields
                run_id = names.get(job_name.lower())
                if run_id and re.fullmatch(r"[0-9]+", job_id):
                    result[run_id][job_id] = self._map_state(raw_state)
        return result

    def result_bundles_exist(self, remote_dirs: list[str]) -> set[str]:
        paths = list(dict.fromkeys(self._validate_remote_path(path) for path in remote_dirs))
        if not paths:
            return set()
        directories = " ".join(shlex.quote(path) for path in paths)
        command = (
            f"for d in {directories}; do "
            "if test -s \"$d/results/result_bundle.zip\"; then printf '%s\\n' \"$d\"; fi; "
            "done"
        )
        return set(self._remote(command).splitlines())

    @staticmethod
    def _map_state(raw: str) -> str:
        state = re.split(r"[+\s]", raw.strip().upper(), maxsplit=1)[0]
        if state in {"PENDING", "CONFIGURING", "RESV_DEL_HOLD", "REQUEUED"}:
            return "PENDING"
        if state in {"RUNNING", "COMPLETING", "STAGE_OUT"}:
            return "RUNNING"
        if state == "COMPLETED":
            return "COMPLETED"
        if state in {"CANCELLED", "PREEMPTED", "REVOKED"}:
            return "CANCELLED"
        if state in {"TIMEOUT", "DEADLINE"}:
            return "TIMEOUT"
        if state in {"FAILED", "OUT_OF_MEMORY", "NODE_FAIL", "BOOT_FAIL"}:
            return "FAILED"
        return "UNKNOWN"

    def cancel(self, job_id: str) -> None:
        if not re.fullmatch(r"[0-9]+", job_id):
            raise SlurmError("Invalid Slurm job id.")
        self._remote(f"scancel {shlex.quote(job_id)}")

    def fetch_result(
        self,
        remote_dir: str,
        max_uncompressed_bytes: int,
        destination_dir: Path,
    ) -> RemoteResult:
        remote_dir = self._validate_remote_path(remote_dir)
        remote_archive = f"{remote_dir}/results/result_bundle.zip"
        try:
            raw_size = self._remote(
                f"if test -f {shlex.quote(remote_archive)}; then "
                f"wc -c < {shlex.quote(remote_archive)}; else printf MISSING; fi"
            ).strip()
        except SlurmError as exc:
            raise SlurmError("Could not determine the remote result bundle size.") from exc
        if raw_size == "MISSING":
            raise SlurmResultError("Completed job has no result bundle.")
        try:
            remote_size = int(raw_size)
        except ValueError as exc:
            raise SlurmResultError("Remote result bundle size is invalid.") from exc
        if remote_size <= 0 or remote_size > max_uncompressed_bytes + 1024 * 1024:
            raise SlurmResultError("Remote result bundle exceeds the configured download limit.")

        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SlurmError("Could not create local result staging directory.") from exc
        local_zip = destination_dir / "result_bundle.zip"
        self._run(["scp", *self._scp_options(),
                   f"{self.target}:{remote_archive}", str(local_zip)])
        try:
            local_size = local_zip.stat().st_size
        except OSError as exc:
            raise SlurmError("Downloaded result bundle is unavailable locally.") from exc
        if local_size != remote_size:
            raise SlurmError("Downloaded result bundle size does not match the remote file.")
        try:
            manifest, inspection_run, artifacts = extract_result_bundle(
                local_zip, destination_dir / "artifacts",
                max_uncompressed_bytes=max_uncompressed_bytes,
            )
        except BundleError as exc:
            raise SlurmResultError(f"Invalid result bundle: {exc}") from exc
        except OSError as exc:
            raise SlurmError("Could not stage downloaded result bundle locally.") from exc
        return RemoteResult(manifest, inspection_run, artifacts)
