from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import tempfile
from typing import Any
import uuid
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ..config import load_site_config, waypoints_from_config
from ..mission.orchestrator import MissionOrchestrator
from ..simulation import VirtualWorldRobotAdapter
from .artifact_store import store_artifact_bytes, store_artifact_file
from .artifact_storage import ArtifactStorage, ArtifactStorageError, create_artifact_storage
from .entities import AuditEventRecord, MissionRecord, utc_now
from .result_bundle import build_result_bundle, read_result_bundle
from .result_service import ResultValidationError, persist_inspection_result
from .settings import Settings
from .slurm import (
    RemoteResult, SlurmClient, SlurmError, SlurmResultError, SlurmSubmissionOutcomeUnknown,
)

logger = logging.getLogger(__name__)
TERMINAL_STATES = {
    "SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED", "TIMED_OUT", "RESULT_IMPORT_FAILED",
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class InspectionWorker:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings,
                 slurm_client: SlurmClient | Any | None = None,
                 artifact_storage: ArtifactStorage | None = None):
        self.session_factory = session_factory
        self.settings = settings
        self.slurm_client = slurm_client
        self.artifact_storage = artifact_storage or create_artifact_storage(settings)

    def run_once(self) -> int:
        recovered = self._recover_stale_submissions()
        retried_imports = self._retry_imports()
        submitted = self._submit_next()
        did_work = recovered or retried_imports or submitted
        if self.settings.executor_mode == "slurm":
            did_work = self._poll_slurm_jobs() or did_work
        return int(did_work)

    def _claim_queued(self) -> dict[str, Any] | None:
        with self.session_factory() as session:
            candidate = session.scalar(select(MissionRecord).where(
                MissionRecord.status == "QUEUED").order_by(MissionRecord.created_at).limit(1))
            if not candidate:
                return None
            result = session.execute(update(MissionRecord).where(
                MissionRecord.run_id == candidate.run_id,
                MissionRecord.status == "QUEUED",
            ).values(
                status="SUBMITTING",
                submission_attempts=MissionRecord.submission_attempts + 1,
                started_at=utc_now(),
                updated_at=utc_now(),
            ))
            session.commit()
            if result.rowcount != 1:
                return None
            return {"run_id": candidate.run_id,
                    "manifest": json.loads(candidate.manifest_json),
                    "backend": candidate.execution_backend}

    def _recover_stale_submissions(self) -> bool:
        now = utc_now()
        cutoff = now - timedelta(seconds=self.settings.submission_recovery_seconds)
        with self.session_factory() as session:
            records = session.scalars(select(MissionRecord).where(
                or_(
                    MissionRecord.status == "SUBMITTING",
                    and_(MissionRecord.status == "CANCELLING",
                         MissionRecord.slurm_job_id.is_(None)),
                ),
            ).order_by(MissionRecord.updated_at).limit(100)).all()
            stale = [{
                "run_id": item.run_id,
                "backend": item.execution_backend,
                "status": item.status,
                "started_at": item.started_at or item.created_at,
                "updated_at": item.updated_at,
                "submission_attempts": item.submission_attempts,
                "remote_dir": item.remote_dir or (
                    f"{self.settings.slurm_remote_root.rstrip('/')}/{item.run_id}"
                    if self.settings.slurm_remote_root else None),
            } for item in records if _aware(item.updated_at) <= cutoff]
        if not stale:
            return False

        did_work = False
        offline = [item for item in stale if item["backend"] == "offline"]
        for item in offline:
            did_work = self._requeue_stale_submission(item["run_id"], cutoff) or did_work

        slurm = [item for item in stale if item["backend"] == "slurm"]
        if not slurm:
            return did_work
        if self.slurm_client is None:
            for item in slurm:
                if item["status"] == "CANCELLING":
                    self._record_cancel_request_error(
                        item["run_id"], None, SlurmError("Slurm client unavailable"))
                else:
                    self._record_poll_error(
                        item["run_id"], "Slurm client unavailable during recovery.")
            return True

        try:
            # Batch accounting queries avoid one sacct RPC per abandoned mission.
            jobs_by_run = self.slurm_client.find_jobs_for_runs(
                [item["run_id"] for item in slurm],
                min(_aware(item["started_at"]) for item in slurm),
            )
            no_job = [item for item in slurm if not jobs_by_run.get(item["run_id"])]
            result_dirs = {
                item["remote_dir"] for item in no_job if item["remote_dir"]
            }
            result_dirs_present = self.slurm_client.result_bundles_exist(list(result_dirs))
        except Exception as exc:
            logger.exception("Stale Slurm submission reconciliation failed.")
            for item in slurm:
                if item["status"] == "CANCELLING":
                    self._record_cancel_request_error(item["run_id"], None, exc)
                else:
                    self._record_poll_error(item["run_id"], f"{type(exc).__name__}: {exc}")
            return True

        for item in slurm:
            run_id = item["run_id"]
            jobs = jobs_by_run.get(run_id, {})
            remote_dir = item["remote_dir"]
            if len(jobs) > 1:
                ids = ",".join(sorted(jobs))
                message = (
                    f"Multiple Slurm jobs match this mission ({ids}); "
                    "operator reconciliation is required."
                )
                if item["status"] == "CANCELLING":
                    self._record_cancel_request_error(
                        run_id, None, SlurmError(message))
                else:
                    self._fail_mission(run_id, "FAILED", message)
                did_work = True
            elif jobs:
                job_id, scheduler_state = next(iter(jobs.items()))
                self._bind_recovered_job(run_id, job_id, scheduler_state, remote_dir, cutoff)
                did_work = True
            elif remote_dir and remote_dir in result_dirs_present:
                if self._claim_recovered_import(run_id, remote_dir, cutoff):
                    self._import_slurm_result(run_id, remote_dir)
                    did_work = True
            elif item["status"] == "CANCELLING":
                self._confirm_absent_submission_cancellation(run_id, cutoff)
                did_work = True
            else:
                did_work = self._requeue_stale_submission(run_id, cutoff) or did_work
        return did_work

    def _requeue_stale_submission(self, run_id: str, cutoff: datetime) -> bool:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if (not record or record.status != "SUBMITTING"
                    or _aware(record.updated_at) > cutoff):
                return False
            if record.submission_attempts >= self.settings.submission_attempt_limit:
                record.status = "FAILED"
                record.error = "Submission recovery attempt limit reached."
                record.finished_at = utc_now()
                event = "MISSION_TERMINATED"
                payload = {"status": "FAILED", "error": record.error,
                           "submission_attempts": record.submission_attempts}
            else:
                record.status = "QUEUED"
                record.started_at = None
                record.error = "Recovered an abandoned submission; retry queued."
                event = "MISSION_SUBMISSION_RECOVERED"
                payload = {"status": "QUEUED",
                           "submission_attempts": record.submission_attempts}
            self._audit(session, event, run_id, payload)
            session.commit()
            return True

    def _bind_recovered_job(self, run_id: str, job_id: str, scheduler_state: str,
                            remote_dir: str | None, cutoff: datetime) -> None:
        status_map = {
            "PENDING": "PENDING", "RUNNING": "RUNNING", "COMPLETED": "SUBMITTED",
            "FAILED": "FAILED", "CANCELLED": "CANCELLED", "TIMEOUT": "TIMED_OUT",
        }
        status = status_map.get(scheduler_state, "SUBMITTED")
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if (not record or record.status not in {"SUBMITTING", "CANCELLING"}
                    or _aware(record.updated_at) > cutoff):
                return
            record.slurm_job_id = job_id
            record.remote_dir = remote_dir
            if record.status == "CANCELLING":
                if status == "CANCELLED":
                    record.status = record.cancellation_target or "CANCELLED"
                    record.cancellation_target = None
                    record.finished_at = utc_now()
                elif status in {"FAILED", "TIMED_OUT"}:
                    record.status = status
                    record.cancellation_target = None
                    record.finished_at = utc_now()
                else:
                    record.cancellation_target = record.cancellation_target or "CANCELLED"
            else:
                record.status = status
            final_status = record.status
            record.error = (
                f"Recovered Slurm job ended in state {scheduler_state}."
                if final_status in {"FAILED", "TIMED_OUT"} else None
            )
            if final_status in TERMINAL_STATES:
                record.finished_at = utc_now()
            self._audit(session, "SLURM_JOB_RECOVERED", run_id,
                        {"job_id": job_id, "scheduler_state": scheduler_state,
                         "status": final_status})
            session.commit()

    def _claim_recovered_import(self, run_id: str, remote_dir: str,
                                cutoff: datetime) -> bool:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if (not record or record.status not in {"SUBMITTING", "CANCELLING"}
                    or _aware(record.updated_at) > cutoff):
                return False
            record.remote_dir = remote_dir
            record.status = "IMPORTING"
            record.cancellation_target = None
            self._audit(session, "SLURM_RESULT_RECOVERED", run_id,
                        {"remote_dir": remote_dir})
            session.commit()
            return True

    def _confirm_absent_submission_cancellation(self, run_id: str,
                                                cutoff: datetime) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if (not record or record.status != "CANCELLING"
                    or record.slurm_job_id is not None
                    or _aware(record.updated_at) > cutoff):
                return
            target = record.cancellation_target or "CANCELLED"
            record.status = target
            record.cancellation_target = None
            record.finished_at = utc_now()
            record.error = None
            self._audit(session, "SLURM_CANCELLATION_CONFIRMED_NO_JOB", run_id,
                        {"status": target})
            session.commit()

    def _submit_next(self) -> bool:
        claim = self._claim_queued()
        if claim is None:
            return False
        run_id = claim["run_id"]
        submission_accepted = False
        try:
            if claim["backend"] == "offline":
                self._run_offline(claim["manifest"])
            elif claim["backend"] == "slurm":
                if self.slurm_client is None:
                    raise SlurmError("Slurm client is not configured.")
                submission = self.slurm_client.submit(claim["manifest"])
                submission_accepted = True
                job_id, remote_dir = submission
                self._bind_submitted_job(run_id, job_id, remote_dir)
            else:
                raise ValueError(f"Unsupported mission backend: {claim['backend']}")
        except Exception as exc:
            logger.exception("Mission submission failed", extra={"run_id": run_id})
            if (claim["backend"] == "slurm"
                    and (isinstance(exc, SlurmSubmissionOutcomeUnknown)
                         or submission_accepted)):
                unknown = exc if isinstance(exc, SlurmSubmissionOutcomeUnknown) else \
                    SlurmSubmissionOutcomeUnknown(
                        "Slurm accepted the job but its local binding was not confirmed.")
                self._record_submission_outcome_unknown(run_id, unknown)
            elif isinstance(exc, (ArtifactStorageError, SQLAlchemyError)):
                self._record_import_retry_error(run_id, exc)
            else:
                self._fail_mission(run_id, "FAILED", f"{type(exc).__name__}: {exc}")
        return True

    def _record_submission_outcome_unknown(
        self, run_id: str, error: SlurmSubmissionOutcomeUnknown,
    ) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if not record or record.status not in {"SUBMITTING", "CANCELLING"}:
                return
            record.error = (
                "Slurm submission response was lost; scheduler reconciliation is pending."
            )
            self._audit(session, "SLURM_SUBMISSION_OUTCOME_UNKNOWN", run_id,
                        {"error_type": type(error).__name__,
                         "cancellation_pending": record.status == "CANCELLING"})
            session.commit()

    def _bind_submitted_job(self, run_id: str, job_id: str, remote_dir: str) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if not record:
                raise RuntimeError("Mission disappeared after Slurm accepted the job.")
            previous_status = record.status
            cancellation_pending = previous_status == "CANCELLING"
            if previous_status in TERMINAL_STATES:
                cancellation_pending = True
                record.cancellation_target = (
                    previous_status if previous_status in {"CANCELLED", "FAILED", "TIMED_OUT"}
                    else "FAILED"
                )
                record.error = (
                    f"Slurm job was submitted after mission entered {previous_status}; "
                    "cancellation is pending."
                )
                self._audit(session, "SLURM_ORPHAN_JOB_CANCELLATION_REQUIRED", run_id,
                            {"job_id": job_id, "previous_status": previous_status})
            record.slurm_job_id = job_id
            record.remote_dir = remote_dir
            record.status = "CANCELLING" if cancellation_pending else "SUBMITTED"
            if not cancellation_pending:
                record.cancellation_target = None
                record.error = None
            elif record.cancellation_target is None:
                record.cancellation_target = "CANCELLED"
            self._audit(session, "SLURM_JOB_SUBMITTED", run_id,
                        {"job_id": job_id, "remote_dir": remote_dir})
            session.commit()

    def _run_offline(self, manifest: dict[str, Any]) -> None:
        config = manifest.get("site_config")
        if not isinstance(config, dict):
            raise ValueError("Mission manifest has no site_config.")
        with tempfile.TemporaryDirectory(prefix="inspection-worker-") as temp_dir:
            root = Path(temp_dir)
            config_path = root / "site.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            loaded = load_site_config(config_path)
            waypoints = waypoints_from_config(loaded)
            if manifest.get("waypoint_ids") != [item.waypoint_id for item in waypoints]:
                raise ValueError("Frozen waypoint order does not match manifest.")
            virtual_world = manifest.get("virtual_world") or {}
            render_backend = virtual_world.get("render_backend", "none")
            if render_backend == "none":
                adapter = None
            elif render_backend in {"svg", "blender", "auto"}:
                adapter = VirtualWorldRobotAdapter(
                    site_id=manifest["site_id"],
                    robot_id=manifest["robot_id"],
                    waypoints=waypoints,
                    output_dir=root / "output",
                    seed=manifest["seed"],
                    render_backend=render_backend,
                    render_quality=virtual_world.get("render_quality", "production"),
                    render_resolution=virtual_world.get("render_resolution", 1280),
                )
            else:
                raise ValueError("Mission virtual_world.render_backend is invalid.")
            run = MissionOrchestrator(
                site_id=manifest["site_id"],
                robot_id=manifest["robot_id"],
                waypoints=waypoints,
                adapter=adapter,
                run_id=manifest["run_id"],
            ).run(root / "output")
            additional_artifacts = getattr(adapter, "additional_artifacts", None)
            bundle_path = build_result_bundle(
                root / "output", run, manifest["config_sha256"],
                additional_artifacts=additional_artifacts,
            )
            result_manifest, inspection_run, artifacts = read_result_bundle(bundle_path)
            self._persist_bundle(manifest["run_id"], result_manifest, inspection_run, artifacts)

    def _retry_imports(self) -> bool:
        cutoff = utc_now() - timedelta(seconds=self.settings.result_import_retry_seconds)
        with self.session_factory() as session:
            records = session.scalars(select(MissionRecord).where(
                MissionRecord.status == "IMPORTING",
                MissionRecord.updated_at <= cutoff,
            ).order_by(MissionRecord.updated_at).limit(100)).all()
            imports = [{
                "run_id": record.run_id,
                "backend": record.execution_backend,
                "manifest": json.loads(record.manifest_json),
                "remote_dir": record.remote_dir,
            } for record in records]
        for item in imports:
            run_id = item["run_id"]
            if item["backend"] == "offline":
                try:
                    self._run_offline(item["manifest"])
                except (ArtifactStorageError, SQLAlchemyError) as exc:
                    self._record_import_retry_error(run_id, exc)
                except Exception as exc:
                    logger.exception("Offline result import failed", extra={"run_id": run_id})
                    self._fail_mission(run_id, "RESULT_IMPORT_FAILED",
                                       f"{type(exc).__name__}: {exc}")
            elif item["backend"] == "slurm" and item["remote_dir"]:
                self._import_slurm_result(run_id, item["remote_dir"])
            else:
                self._record_import_retry_error(run_id, SlurmError("Result location unavailable"))
        return bool(imports)

    def _import_slurm_result(self, run_id: str, remote_dir: str) -> None:
        if self.slurm_client is None:
            self._record_import_retry_error(run_id, SlurmError("Slurm client unavailable"))
            return
        try:
            with tempfile.TemporaryDirectory(prefix="inspection-result-") as temp_dir:
                remote: RemoteResult = self.slurm_client.fetch_result(
                    remote_dir, self.settings.max_upload_bytes, Path(temp_dir))
                self._persist_bundle(run_id, remote.manifest,
                                     remote.inspection_run, remote.artifacts)
        except SlurmResultError as exc:
            logger.error("Completed Slurm job returned an invalid result",
                         extra={"run_id": run_id, "error_type": type(exc).__name__})
            self._fail_mission(run_id, "RESULT_IMPORT_FAILED", str(exc))
        except (ArtifactStorageError, SlurmError, SQLAlchemyError) as exc:
            logger.warning("Result import retry pending", extra={
                "run_id": run_id, "error_type": type(exc).__name__,
            })
            self._record_import_retry_error(run_id, exc)
        except Exception as exc:
            logger.exception("Slurm result import failed", extra={"run_id": run_id})
            self._fail_mission(run_id, "RESULT_IMPORT_FAILED",
                               f"{type(exc).__name__}: {exc}")

    def _record_import_retry_error(self, run_id: str, error: Exception) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if not record or record.status in TERMINAL_STATES:
                return
            if record.status not in {"SUBMITTING", "IMPORTING"}:
                return
            message = f"Result import retry pending: {type(error).__name__}."
            record.status = "IMPORTING"
            record.cancellation_target = None
            record.updated_at = utc_now()
            if record.error != message:
                record.error = message
                self._audit(session, "MISSION_RESULT_IMPORT_RETRY_PENDING", run_id,
                            {"error_type": type(error).__name__})
            session.commit()

    def _poll_slurm_jobs(self) -> bool:
        if self.slurm_client is None:
            return False
        with self.session_factory() as session:
            active = session.scalars(select(MissionRecord).where(
                MissionRecord.execution_backend == "slurm",
                MissionRecord.status.in_(
                    ("SUBMITTED", "PENDING", "RUNNING", "CANCELLING")),
            ).order_by(MissionRecord.created_at).limit(100)).all()
            records = [{"run_id": item.run_id, "job_id": item.slurm_job_id,
                        "remote_dir": item.remote_dir, "started_at": item.started_at,
                        "poll_failures": item.poll_failures, "status": item.status}
                       for item in active if item.slurm_job_id and item.remote_dir]
        did_work = False
        for item in records:
            did_work = self._poll_one(item) or did_work
        return did_work

    def _poll_one(self, mission: dict[str, Any]) -> bool:
        run_id = mission["run_id"]
        if mission.get("status") == "CANCELLING":
            job_id = mission["job_id"]
            try:
                state = self.slurm_client.status(job_id)
            except Exception as exc:
                logger.exception("Slurm state check during cancellation failed",
                                 extra={"run_id": run_id, "job_id": job_id})
                self._record_cancel_request_error(run_id, job_id, exc)
                return True
            if state == "CANCELLED":
                self._confirm_cancel_request(run_id, job_id)
                return True
            if state == "COMPLETED":
                with self.session_factory() as session:
                    claim = session.execute(update(MissionRecord).where(
                        MissionRecord.run_id == run_id,
                        MissionRecord.status == "CANCELLING",
                    ).values(status="IMPORTING", cancellation_target=None,
                             updated_at=utc_now()))
                    if claim.rowcount == 1:
                        self._audit(session, "MISSION_CANCELLATION_RACED_WITH_COMPLETION", run_id,
                                    {"job_id": job_id})
                    session.commit()
                if claim.rowcount != 1:
                    return False
                self._import_slurm_result(run_id, mission["remote_dir"])
                return True
            if state in {"FAILED", "TIMEOUT"}:
                target = "TIMED_OUT" if state == "TIMEOUT" else "FAILED"
                self._fail_mission(
                    run_id, target,
                    f"Slurm job ended in state {state} before cancellation was confirmed.",
                )
                return True
            try:
                self.slurm_client.cancel(job_id)
            except Exception as exc:
                logger.exception("Slurm cancellation request failed",
                                 extra={"run_id": run_id, "job_id": job_id})
                self._record_cancel_request_error(run_id, job_id, exc)
            else:
                self._clear_cancel_request_error(run_id)
            return True

        started_at = mission["started_at"] or datetime.now(timezone.utc)
        if (datetime.now(timezone.utc) - _aware(started_at)).total_seconds() > self.settings.mission_timeout_seconds:
            self._begin_cancellation(
                run_id,
                target="TIMED_OUT",
                reason="Mission exceeded configured timeout; scheduler cancellation is pending.",
                event_type="MISSION_TIMEOUT_CANCELLATION_REQUESTED",
                payload={"job_id": mission["job_id"]},
            )
            return True
        try:
            state = self.slurm_client.status(mission["job_id"])
            if state in {"PENDING", "RUNNING"}:
                with self.session_factory() as session:
                    record = session.scalar(select(MissionRecord).where(
                        MissionRecord.run_id == run_id).with_for_update())
                    if record and record.status in {"SUBMITTED", "PENDING", "RUNNING"}:
                        record.status = state
                        record.poll_failures = 0
                        record.error = None
                        session.commit()
                return True
            if state == "COMPLETED":
                with self.session_factory() as session:
                    claim = session.execute(update(MissionRecord).where(
                        MissionRecord.run_id == run_id,
                        MissionRecord.status.in_(["SUBMITTED", "PENDING", "RUNNING"]),
                    ).values(status="IMPORTING", updated_at=utc_now()))
                    session.commit()
                if claim.rowcount != 1:
                    return False
                self._import_slurm_result(run_id, mission["remote_dir"])
                return True
            if state in {"FAILED", "CANCELLED", "TIMEOUT"}:
                target = "TIMED_OUT" if state == "TIMEOUT" else state
                self._fail_mission(run_id, target, f"Slurm job ended in state {state}.")
                return True
            self._record_poll_error(run_id, f"Unexpected Slurm state: {state}")
        except Exception as exc:
            self._record_poll_error(run_id, f"{type(exc).__name__}: {exc}")
        return False

    def _persist_bundle(self, run_id: str, manifest: dict[str, Any],
                        inspection_run: dict[str, Any],
                        artifacts: dict[str, bytes | Path]) -> None:
        with self.session_factory() as session:
            try:
                record = session.scalar(select(MissionRecord).where(
                    MissionRecord.run_id == run_id).with_for_update())
                if not record:
                    raise ValueError("Mission disappeared before result import.")
                if (record.status == "CANCELLING"
                        or record.status in TERMINAL_STATES
                        and record.status not in {"SUCCEEDED", "PARTIAL"}):
                    raise ResultValidationError(
                        f"Mission is already {record.status}; late results are rejected.")
                source = manifest.get("source", "unknown")
                descriptors = manifest.get("artifacts")
                descriptors_by_name = {
                    item.get("name"): item for item in descriptors
                    if isinstance(item, dict)
                } if isinstance(descriptors, list) else {}
                for name, content in artifacts.items():
                    if isinstance(content, bytes):
                        store_artifact_bytes(session, self.artifact_storage, run_id,
                                             name, content, source)
                        continue
                    descriptor = descriptors_by_name.get(name)
                    if (not isinstance(content, Path) or not isinstance(descriptor, dict)
                            or not isinstance(descriptor.get("sha256"), str)
                            or isinstance(descriptor.get("size_bytes"), bool)
                            or not isinstance(descriptor.get("size_bytes"), int)):
                        raise ValueError(f"Artifact file metadata is invalid: {name}.")
                    with content.open("rb") as stream:
                        store_artifact_file(
                            session,
                            self.artifact_storage,
                            run_id,
                            name,
                            stream,
                            descriptor["sha256"],
                            descriptor["size_bytes"],
                            source,
                        )
                replay, digest = persist_inspection_result(
                    session, record, manifest, inspection_run, self.artifact_storage)
                self._audit(session, "MISSION_RESULT_IMPORTED", run_id,
                            {"result_hash": digest, "idempotent_replay": replay,
                             "source": source, "status": record.status})
                session.commit()
            except Exception:
                session.rollback()
                raise

    def _record_cancel_request_error(self, run_id: str, job_id: str | None,
                                     error: Exception) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if record and record.status == "CANCELLING":
                subject = f"job {job_id}" if job_id else "submission reconciliation"
                message = (
                    f"Slurm cancellation retry pending for {subject}: "
                    f"{type(error).__name__}."
                )
                if record.error != message:
                    record.error = message
                    event_type = (
                        "SLURM_CANCELLATION_ATTEMPT_FAILED" if job_id
                        else "SLURM_CANCELLATION_RECONCILIATION_FAILED"
                    )
                    self._audit(session, event_type, run_id,
                                {"job_id": job_id, "error": message})
                    session.commit()

    def _clear_cancel_request_error(self, run_id: str) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if record and record.status == "CANCELLING" and record.error is not None:
                record.error = None
                session.commit()

    def _confirm_cancel_request(self, run_id: str, job_id: str) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if not record or record.status != "CANCELLING":
                return
            target = record.cancellation_target or "CANCELLED"
            record.status = target
            record.cancellation_target = None
            record.finished_at = utc_now()
            record.error = None
            self._audit(session, "SLURM_CANCELLATION_CONFIRMED", run_id,
                        {"job_id": job_id, "status": target})
            session.commit()

    def _begin_cancellation(self, run_id: str, *, target: str, reason: str,
                            event_type: str, payload: dict[str, Any]) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if not record or record.status in TERMINAL_STATES:
                return
            if record.status == "CANCELLING":
                return
            record.status = "CANCELLING"
            record.cancellation_target = target
            record.error = reason
            self._audit(session, event_type, run_id,
                        {**payload, "target_status": target})
            session.commit()

    def _record_poll_error(self, run_id: str, message: str) -> None:
        scheduler_without_id = False
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if not record or record.status in TERMINAL_STATES:
                return
            if record.status == "CANCELLING":
                if record.slurm_job_id:
                    cancel_error = (
                        "Scheduler state check failed while cancellation was pending: "
                        + message[-500:]
                    )
                    if record.error != cancel_error:
                        record.error = cancel_error
                        self._audit(session, "SLURM_CANCELLATION_ATTEMPT_FAILED", run_id,
                                    {"job_id": record.slurm_job_id,
                                     "error": cancel_error})
                        session.commit()
                return
            if record.status not in {"SUBMITTING", "SUBMITTED", "PENDING", "RUNNING"}:
                return
            record.poll_failures += 1
            record.error = message[-2000:]
            if record.status == "SUBMITTING" and record.execution_backend == "slurm":
                if record.poll_failures == 10:
                    record.error = (
                        "Slurm submission reconciliation is unavailable; automatic retry is "
                        "paused to avoid a duplicate job. " + record.error
                    )[-2000:]
                    self._audit(session, "SLURM_RECONCILIATION_REQUIRED", run_id,
                                {"error": record.error,
                                 "poll_failures": record.poll_failures})
                session.commit()
                return
            if record.poll_failures >= 10:
                if record.execution_backend == "slurm" and record.slurm_job_id:
                    record.status = "CANCELLING"
                    record.cancellation_target = "FAILED"
                    record.error = (
                        "Scheduler polling failed repeatedly; cancellation is pending. "
                        + record.error
                    )[-2000:]
                    self._audit(session, "SLURM_CANCELLATION_REQUESTED_AFTER_POLL_FAILURES",
                                run_id, {"job_id": record.slurm_job_id,
                                         "poll_failures": record.poll_failures,
                                         "error": record.error})
                else:
                    record.status = "FAILED"
                    record.cancellation_target = None
                    record.finished_at = utc_now()
                    if record.execution_backend == "slurm":
                        scheduler_without_id = True
                        record.error += " Scheduler job ID is unknown; check for an orphaned job."
                    self._audit(session, "MISSION_TERMINATED", run_id,
                                {"status": "FAILED", "error": record.error,
                                 "poll_failures": record.poll_failures})
            session.commit()
        if scheduler_without_id:
            self._audit_reconciliation_required(
                run_id, "Repeated scheduler polling failures left no known job ID.")

    def _fail_mission(self, run_id: str, state: str, message: str) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if not record or record.status in TERMINAL_STATES:
                return
            record.status = state
            record.cancellation_target = None
            record.error = message[-2000:]
            record.finished_at = utc_now()
            self._audit(session, "MISSION_TERMINATED", run_id,
                        {"status": state, "error": record.error})
            session.commit()

    def _audit_reconciliation_required(self, run_id: str, message: str) -> None:
        with self.session_factory() as session:
            record = session.scalar(select(MissionRecord).where(
                MissionRecord.run_id == run_id).with_for_update())
            if not record or record.status != "FAILED":
                return
            record.error = f"{record.error or ''} {message}".strip()
            self._audit(session, "SLURM_RECONCILIATION_REQUIRED", run_id,
                        {"error": record.error})
            session.commit()

    @staticmethod
    def _audit(session: Session, event_type: str, run_id: str,
               payload: dict[str, Any]) -> None:
        session.add(AuditEventRecord(
            event_id=uuid.uuid4().hex,
            actor="inspection-worker",
            actor_role="system",
            event_type=event_type,
            resource_type="mission",
            resource_id=run_id,
            payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ))
