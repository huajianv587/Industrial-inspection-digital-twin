from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .entities import WorkOrderRecord


@dataclass(frozen=True)
class EamWorkOrderRequest:
    ticket_id: str
    idempotency_key: str
    approval_decision: Literal["ACKNOWLEDGED"]
    reviewed_by: str
    reviewed_at: datetime
    review_comment: str
    payload_json: str


@dataclass(frozen=True)
class EamWorkOrderReceipt:
    external_id: str
    status: str
    submitted_at: datetime


class EamAdapter(Protocol):
    def submit_work_order(self, request: EamWorkOrderRequest) -> EamWorkOrderReceipt: ...


class EamAdapterError(RuntimeError):
    """An EAM submission failed without exposing credentials or response bodies."""


class HttpEamAdapter:
    """Dependency-free EAM client with a stable idempotency header."""

    def __init__(
        self,
        *,
        base_url: str,
        submit_path: str,
        api_key: str,
        timeout_seconds: float,
        opener=urlopen,
    ) -> None:
        self._url = base_url.rstrip("/") + submit_path
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def submit_work_order(self, request: EamWorkOrderRequest) -> EamWorkOrderReceipt:
        try:
            work_order = json.loads(request.payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise EamAdapterError("EAM work-order payload is not valid JSON.") from exc
        if not isinstance(work_order, dict):
            raise EamAdapterError("EAM work-order payload must be an object.")
        body = json.dumps({
            "ticket_id": request.ticket_id,
            "idempotency_key": request.idempotency_key,
            "approval_decision": request.approval_decision,
            "reviewed_by": request.reviewed_by,
            "reviewed_at": request.reviewed_at.isoformat(),
            "review_comment": request.review_comment,
            "work_order": work_order,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        http_request = Request(
            self._url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "Idempotency-Key": request.idempotency_key,
            },
        )
        try:
            with self._opener(http_request, timeout=self._timeout_seconds) as response:
                status_code = int(response.status)
                response_body = response.read(64 * 1024)
        except HTTPError as exc:
            raise EamAdapterError(f"EAM returned HTTP {exc.code}.") from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise EamAdapterError("EAM request failed before a response was received.") from exc
        if not 200 <= status_code < 300:
            raise EamAdapterError(f"EAM returned HTTP {status_code}.")
        try:
            decoded = json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EamAdapterError("EAM returned invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise EamAdapterError("EAM response must be a JSON object.")
        external_id = decoded.get("external_id")
        external_status = decoded.get("status")
        if (not isinstance(external_id, str) or not external_id.strip()
                or len(external_id) > 256
                or not isinstance(external_status, str) or not external_status.strip()
                or len(external_status) > 64):
            raise EamAdapterError("EAM response is missing a valid external_id or status.")
        return EamWorkOrderReceipt(
            external_id=external_id,
            status=external_status,
            submitted_at=datetime.now(request.reviewed_at.tzinfo),
        )


def build_eam_request(record: WorkOrderRecord) -> EamWorkOrderRequest:
    if (record.review_status != "REVIEWED"
            or record.review_decision != "ACKNOWLEDGED"
            or not record.reviewed_by
            or record.reviewed_at is None
            or not record.review_comment
            or len(record.review_comment.strip()) < 3):
        raise ValueError("EAM submission requires a recorded human acknowledgement.")
    reviewed_at = record.reviewed_at
    if reviewed_at.tzinfo is None:
        # SQLite's DateTime adapter drops timezone metadata. All timestamps are
        # written by this service from utc_now(), so normalize that representation
        # loss at the outbound boundary instead of changing the persisted audit value.
        reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
    elif reviewed_at.utcoffset() is None:
        raise ValueError("EAM review timestamp must include a timezone.")
    try:
        payload = json.loads(record.payload_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Work-order payload is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Work-order payload must be a JSON object.")

    return EamWorkOrderRequest(
        ticket_id=record.ticket_id,
        idempotency_key=record.ticket_id,
        approval_decision="ACKNOWLEDGED",
        reviewed_by=record.reviewed_by,
        reviewed_at=reviewed_at,
        review_comment=record.review_comment.strip(),
        payload_json=record.payload_json,
    )
