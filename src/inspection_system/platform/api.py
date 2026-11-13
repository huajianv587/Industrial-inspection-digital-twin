from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import tempfile
import time
import uuid
from typing import Any
import mimetypes

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy import Engine, and_, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import ConfigError, load_site_config
from ..industrial import industrial_readiness, load_industrial_site
from .auth import Actor, actor_from_request, require_roles
from .artifact_storage import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStorageError,
    create_artifact_storage,
)
from .db import create_database, get_session
from .entities import (
    ArtifactRecord, AuditEventRecord, EamSubmissionRecord, MissionRecord,
    ServiceHeartbeatRecord, WorkOrderRecord, utc_now,
)
from .eam import EamAdapter, EamAdapterError, HttpEamAdapter, build_eam_request
from .schemas import ArtifactView, MissionCreate, MissionView, ResultImport, WorkOrderReview
from .result_service import ResultValidationError, persist_inspection_result
from .settings import Settings

logger = logging.getLogger(__name__)
TERMINAL_MISSION_STATES = {
    "SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED", "TIMED_OUT", "RESULT_IMPORT_FAILED",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _encode_history_cursor(created_at: datetime, resource_id: str) -> str:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    payload = _json([created_at.isoformat(), resource_id]).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_history_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        if not 1 <= len(cursor) <= 512:
            raise ValueError
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(payload)
        if (not isinstance(value, list) or len(value) != 2
                or not isinstance(value[0], str) or not isinstance(value[1], str)
                or not 1 <= len(value[1]) <= 128):
            raise ValueError
        created_at = datetime.fromisoformat(value[0])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        return created_at, value[1]
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid history cursor.") from exc


def _fetch_history_page(
    session: Session,
    statement,
    *,
    created_at_column,
    id_column,
    limit: int,
    cursor: str | None,
    response: Response,
):
    if cursor:
        created_at, resource_id = _decode_history_cursor(cursor)
        statement = statement.where(or_(
            created_at_column < created_at,
            and_(created_at_column == created_at, id_column < resource_id),
        ))
    records = session.scalars(statement.order_by(
        desc(created_at_column), desc(id_column)).limit(limit + 1)).all()
    has_more = len(records) > limit
    records = records[:limit]
    if has_more and records:
        response.headers["X-Next-Cursor"] = _encode_history_cursor(
            records[-1].created_at, str(getattr(records[-1], id_column.key)))
    return records


def _mission_view(record: MissionRecord) -> MissionView:
    return MissionView(
        run_id=record.run_id,
        site_id=record.site_id,
        robot_id=record.robot_id,
        execution_backend=record.execution_backend,
        status=record.status,
        seed=record.seed,
        slurm_job_id=record.slurm_job_id,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        finished_at=record.finished_at,
    )


def _audit(session: Session, actor: Actor, event_type: str, resource_type: str,
           resource_id: str, payload: dict[str, Any]) -> None:
    session.add(AuditEventRecord(
        event_id=uuid.uuid4().hex,
        actor=actor.subject,
        actor_role=actor.role,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        payload_json=_json(payload),
    ))


def create_app(
    settings: Settings | None = None,
    *,
    engine_override: Engine | None = None,
    eam_adapter: EamAdapter | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_settings.validate(require_slurm_credentials=False)
    artifact_storage = create_artifact_storage(resolved_settings)
    resolved_eam_adapter = eam_adapter
    if resolved_eam_adapter is None and resolved_settings.eam_enabled:
        resolved_eam_adapter = HttpEamAdapter(
            base_url=resolved_settings.eam_base_url or "",
            submit_path=resolved_settings.eam_submit_path,
            api_key=resolved_settings.eam_api_key or "",
            timeout_seconds=resolved_settings.eam_timeout_seconds,
        )
    if engine_override is None:
        engine, session_factory = create_database(
            resolved_settings.database_url, environment=resolved_settings.environment)
    else:
        from sqlalchemy.orm import sessionmaker
        engine = engine_override
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    if resolved_settings.environment == "local_demo":
        # The local demo is intentionally self-contained: it has no migration
        # service or external database, so initialize its file-backed schema here.
        from .db import Base
        Base.metadata.create_all(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        artifact_storage.initialize()
        yield
        engine.dispose()

    app = FastAPI(
        title="Industrial Inspection Platform API",
        version="0.2.0",
        description="Mission orchestration, result provenance, and human-reviewed work orders.",
        lifespan=lifespan,
    )
    # The Vite frontend is served from a different Vercel domain than this
    # API, so browser calls need CORS preflight to succeed; without it every
    # dashboard request fails in the browser with "Failed to fetch".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://web-five-rosy-1dxmibo809.vercel.app",
            "https://web-37bn75i47-huajian.vercel.app",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = resolved_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.artifact_storage = artifact_storage
    app.state.eam_adapter = resolved_eam_adapter
    request_metrics: dict[tuple[str, str, int], dict[str, float]] = {}

    def _record_request_metric(method: str, path: str, status: int, duration_ms: float) -> None:
        item = request_metrics.setdefault(
            (method, path, status), {"count": 0.0, "duration_ms": 0.0})
        item["count"] += 1
        item["duration_ms"] += duration_ms

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", supplied) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            route = request.scope.get("route")
            path = getattr(route, "path", "__unmatched__")
            _record_request_metric(request.method, path, status, duration_ms)
            logger.info("HTTP request completed", extra={
                "request_id": request_id,
                "http_method": request.method,
                "http_path": path,
                "http_status": status,
                "duration_ms": duration_ms,
            })

    def session_dependency(request: Request):
        yield from get_session(request.app.state.session_factory)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        lines = [
            "# HELP inspection_http_requests_total Completed HTTP requests.",
            "# TYPE inspection_http_requests_total counter",
            "# HELP inspection_http_request_duration_ms_sum Total request duration in milliseconds.",
            "# TYPE inspection_http_request_duration_ms_sum counter",
        ]
        for (method, path, status), values in sorted(request_metrics.items()):
            labels = f'method="{method}",path="{path}",status="{status}"'
            lines.append(
                f"inspection_http_requests_total{{{labels}}} {values['count']:.0f}"
            )
            lines.append(
                f"inspection_http_request_duration_ms_sum{{{labels}}} "
                f"{values['duration_ms']:.3f}"
            )
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "inspection-api"}

    @app.get("/readyz")
    def readiness() -> dict[str, str]:
        try:
            with engine.connect() as connection:
                connection.execute(select(MissionRecord.run_id).limit(1))
        except Exception as exc:
            logger.warning("Readiness check failed: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
        database_name = "sqlite" if resolved_settings.environment == "local_demo" else "supabase"
        return {"status": "ready", "database": database_name}

    @app.get("/api/v1/dashboard")
    def dashboard(
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(actor_from_request),
    ) -> dict[str, Any]:
        _ = actor
        try:
            config = load_site_config(resolved_settings.site_config_path)
        except ConfigError as exc:
            raise HTTPException(status_code=503, detail="Site configuration is unavailable.") from exc
        mission_counts = dict(session.execute(
            select(MissionRecord.status, func.count()).group_by(MissionRecord.status)
        ).all())
        pending_orders = session.scalar(select(func.count()).select_from(WorkOrderRecord)
                                        .where(WorkOrderRecord.review_status == "PENDING")) or 0
        recent = session.scalars(select(MissionRecord).order_by(
            desc(MissionRecord.created_at)).limit(12)).all()
        heartbeat = session.get(ServiceHeartbeatRecord, "worker")
        worker_status = "not_seen"
        worker_last_seen = None
        worker_backend = None
        worker_instance = None
        worker_error_type = None
        if heartbeat:
            worker_last_seen = heartbeat.last_seen_at
            if worker_last_seen.tzinfo is None:
                worker_last_seen = worker_last_seen.replace(tzinfo=timezone.utc)
            age_seconds = max(
                0.0, (datetime.now(timezone.utc) - worker_last_seen).total_seconds())
            worker_status = (
                "stale" if age_seconds > resolved_settings.worker_heartbeat_stale_seconds
                else heartbeat.state
            )
            worker_backend = heartbeat.execution_backend
            worker_instance = heartbeat.instance_id
            worker_error_type = heartbeat.last_error_type
        return {
            "site": {"site_id": config["site_id"], "site_name": config["site_name"]},
            "robot": config["robot"],
            "execution_backend": resolved_settings.executor_mode,
            "eam_enabled": resolved_settings.eam_enabled,
            "mission_counts": mission_counts,
            "pending_work_orders": pending_orders,
            "recent_missions": [_mission_view(item).model_dump(mode="json") for item in recent],
            "worker": {
                "status": worker_status,
                "last_seen_at": worker_last_seen.isoformat() if worker_last_seen else None,
                "execution_backend": worker_backend,
                "instance_id": worker_instance,
                "last_error_type": worker_error_type,
            },
        }

    @app.get("/api/v1/sites")
    def get_site(actor: Actor = Depends(actor_from_request)) -> dict[str, Any]:
        _ = actor
        try:
            return load_site_config(resolved_settings.site_config_path)
        except ConfigError as exc:
            raise HTTPException(status_code=503, detail="Site configuration is unavailable.") from exc

    @app.get("/api/v1/industrial/site")
    def get_industrial_site(actor: Actor = Depends(actor_from_request)) -> dict[str, Any]:
        _ = actor
        try:
            config = load_industrial_site(resolved_settings.industrial_site_config_path)
        except ConfigError as exc:
            raise HTTPException(
                status_code=503,
                detail="Industrial site registry is unavailable or invalid.",
            ) from exc
        return {"site": config, "readiness": industrial_readiness(config)}

    @app.post("/api/v1/missions", response_model=MissionView, status_code=202)
    def create_mission(
        body: MissionCreate,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(require_roles("admin", "operator")),
    ) -> MissionView:
        if idempotency_key and (len(idempotency_key) > 128 or not idempotency_key.strip()):
            raise HTTPException(status_code=400, detail="Invalid Idempotency-Key.")
        try:
            config = load_site_config(resolved_settings.site_config_path)
        except ConfigError as exc:
            raise HTTPException(status_code=503, detail="Site configuration is unavailable.") from exc
        if body.site_id != config["site_id"]:
            raise HTTPException(status_code=422, detail="Unknown site_id.")
        all_waypoints = {item["waypoint_id"]: item for item in config["waypoints"]}
        if len(set(body.waypoint_ids)) != len(body.waypoint_ids):
            raise HTTPException(status_code=422, detail="waypoint_ids must be unique.")
        missing = [item for item in body.waypoint_ids if item not in all_waypoints]
        if missing:
            raise HTTPException(status_code=422, detail=f"Unknown waypoint_ids: {missing}")

        backend = resolved_settings.executor_mode
        if body.execution_backend is not None and body.execution_backend != backend:
            raise HTTPException(
                status_code=422,
                detail="execution_backend is controlled by deployment configuration.",
            )
        if backend != "offline" and body.render_backend != "none":
            raise HTTPException(
                status_code=422,
                detail="render_backend is available only for the local offline executor.",
            )
        if body.render_backend == "none" and (
            body.render_quality != "production" or body.render_resolution != 1280
        ):
            raise HTTPException(
                status_code=422,
                detail="render_quality and render_resolution require a rendered virtual world.",
            )
        if backend == "slurm" and resolved_settings.slurm_source == "isaac_sim":
            isaac_config = {
                "expected_version": resolved_settings.isaac_sim_version,
                "robot_usd_path": resolved_settings.isaac_robot_usd_path,
                "python_path": resolved_settings.isaac_sim_python,
                "adapter_entrypoint": resolved_settings.isaac_sim_adapter,
            }
            if any(not value for value in isaac_config.values()):
                raise HTTPException(
                    status_code=503,
                    detail="Isaac Sim execution is missing administrator runtime configuration.",
                )
            if resolved_settings.isaac_model_manifest_path:
                isaac_config["model"] = {
                    "manifest_path": resolved_settings.isaac_model_manifest_path,
                    "manifest_sha256": resolved_settings.isaac_model_manifest_sha256,
                    "artifact_sha256": resolved_settings.isaac_model_artifact_sha256,
                    "model_id": resolved_settings.isaac_model_id,
                    "model_version": resolved_settings.isaac_model_version,
                }
        else:
            isaac_config = None
        frozen_config = {**config, "waypoints": [all_waypoints[item] for item in body.waypoint_ids]}
        config_bytes = _json(frozen_config).encode("utf-8")
        config_hash = _hash(config_bytes)
        run_id = f"RUN-{uuid.uuid4().hex[:16].upper()}"
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "site_id": body.site_id,
            "robot_id": config["robot"]["robot_id"],
            "waypoint_ids": body.waypoint_ids,
            "seed": body.seed,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "synthetic_simulation" if backend == "offline" else resolved_settings.slurm_source,
            "execution_backend": backend,
            "render_backend": body.render_backend,
            "software_version": "0.2.0",
            "config_sha256": config_hash,
            "site_config": frozen_config,
        }
        if body.render_backend != "none":
            manifest["virtual_world"] = {
                "engine": "local_kinematic",
                "render_backend": body.render_backend,
            }
            if body.render_quality != "production":
                manifest["virtual_world"]["render_quality"] = body.render_quality
            if body.render_resolution != 1280:
                manifest["virtual_world"]["render_resolution"] = body.render_resolution
        if isaac_config is not None:
            manifest["simulator"] = isaac_config
        request_hash = _hash(_json({
            "site_id": body.site_id,
            "waypoint_ids": body.waypoint_ids,
            "seed": body.seed,
            "execution_backend": backend,
            "render_backend": body.render_backend,
            "render_quality": body.render_quality,
            "render_resolution": body.render_resolution,
        }).encode("utf-8"))
        if idempotency_key:
            existing = session.scalar(select(MissionRecord).where(
                MissionRecord.idempotency_key == idempotency_key))
            if existing:
                if existing.request_hash != request_hash:
                    raise HTTPException(status_code=409,
                                        detail="Idempotency-Key was already used for another request.")
                return _mission_view(existing)
        record = MissionRecord(
            run_id=run_id,
            site_id=body.site_id,
            robot_id=config["robot"]["robot_id"],
            execution_backend=backend,
            status="QUEUED",
            seed=body.seed,
            manifest_json=_json(manifest),
            request_hash=request_hash,
            idempotency_key=idempotency_key,
        )
        session.add(record)
        try:
            _audit(session, actor, "MISSION_CREATED", "mission", run_id,
                   {"backend": backend, "waypoint_ids": body.waypoint_ids})
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if idempotency_key:
                existing = session.scalar(select(MissionRecord).where(
                    MissionRecord.idempotency_key == idempotency_key))
                if existing and existing.request_hash == request_hash:
                    return _mission_view(existing)
            raise HTTPException(status_code=409, detail="Mission request conflicts with existing data.") from exc
        logger.info("Mission queued", extra={
            "run_id": run_id,
            "execution_backend": backend,
            "actor_id": actor.subject,
        })
        return _mission_view(record)

    @app.get("/api/v1/missions", response_model=list[MissionView])
    def list_missions(
        response: Response,
        limit: int = 50,
        cursor: str | None = None,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(actor_from_request),
    ) -> list[MissionView]:
        _ = actor
        if not 1 <= limit <= 200:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 200.")
        records = _fetch_history_page(
            session,
            select(MissionRecord),
            created_at_column=MissionRecord.created_at,
            id_column=MissionRecord.run_id,
            limit=limit,
            cursor=cursor,
            response=response,
        )
        return [_mission_view(item) for item in records]

    @app.get("/api/v1/missions/{run_id}")
    def get_mission(
        run_id: str,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(actor_from_request),
    ) -> dict[str, Any]:
        _ = actor
        record = session.get(MissionRecord, run_id)
        if not record:
            raise HTTPException(status_code=404, detail="Mission not found.")
        return {
            **_mission_view(record).model_dump(mode="json"),
            "manifest": json.loads(record.manifest_json),
            "result": json.loads(record.result_json) if record.result_json else None,
        }

    @app.get("/api/v1/missions/{run_id}/artifacts", response_model=list[ArtifactView])
    def list_mission_artifacts(
        run_id: str,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(actor_from_request),
    ) -> list[ArtifactView]:
        _ = actor
        if not session.get(MissionRecord, run_id):
            raise HTTPException(status_code=404, detail="Mission not found.")
        records = session.scalars(select(ArtifactRecord).where(
            ArtifactRecord.run_id == run_id,
        ).order_by(ArtifactRecord.name)).all()
        return [ArtifactView(
            artifact_id=item.artifact_id,
            run_id=item.run_id,
            name=item.name,
            sha256=item.sha256,
            size_bytes=item.size_bytes,
            source=item.source,
            created_at=item.created_at,
        ) for item in records]

    @app.post("/api/v1/missions/{run_id}/cancel", status_code=202)
    def cancel_mission(
        run_id: str,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(require_roles("admin", "operator")),
    ) -> MissionView:
        record = session.scalar(select(MissionRecord).where(
            MissionRecord.run_id == run_id).with_for_update())
        if not record:
            raise HTTPException(status_code=404, detail="Mission not found.")
        if record.status == "CANCELLING":
            return _mission_view(record)
        if record.status in TERMINAL_MISSION_STATES:
            raise HTTPException(status_code=409, detail=f"Mission is already {record.status}.")
        if record.status == "IMPORTING":
            raise HTTPException(status_code=409, detail="Mission results are already being imported.")
        if record.execution_backend == "slurm" and (
            record.slurm_job_id or record.status == "SUBMITTING"
        ):
            record.status = "CANCELLING"
            record.cancellation_target = "CANCELLED"
            record.error = None
            _audit(session, actor, "MISSION_CANCELLATION_REQUESTED", "mission", run_id,
                   {"job_id": record.slurm_job_id,
                    "submission_in_progress": record.slurm_job_id is None})
        elif record.execution_backend == "slurm" and record.status != "QUEUED":
            raise HTTPException(
                status_code=409,
                detail="Slurm job ID is unavailable; mission state requires reconciliation.",
            )
        else:
            record.status = "CANCELLED"
            record.cancellation_target = None
            record.finished_at = utc_now()
            _audit(session, actor, "MISSION_CANCELLED", "mission", run_id, {})
        session.commit()
        return _mission_view(record)

    @app.get("/api/v1/work-orders")
    def list_work_orders(
        response: Response,
        review_status: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(actor_from_request),
    ) -> list[dict[str, Any]]:
        _ = actor
        if not 1 <= limit <= 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500.")
        query = select(WorkOrderRecord)
        if review_status:
            query = query.where(WorkOrderRecord.review_status == review_status)
        if run_id:
            query = query.where(WorkOrderRecord.run_id == run_id)
        records = _fetch_history_page(
            session,
            query,
            created_at_column=WorkOrderRecord.created_at,
            id_column=WorkOrderRecord.ticket_id,
            limit=limit,
            cursor=cursor,
            response=response,
        )
        submission_by_ticket = {
            item.ticket_id: item
            for item in session.scalars(select(EamSubmissionRecord).where(
                EamSubmissionRecord.ticket_id.in_([item.ticket_id for item in records]))).all()
        }
        return [{
            "ticket_id": item.ticket_id,
            "run_id": item.run_id,
            "severity": item.severity,
            "review_status": item.review_status,
            "payload": json.loads(item.payload_json),
            "reviewed_by": item.reviewed_by,
            "review_decision": item.review_decision,
            "review_comment": item.review_comment,
            "created_at": item.created_at.isoformat(),
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
            "eam_submission": (
                {
                    "status": submission.status,
                    "attempts": submission.attempts,
                    "external_id": submission.external_id,
                    "submitted_at": submission.submitted_at.isoformat()
                    if submission.submitted_at else None,
                    "updated_at": submission.updated_at.isoformat(),
                }
                if (submission := submission_by_ticket.get(item.ticket_id)) is not None
                else None
            ),
        } for item in records]

    @app.post("/api/v1/work-orders/{ticket_id}/review")
    def review_work_order(
        ticket_id: str,
        body: WorkOrderReview,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(require_roles("admin", "reviewer")),
    ) -> dict[str, Any]:
        record = session.scalar(select(WorkOrderRecord).where(
            WorkOrderRecord.ticket_id == ticket_id).with_for_update())
        if not record:
            raise HTTPException(status_code=404, detail="Work order not found.")
        if record.review_status != "PENDING":
            raise HTTPException(status_code=409, detail="Work order has already been reviewed.")
        record.review_status = "REVIEWED" if body.decision == "ACKNOWLEDGED" else "DISMISSED"
        record.reviewed_by = actor.subject
        record.review_decision = body.decision
        record.review_comment = body.comment.strip()
        record.reviewed_at = utc_now()
        _audit(session, actor, "WORK_ORDER_REVIEWED", "work_order", ticket_id,
               {"decision": body.decision, "comment": body.comment.strip()})
        session.commit()
        return {"ticket_id": ticket_id, "review_status": record.review_status,
                "reviewed_by": record.reviewed_by, "reviewed_at": record.reviewed_at.isoformat()}

    @app.post("/api/v1/work-orders/{ticket_id}/eam")
    def submit_work_order_to_eam(
        ticket_id: str,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(require_roles("admin")),
    ) -> dict[str, Any]:
        adapter = resolved_eam_adapter
        if not resolved_settings.eam_enabled or adapter is None:
            raise HTTPException(status_code=503, detail="EAM integration is not enabled.")
        record = session.scalar(select(WorkOrderRecord).where(
            WorkOrderRecord.ticket_id == ticket_id).with_for_update())
        if not record:
            raise HTTPException(status_code=404, detail="Work order not found.")
        try:
            request_payload = build_eam_request(record)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        request_hash = _hash(_json({
            "ticket_id": request_payload.ticket_id,
            "reviewed_by": request_payload.reviewed_by,
            "reviewed_at": request_payload.reviewed_at.isoformat(),
            "review_comment": request_payload.review_comment,
            "payload_json": request_payload.payload_json,
        }).encode("utf-8"))
        submission = session.get(EamSubmissionRecord, ticket_id, with_for_update=True)
        if submission and submission.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="EAM request changed after submission state was recorded.",
            )
        if submission and submission.status == "SUBMITTED":
            _audit(session, actor, "EAM_SUBMISSION_REPLAYED", "work_order", ticket_id, {
                "external_id": submission.external_id,
                "idempotency_key": submission.idempotency_key,
            })
            session.commit()
            return {
                "ticket_id": ticket_id,
                "status": submission.status,
                "external_id": submission.external_id,
                "idempotent_replay": True,
            }
        if submission is None:
            submission = EamSubmissionRecord(
                ticket_id=ticket_id,
                idempotency_key=request_payload.idempotency_key,
                request_hash=request_hash,
                status="PENDING",
                attempts=0,
            )
            session.add(submission)
        submission.status = "PENDING"
        submission.request_hash = request_hash
        submission.last_error = None
        submission.attempts += 1
        submission.updated_at = utc_now()
        session.commit()
        try:
            receipt = adapter.submit_work_order(request_payload)
        except (EamAdapterError, OSError, TimeoutError) as exc:
            with session.begin():
                current = session.get(EamSubmissionRecord, ticket_id, with_for_update=True)
                if current is not None:
                    current.status = "FAILED"
                    current.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                    current.updated_at = utc_now()
                _audit(session, actor, "EAM_SUBMISSION_FAILED", "work_order", ticket_id, {
                    "error_type": type(exc).__name__,
                })
            raise HTTPException(
                status_code=502,
                detail="EAM submission failed; retry is safe.",
            ) from exc
        with session.begin():
            current = session.get(EamSubmissionRecord, ticket_id, with_for_update=True)
            if current is None:
                raise HTTPException(status_code=500, detail="EAM submission state disappeared.")
            current.status = "SUBMITTED"
            current.external_id = receipt.external_id
            current.response_json = _json({
                "external_id": receipt.external_id,
                "status": receipt.status,
                "submitted_at": receipt.submitted_at.isoformat(),
            })
            current.submitted_at = receipt.submitted_at
            current.updated_at = utc_now()
            _audit(session, actor, "EAM_SUBMISSION_SUCCEEDED", "work_order", ticket_id, {
                "external_id": receipt.external_id,
                "status": receipt.status,
                "idempotency_key": current.idempotency_key,
            })
        return {
            "ticket_id": ticket_id,
            "status": "SUBMITTED",
            "external_id": receipt.external_id,
            "idempotent_replay": False,
        }

    @app.post("/api/v1/missions/{run_id}/result", status_code=200)
    def import_result(
        run_id: str,
        body: ResultImport,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(require_roles("admin", "operator")),
    ) -> dict[str, Any]:
        record = session.scalar(select(MissionRecord).where(
            MissionRecord.run_id == run_id).with_for_update())
        if not record:
            raise HTTPException(status_code=404, detail="Mission not found.")
        if (record.status == "CANCELLING"
                or record.status in TERMINAL_MISSION_STATES
                and record.status not in {"SUCCEEDED", "PARTIAL"}):
            raise HTTPException(status_code=409,
                                detail=f"Mission is already {record.status}; result import is closed.")
        try:
            replay, incoming_hash = persist_inspection_result(
                session, record, body.manifest.model_dump(), body.inspection_run,
                artifact_storage,
            )
        except ResultValidationError as exc:
            session.rollback()
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except ArtifactStorageError as exc:
            session.rollback()
            raise HTTPException(status_code=503,
                                detail="Artifact storage is unavailable.") from exc
        _audit(session, actor, "MISSION_RESULT_IMPORTED", "mission", run_id,
               {"source": body.manifest.source, "result_sha256": incoming_hash,
                "artifact_count": len(body.manifest.artifacts), "idempotent_replay": replay})
        session.commit()
        return {"run_id": run_id, "status": record.status, "idempotent_replay": replay}

    @app.post("/api/v1/missions/{run_id}/artifacts/{name}", status_code=201)
    def upload_artifact(
        run_id: str,
        name: str,
        file: UploadFile = File(...),
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(require_roles("admin", "operator")),
    ) -> dict[str, Any]:
        _ = actor
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,255}", name) or name in {".", ".."}:
            raise HTTPException(status_code=400, detail="Invalid artifact name.")
        mission = session.get(MissionRecord, run_id)
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found.")
        existing = session.scalar(select(ArtifactRecord).where(
            ArtifactRecord.run_id == run_id, ArtifactRecord.name == name))
        if existing:
            raise HTTPException(status_code=409, detail="Artifact name is immutable once uploaded.")
        digest = hashlib.sha256()
        size = 0
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="inspection-upload-", delete=False) as target:
                temp_path = Path(target.name)
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > resolved_settings.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="Artifact exceeds upload limit.")
                    digest.update(chunk)
                    target.write(chunk)
            sha256 = digest.hexdigest()
            with temp_path.open("rb") as content_stream:
                storage_path = artifact_storage.put_file(
                    run_id, sha256, content_stream, size)
            record = ArtifactRecord(
                artifact_id=uuid.uuid4().hex,
                run_id=run_id,
                name=name,
                sha256=sha256,
                size_bytes=size,
                storage_path=storage_path,
                source=json.loads(mission.manifest_json)["source"],
            )
            session.add(record)
            session.commit()
            return {"artifact_id": record.artifact_id, "run_id": run_id, "name": name,
                    "sha256": sha256, "size_bytes": size}
        except HTTPException:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            raise
        except ArtifactStorageError as exc:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            session.rollback()
            raise HTTPException(status_code=503,
                                detail="Artifact storage is unavailable.") from exc
        except IntegrityError as exc:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            session.rollback()
            raise HTTPException(status_code=409,
                                detail="Artifact name is immutable once uploaded.") from exc
        except Exception:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            session.rollback()
            logger.exception("Artifact upload failed", extra={
                "run_id": run_id, "artifact_name": name,
            })
            raise HTTPException(status_code=500, detail="Artifact upload failed.")
        finally:
            file.file.close()

    @app.get("/api/v1/artifacts/{artifact_id}")
    def download_artifact(
        artifact_id: str,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(actor_from_request),
    ) -> FileResponse:
        _ = actor
        record = session.get(ArtifactRecord, artifact_id)
        if not record:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        if not artifact_storage.validate_reference(
                record.storage_path, record.run_id, record.sha256):
            raise HTTPException(status_code=404, detail="Artifact file is unavailable.")
        temp_path: Path | None = None
        try:
            digest = hashlib.sha256()
            size = 0
            with tempfile.NamedTemporaryFile(
                    prefix="inspection-download-", delete=False) as target:
                temp_path = Path(target.name)
                for chunk in artifact_storage.iter_bytes(record.storage_path):
                    size += len(chunk)
                    if size > min(record.size_bytes, resolved_settings.max_upload_bytes):
                        raise ArtifactIntegrityError(
                            "Stored artifact exceeds its recorded size.")
                    digest.update(chunk)
                    target.write(chunk)
            if size != record.size_bytes or digest.hexdigest() != record.sha256:
                raise ArtifactIntegrityError(
                    "Stored artifact failed its recorded size or SHA-256 check.")
            response = FileResponse(
                temp_path,
                media_type=mimetypes.guess_type(record.name)[0] or "application/octet-stream",
                filename=record.name,
                background=BackgroundTask(temp_path.unlink, missing_ok=True),
            )
            temp_path = None
            return response
        except ArtifactNotFoundError as exc:
            raise HTTPException(status_code=404,
                                detail="Artifact file is unavailable.") from exc
        except ArtifactIntegrityError as exc:
            logger.error("Artifact integrity check failed", extra={
                "artifact_id": artifact_id,
            })
            raise HTTPException(status_code=503,
                                detail="Artifact failed integrity validation.") from exc
        except ArtifactStorageError as exc:
            raise HTTPException(status_code=503,
                                detail="Artifact storage is unavailable.") from exc
        except OSError as exc:
            logger.exception("Artifact download staging failed", extra={
                "artifact_id": artifact_id,
            })
            raise HTTPException(status_code=503,
                                detail="Artifact download could not be staged.") from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @app.get("/api/v1/audit-events")
    def audit_events(
        response: Response,
        resource_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        session: Session = Depends(session_dependency),
        actor: Actor = Depends(require_roles("admin", "reviewer")),
    ) -> list[dict[str, Any]]:
        _ = actor
        if not 1 <= limit <= 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500.")
        query = select(AuditEventRecord)
        if resource_id:
            query = query.where(AuditEventRecord.resource_id == resource_id)
        records = _fetch_history_page(
            session,
            query,
            created_at_column=AuditEventRecord.created_at,
            id_column=AuditEventRecord.event_id,
            limit=limit,
            cursor=cursor,
            response=response,
        )
        return [{"event_id": item.event_id, "actor": item.actor, "actor_role": item.actor_role,
                 "event_type": item.event_type, "resource_type": item.resource_type,
                 "resource_id": item.resource_id, "payload": json.loads(item.payload_json),
                 "created_at": item.created_at.isoformat()} for item in records]

    return app
