from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import logging.config
from pathlib import Path
from typing import Any


_CONTEXT_FIELDS = (
    "run_id", "waypoint_id", "job_id", "execution_backend", "actor_id",
    "artifact_id", "artifact_name", "scheduler_state", "result_status", "error_type",
    "request_id", "http_method", "http_path", "http_status", "duration_ms",
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, timezone.utc)
        payload: dict[str, Any] = {
            "timestamp": timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def configure_logging(config_path: str | Path = "configs/logging.json") -> None:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    logging.config.dictConfig(config)
