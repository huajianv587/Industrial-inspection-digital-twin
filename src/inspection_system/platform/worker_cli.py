from __future__ import annotations

import logging
import signal
import time
import uuid
from .db import create_database
from .logging_config import configure_logging
from .heartbeat import record_worker_heartbeat
from .settings import Settings
from .slurm import SlurmClient
from .worker import InspectionWorker


def main() -> int:
    configure_logging()
    settings = Settings.from_env()
    settings.validate()
    engine, factory = create_database(
        settings.database_url, environment=settings.environment)
    slurm_client = SlurmClient(settings) if settings.executor_mode == "slurm" else None
    worker = InspectionWorker(factory, settings, slurm_client)
    instance_id = uuid.uuid4().hex
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    log = logging.getLogger(__name__)

    def heartbeat(state: str, error_type: str | None = None) -> None:
        try:
            record_worker_heartbeat(
                factory,
                instance_id=instance_id,
                execution_backend=settings.executor_mode,
                state=state,
                error_type=error_type,
            )
        except Exception:
            log.exception("Worker heartbeat could not be persisted.")

    heartbeat("starting")
    while not stopping:
        heartbeat("working")
        state = "idle"
        error_type = None
        try:
            worker.run_once()
        except Exception as exc:
            state = "degraded"
            error_type = type(exc).__name__
            log.exception("Worker iteration failed.")
        heartbeat(state, error_type)
        time.sleep(settings.slurm_poll_seconds)
    heartbeat("stopped")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
