from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from inspection_system.platform.api import create_app
from inspection_system.platform.db import Base, create_database
from inspection_system.platform.eam import (
    EamAdapterError,
    EamWorkOrderReceipt,
    HttpEamAdapter,
)
from inspection_system.platform.entities import (
    AuditEventRecord,
    EamSubmissionRecord,
    MissionRecord,
    WorkOrderRecord,
)
from inspection_system.platform.settings import Settings


class _Response:
    def __init__(self, body: bytes, status: int = 201) -> None:
        self.status = status
        self.body = body

    def read(self, _limit: int) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class EamHttpAdapterTests(unittest.TestCase):
    def test_sends_bounded_json_and_stable_idempotency_headers(self):
        captured: dict[str, object] = {}

        def opener(request, *, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.headers)
            captured["body"] = request.data
            captured["timeout"] = timeout
            return _Response(b'{"external_id":"EAM-42","status":"OPEN"}')

        adapter = HttpEamAdapter(
            base_url="https://eam.example.test",
            submit_path="/api/v1/work-orders",
            api_key="secret-not-for-logs",
            timeout_seconds=3.5,
            opener=opener,
        )
        reviewed_at = datetime(2026, 10, 26, tzinfo=timezone.utc)
        receipt = adapter.submit_work_order(type("Request", (), {
            "ticket_id": "WO-1",
            "idempotency_key": "WO-1",
            "approval_decision": "ACKNOWLEDGED",
            "reviewed_by": "reviewer@example.test",
            "reviewed_at": reviewed_at,
            "review_comment": "approved",
            "payload_json": json.dumps({"severity": "CRITICAL"}),
        })())

        self.assertEqual(receipt.external_id, "EAM-42")
        self.assertEqual(captured["url"], "https://eam.example.test/api/v1/work-orders")
        self.assertEqual(captured["timeout"], 3.5)
        headers = {str(key).lower(): value for key, value in captured["headers"].items()}
        self.assertEqual(headers["idempotency-key"], "WO-1")
        self.assertEqual(headers["authorization"], "Bearer secret-not-for-logs")
        body = json.loads(captured["body"])
        self.assertEqual(body["ticket_id"], "WO-1")
        self.assertEqual(body["work_order"]["severity"], "CRITICAL")

    def test_rejects_invalid_response_without_returning_body(self):
        adapter = HttpEamAdapter(
            base_url="https://eam.example.test",
            submit_path="/api/v1/work-orders",
            api_key="secret",
            timeout_seconds=1,
            opener=lambda _request, **_kwargs: _Response(b'{"unexpected":"value"}'),
        )
        with self.assertRaisesRegex(EamAdapterError, "missing a valid"):
            adapter.submit_work_order(type("Request", (), {
                "ticket_id": "WO-1",
                "idempotency_key": "WO-1",
                "approval_decision": "ACKNOWLEDGED",
                "reviewed_by": "reviewer",
                "reviewed_at": datetime.now(timezone.utc),
                "review_comment": "approved",
                "payload_json": "{}",
            })())


class EamApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="eam-api-test-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.settings = Settings(
            database_url="sqlite://",
            environment="test",
            auth_mode="development",
            artifact_dir=root / "artifacts",
            executor_mode="offline",
            eam_enabled=True,
            eam_base_url="https://eam.example.test",
            eam_api_key="test-api-key",
        )
        self.engine, self.factory = create_database("sqlite://", environment="test")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.adapter = _FakeEamAdapter()
        self.app = create_app(
            self.settings,
            engine_override=self.engine,
            eam_adapter=self.adapter,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)
        self.headers = {"X-Actor-Role": "admin"}
        self.ticket_id = "WO-EAM-001"
        with self.factory() as session:
            session.add(MissionRecord(
                run_id="RUN-EAM-001",
                site_id="SITE-TEST",
                robot_id="robot-01",
                execution_backend="offline",
                status="SUCCEEDED",
                seed=1,
                manifest_json="{}",
                request_hash="0" * 64,
            ))
            session.add(WorkOrderRecord(
                ticket_id=self.ticket_id,
                run_id="RUN-EAM-001",
                severity="CRITICAL",
                review_status="PENDING",
                payload_json=json.dumps({"ticket_id": self.ticket_id, "severity": "CRITICAL"}),
            ))
            session.commit()

    def test_requires_human_acknowledgement_before_submission(self):
        response = self.client.post(
            f"/api/v1/work-orders/{self.ticket_id}/eam",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.adapter.calls, [])

    def test_submission_is_durable_and_idempotent(self):
        reviewed = self.client.post(
            f"/api/v1/work-orders/{self.ticket_id}/review",
            json={"decision": "ACKNOWLEDGED", "comment": "approved for dispatch"},
            headers=self.headers,
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)

        first = self.client.post(
            f"/api/v1/work-orders/{self.ticket_id}/eam",
            headers=self.headers,
        )
        second = self.client.post(
            f"/api/v1/work-orders/{self.ticket_id}/eam",
            headers=self.headers,
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["idempotent_replay"])
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["idempotent_replay"])
        self.assertEqual(len(self.adapter.calls), 1)

        with self.factory() as session:
            submission = session.get(EamSubmissionRecord, self.ticket_id)
            self.assertIsNotNone(submission)
            self.assertEqual(submission.status, "SUBMITTED")
            self.assertEqual(submission.attempts, 1)
            self.assertEqual(submission.external_id, "EAM-WO-EAM-001")
            events = session.query(AuditEventRecord).filter_by(
                resource_id=self.ticket_id).all()
            self.assertEqual(
                {event.event_type for event in events},
                {"WORK_ORDER_REVIEWED", "EAM_SUBMISSION_SUCCEEDED", "EAM_SUBMISSION_REPLAYED"},
            )

        listed = self.client.get("/api/v1/work-orders", headers=self.headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["eam_submission"], {
            "status": "SUBMITTED",
            "attempts": 1,
            "external_id": "EAM-WO-EAM-001",
            "submitted_at": listed.json()[0]["eam_submission"]["submitted_at"],
            "updated_at": listed.json()[0]["eam_submission"]["updated_at"],
        })

    def test_failed_submission_can_be_retried_with_same_idempotency_key(self):
        self.client.post(
            f"/api/v1/work-orders/{self.ticket_id}/review",
            json={"decision": "ACKNOWLEDGED", "comment": "approved for retry"},
            headers=self.headers,
        )
        self.adapter.fail_next = True
        failed = self.client.post(
            f"/api/v1/work-orders/{self.ticket_id}/eam",
            headers=self.headers,
        )
        retried = self.client.post(
            f"/api/v1/work-orders/{self.ticket_id}/eam",
            headers=self.headers,
        )
        self.assertEqual(failed.status_code, 502, failed.text)
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(len(self.adapter.calls), 2)
        with self.factory() as session:
            submission = session.get(EamSubmissionRecord, self.ticket_id)
            self.assertEqual(submission.status, "SUBMITTED")
            self.assertEqual(submission.attempts, 2)


class _FakeEamAdapter:
    def __init__(self) -> None:
        self.calls = []
        self.fail_next = False

    def submit_work_order(self, request):
        self.calls.append(request)
        if self.fail_next:
            self.fail_next = False
            raise EamAdapterError("vendor temporarily unavailable")
        return EamWorkOrderReceipt(
            external_id=f"EAM-{request.ticket_id}",
            status="OPEN",
            submitted_at=datetime.now(timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
