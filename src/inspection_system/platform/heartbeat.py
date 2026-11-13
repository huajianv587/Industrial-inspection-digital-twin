from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session, sessionmaker

from .entities import ServiceHeartbeatRecord, utc_now


def record_worker_heartbeat(
    session_factory: sessionmaker[Session],
    *,
    instance_id: str,
    execution_backend: str,
    state: str,
    error_type: str | None = None,
    last_seen_at: datetime | None = None,
) -> None:
    with session_factory() as session:
        record = session.get(ServiceHeartbeatRecord, "worker")
        if record is None:
            record = ServiceHeartbeatRecord(
                service_name="worker",
                instance_id=instance_id,
                state=state,
                execution_backend=execution_backend,
                last_seen_at=last_seen_at or utc_now(),
                last_error_type=error_type,
            )
            session.add(record)
        else:
            record.instance_id = instance_id
            record.state = state
            record.execution_backend = execution_backend
            record.last_seen_at = last_seen_at or utc_now()
            record.last_error_type = error_type
        session.commit()
