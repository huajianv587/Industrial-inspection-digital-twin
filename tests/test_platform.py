from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from inspection_system.config import waypoints_from_config
from inspection_system.mission.orchestrator import MissionOrchestrator
from inspection_system.models import InspectionRun, Observation, WaypointResult
from inspection_system.perception.rules import RuleBasedDiagnosticEngine
from inspection_system.platform.api import create_app
from inspection_system.platform.db import Base, create_database
from inspection_system.platform.entities import (
    ArtifactRecord, AuditEventRecord, MissionRecord, ServiceHeartbeatRecord,
    WorkOrderRecord, utc_now,
)
from inspection_system.platform.heartbeat import record_worker_heartbeat
from inspection_system.platform.result_bundle import (
    build_result_bundle,
    extract_result_bundle,
    read_result_bundle,
)
from inspection_system.platform.settings import Settings
from inspection_system.platform.result_service import ResultValidationError
from inspection_system.platform.slurm import (
    RemoteResult,
    SlurmError,
    SlurmResultError,
    SlurmSubmissionOutcomeUnknown,
)
from inspection_system.platform.worker import InspectionWorker


class SettingsTests(unittest.TestCase):
    def test_local_database_is_rejected_outside_tests(self):
        settings = Settings(database_url="sqlite://", environment="production")
        with self.assertRaisesRegex(ValueError, "SQLite is test-only"):
            settings.validate_database()

    def test_non_supabase_postgres_is_rejected(self):
        settings = Settings(database_url="postgresql://user:pass@localhost/db")
        with self.assertRaisesRegex(ValueError, "Supabase-managed"):
            settings.validate_database()

    def test_supabase_postgres_is_normalized_to_tls_psycopg(self):
        settings = Settings(database_url=(
            "postgresql://postgres:pass@db.project-ref.supabase.co/postgres?sslmode=disable"))
        normalized = settings.sqlalchemy_database_url()
        self.assertEqual(normalized.drivername, "postgresql+psycopg")
        self.assertEqual(normalized.query["sslmode"], "verify-full")

    def test_runtime_does_not_fall_back_to_migration_owner_url(self):
        environment = {
            "APP_ENV": "production",
            "SUPABASE_DB_URL": "postgresql://postgres:pass@db.project-ref.supabase.co/postgres",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()
        with self.assertRaisesRegex(ValueError, "Supabase PostgreSQL connection URL is required"):
            settings.validate_database()

    def test_production_rejects_offline_synthetic_executor(self):
        settings = Settings(
            database_url="postgresql://inspection_app:pass@db.project-ref.supabase.co/postgres",
            environment="production",
        )
        with self.assertRaisesRegex(ValueError, "Production requires INSPECTION_EXECUTOR=slurm"):
            settings.validate()

    def test_production_rejects_synthetic_slurm_source(self):
        settings = Settings(
            database_url="postgresql://inspection_app:pass@db.project-ref.supabase.co/postgres",
            environment="production",
            executor_mode="slurm",
            slurm_source="synthetic_simulation",
        )
        with self.assertRaisesRegex(ValueError, "Production requires SLURM_RESULT_SOURCE=isaac_sim"):
            settings.validate()

    def test_development_allows_explicit_offline_execution(self):
        settings = Settings(
            database_url="postgresql://inspection_app:pass@db.project-ref.supabase.co/postgres",
            environment="development",
            auth_mode="development",
            executor_mode="offline",
        )
        settings.validate()

    def test_local_demo_allows_explicit_file_backed_sqlite(self):
        settings = Settings(
            database_url="sqlite:////tmp/inspection-local-demo.db",
            environment="local_demo",
            auth_mode="development",
            executor_mode="offline",
            artifact_storage_backend="local",
            slurm_source="synthetic_simulation",
        )
        settings.validate()

    def test_local_demo_rejects_in_memory_sqlite(self):
        settings = Settings(
            database_url="sqlite://",
            environment="local_demo",
            auth_mode="development",
            executor_mode="offline",
            artifact_storage_backend="local",
            slurm_source="synthetic_simulation",
        )
        with self.assertRaisesRegex(ValueError, "file-backed SQLite"):
            settings.validate_database()

    def test_api_validates_isaac_config_without_worker_key_files(self):
        settings = Settings(
            database_url="sqlite://",
            environment="test",
            auth_mode="development",
            executor_mode="slurm",
            slurm_source="isaac_sim",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
        )
        with self.assertRaisesRegex(ValueError, "ISAAC_SIM_VERSION"):
            settings.validate(require_slurm_credentials=False)

    def test_api_slurm_config_does_not_require_worker_private_key(self):
        settings = Settings(
            database_url="sqlite://",
            environment="test",
            auth_mode="development",
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
        )
        settings.validate(require_slurm_credentials=False)
        with self.assertRaisesRegex(ValueError, "SLURM_IDENTITY_FILE"):
            settings.validate()

    def test_worker_heartbeat_timeout_must_cover_multiple_poll_intervals(self):
        settings = Settings(
            database_url="sqlite://", environment="test", auth_mode="development",
            slurm_poll_seconds=30, worker_heartbeat_stale_seconds=45,
        )
        with self.assertRaisesRegex(ValueError, "at least twice SLURM_POLL_SECONDS"):
            settings.validate()


class MissionSchemaTests(unittest.TestCase):
    def test_mission_retry_query_has_composite_index(self):
        index = next(
            item for item in MissionRecord.__table__.indexes
            if item.name == "ix_missions_status_updated"
        )
        self.assertEqual(tuple(column.name for column in index.columns),
                         ("status", "updated_at"))

    def test_result_import_retry_interval_must_be_positive(self):
        settings = Settings(
            database_url="sqlite://", environment="test", auth_mode="development",
            result_import_retry_seconds=0,
        )
        with self.assertRaisesRegex(ValueError, "RESULT_IMPORT_RETRY_SECONDS must be positive"):
            settings.validate()

    def test_result_import_retry_interval_is_loaded_from_environment(self):
        with patch.dict(os.environ, {"RESULT_IMPORT_RETRY_SECONDS": "45"}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.result_import_retry_seconds, 45)


class IsaacApiContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.settings = Settings(
            database_url="sqlite://",
            environment="test",
            auth_mode="development",
            artifact_dir=root / "artifacts",
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
            isaac_slurm_gres="gpu:1",
            slurm_source="isaac_sim",
            isaac_sim_version="1.2.3",
            isaac_robot_usd_path="/cluster/assets/go2.usd",
            isaac_sim_python="/opt/isaac-sim/python.sh",
            isaac_sim_adapter="inspection_system.adapters.site:create_adapter",
        )
        self.engine, self.factory = create_database(
            self.settings.database_url, environment="test")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.app = create_app(self.settings, engine_override=self.engine)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)
        self.headers = {"X-Actor-Role": "admin"}

    def test_artifact_upload_offloads_blocking_io_from_the_event_loop(self):
        route = next(
            route for route in self.app.routes
            if getattr(route, "path", None) == "/api/v1/missions/{run_id}/artifacts/{name}"
        )
        self.assertFalse(inspect.iscoroutinefunction(route.endpoint))

    def test_health_and_metrics_expose_request_trace(self):
        health = self.client.get("/healthz", headers={"X-Request-ID": "trace-123"})
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.headers.get("x-request-id"), "trace-123")

        metrics = self.client.get("/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("inspection_http_requests_total", metrics.text)
        self.assertIn('path="/healthz"', metrics.text)

    def test_history_endpoints_paginate_ties_without_gaps_or_duplicates(self):
        created_at = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
        mission_ids = [f"RUN-{index:016d}" for index in range(1, 4)]
        work_order_ids = [f"SIM-WO-{index:04d}" for index in range(1, 4)]
        event_ids = [f"event-{index:04d}" for index in range(1, 4)]
        with self.factory() as session:
            for index, run_id in enumerate(mission_ids, start=1):
                session.add(MissionRecord(
                    run_id=run_id,
                    site_id="SIM-FACTORY-001",
                    robot_id="unitree-sim-01",
                    execution_backend="slurm",
                    status="SUCCEEDED",
                    seed=index,
                    manifest_json="{}",
                    request_hash=f"{index:064x}",
                    created_at=created_at,
                    updated_at=created_at,
                ))
            for index, ticket_id in enumerate(work_order_ids, start=1):
                session.add(WorkOrderRecord(
                    ticket_id=ticket_id,
                    run_id=mission_ids[index - 1],
                    severity="WARNING",
                    review_status="PENDING",
                    payload_json="{}",
                    created_at=created_at,
                ))
            for event_id in event_ids:
                session.add(AuditEventRecord(
                    event_id=event_id,
                    actor="operator-1",
                    actor_role="operator",
                    event_type="MISSION_CREATED",
                    resource_type="mission",
                    resource_id=mission_ids[0],
                    payload_json="{}",
                    created_at=created_at,
                ))
            session.commit()

        endpoints = (
            ("/api/v1/missions", self.headers, "run_id", mission_ids),
            ("/api/v1/work-orders", self.headers, "ticket_id", work_order_ids),
            ("/api/v1/audit-events", {"X-Actor-Role": "reviewer"}, "event_id", event_ids),
        )
        for endpoint, headers, id_field, expected_ids in endpoints:
            with self.subTest(endpoint=endpoint):
                first = self.client.get(f"{endpoint}?limit=2", headers=headers)
                self.assertEqual(first.status_code, 200, first.text)
                cursor = first.headers.get("x-next-cursor")
                self.assertTrue(cursor)
                second = self.client.get(
                    f"{endpoint}?limit=2&cursor={cursor}", headers=headers)
                self.assertEqual(second.status_code, 200, second.text)
                self.assertNotIn("x-next-cursor", second.headers)
                actual_ids = [item[id_field] for item in first.json() + second.json()]
                self.assertEqual(actual_ids, list(reversed(expected_ids)))

    def test_history_endpoints_reject_malformed_cursor(self):
        response = self.client.get(
            "/api/v1/missions?cursor=not-a-valid-cursor", headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def _build_isaac_bundle(
        self, run_id, frozen_manifest, frozen_manifest_json,
        failed_waypoint_index=None,
    ):
        started = datetime.now(timezone.utc).replace(microsecond=0)
        finished = started + timedelta(seconds=30)
        manifest_digest = hashlib.sha256(frozen_manifest_json.encode("utf-8")).hexdigest()
        engine = RuleBasedDiagnosticEngine()
        results = []
        for index, waypoint in enumerate(
            waypoints_from_config(frozen_manifest["site_config"]), start=1,
        ):
            if index == failed_waypoint_index:
                results.append(WaypointResult(
                    waypoint_id=waypoint.waypoint_id,
                    device_id=waypoint.device_id,
                    navigation_status="FAILED",
                    inspection_status="SKIPPED",
                    observation=None,
                    assessment=None,
                    work_order=None,
                    error="Navigation failed before inspection.",
                ))
                continue
            observation = Observation(
                sample_id=f"{run_id}-{index:03d}-{waypoint.waypoint_id}",
                timestamp_utc=started.isoformat(),
                source="isaac_sim",
                robot_id=frozen_manifest["robot_id"],
                waypoint_id=waypoint.waypoint_id,
                device_id=waypoint.device_id,
                pressure_mpa=None,
                temperature_c=43.0,
                ambient_temperature_c=26.5,
                cabinet_door_closed=None,
                leak_detected=None,
                sensor_confidence={"rgb_camera": 0.91},
                domain={
                    "sensor_provenance": {
                        "sensor_ids": ["rgb_camera"],
                        "frame_id": "base_link/rgb_camera",
                    },
                    "temperature_semantics": "simulated_proxy",
                    "simulation_provenance": {
                        "runtime": "Isaac Sim",
                        "runtime_version": "1.2.3",
                        "seed": frozen_manifest["seed"],
                        "manifest_sha256": manifest_digest,
                        "robot_usd_path": frozen_manifest["simulator"]["robot_usd_path"],
                    },
                },
            )
            model_config = frozen_manifest["simulator"].get("model")
            if model_config is not None:
                observation.model_version = model_config["model_version"]
                observation.domain["model_provenance"] = {
                    "model_id": model_config["model_id"],
                    "model_version": model_config["model_version"],
                    "manifest_sha256": model_config["manifest_sha256"],
                    "artifact_sha256": model_config["artifact_sha256"],
                    "input_schema": "inspection-model-input/v1",
                    "output_schema": "inspection-model-output/v1",
                }
            assessment = engine.assess(observation, waypoint)
            work_order = engine.create_work_order(
                observation, waypoint, assessment, frozen_manifest["site_id"], run_id=run_id,
            )
            results.append(WaypointResult(
                waypoint_id=waypoint.waypoint_id,
                device_id=waypoint.device_id,
                navigation_status="SUCCEEDED",
                inspection_status="COMPLETED",
                observation=observation,
                assessment=assessment,
                work_order=work_order,
            ))
        run = InspectionRun(
            run_id=run_id,
            site_id=frozen_manifest["site_id"],
            robot_id=frozen_manifest["robot_id"],
            started_at_utc=started.isoformat(),
            finished_at_utc=finished.isoformat(),
            status=("COMPLETED_WITH_ERRORS" if failed_waypoint_index is not None
                    else "COMPLETED"),
            results=results,
            source="isaac_sim",
        )
        bundle_path = build_result_bundle(
            Path(self.temp_dir.name) / "bundles" / run_id,
            run,
            frozen_manifest["config_sha256"],
            software_version="isaac-sim/1.2.3",
        )
        return read_result_bundle(bundle_path)

    def test_isaac_mission_manifest_and_result_source_contract(self):
        response = self.client.post("/api/v1/missions", json={
            "site_id": "SIM-FACTORY-001",
            "waypoint_ids": ["WP_01_PIPE", "WP_02_CABINET"],
            "seed": 17,
            "execution_backend": "slurm",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]

        with self.factory() as session:
            record = session.get(MissionRecord, run_id)
            frozen_manifest_json = record.manifest_json
            frozen_manifest = json.loads(record.manifest_json)
        self.assertEqual(frozen_manifest["source"], "isaac_sim")
        self.assertEqual(frozen_manifest["simulator"], {
            "expected_version": "1.2.3",
            "robot_usd_path": "/cluster/assets/go2.usd",
            "python_path": "/opt/isaac-sim/python.sh",
            "adapter_entrypoint": "inspection_system.adapters.site:create_adapter",
        })
        self.assertEqual(frozen_manifest["waypoint_ids"], ["WP_01_PIPE", "WP_02_CABINET"])

        result_manifest, result, artifacts = self._build_isaac_bundle(
            run_id, frozen_manifest, frozen_manifest_json,
        )
        spoofed_manifest = {**result_manifest, "source": "synthetic_simulation"}
        spoofed_result = {**result, "source": "synthetic_simulation"}
        rejected = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": spoofed_manifest, "inspection_run": spoofed_result},
            headers=self.headers,
        )
        self.assertEqual(rejected.status_code, 409, rejected.text)

        empty_result = copy.deepcopy(result)
        empty_result["results"] = []
        rejected_empty = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": empty_result},
            headers=self.headers,
        )
        self.assertEqual(rejected_empty.status_code, 422, rejected_empty.text)

        forged_identity = copy.deepcopy(result)
        forged_identity["results"][0]["device_id"] = "DEV-UNRELATED-999"
        rejected_identity = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": forged_identity},
            headers=self.headers,
        )
        self.assertEqual(rejected_identity.status_code, 422, rejected_identity.text)

        malformed_status = copy.deepcopy(result)
        malformed_status["results"][0]["navigation_status"] = []
        rejected_status = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": malformed_status},
            headers=self.headers,
        )
        self.assertEqual(rejected_status.status_code, 422, rejected_status.text)

        forged_provenance = copy.deepcopy(result)
        forged_provenance["results"][0]["observation"]["domain"][
            "simulation_provenance"]["seed"] = 999
        rejected_provenance = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": forged_provenance},
            headers=self.headers,
        )
        self.assertEqual(rejected_provenance.status_code, 422, rejected_provenance.text)

        unlabeled_temperature = copy.deepcopy(result)
        unlabeled_temperature["results"][0]["observation"]["domain"].pop(
            "temperature_semantics")
        rejected_temperature = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": unlabeled_temperature},
            headers=self.headers,
        )
        self.assertEqual(rejected_temperature.status_code, 422, rejected_temperature.text)

        duplicate_quality_flag = copy.deepcopy(result)
        duplicate_quality_flag["results"][0]["observation"]["quality_flags"] = [
            "LOW_LIGHT", "LOW_LIGHT",
        ]
        rejected_quality = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": duplicate_quality_flag},
            headers=self.headers,
        )
        self.assertEqual(rejected_quality.status_code, 422, rejected_quality.text)

        missing_artifacts = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": result},
            headers=self.headers,
        )
        self.assertEqual(missing_artifacts.status_code, 422, missing_artifacts.text)

        for name, content in artifacts.items():
            uploaded = self.client.post(
                f"/api/v1/missions/{run_id}/artifacts/{name}",
                files={"file": (name, content, "application/octet-stream")},
                headers=self.headers,
            )
            self.assertEqual(uploaded.status_code, 201, uploaded.text)
        with self.factory() as session:
            report_record = session.scalar(select(ArtifactRecord).where(
                ArtifactRecord.run_id == run_id,
                ArtifactRecord.name == "inspection_report.md",
            ))
            report_path = Path(report_record.storage_path)
        report_path.write_bytes(artifacts["inspection_report.md"] + b"tampered")
        rejected_tampered_artifact = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": result},
            headers=self.headers,
        )
        report_path.write_bytes(artifacts["inspection_report.md"])
        self.assertEqual(rejected_tampered_artifact.status_code, 422,
                         rejected_tampered_artifact.text)
        imported = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": result},
            headers=self.headers,
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["status"], "SUCCEEDED")
        self.assertEqual(len(result["results"]), len(frozen_manifest["waypoint_ids"]))
        detail = self.client.get(f"/api/v1/missions/{run_id}", headers=self.headers)
        self.assertEqual(detail.json()["result"]["source"], "isaac_sim")
        replay = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": result},
            headers=self.headers,
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])
        artifacts_response = self.client.get(
            f"/api/v1/missions/{run_id}/artifacts", headers=self.headers,
        )
        report = next(item for item in artifacts_response.json()
                      if item["name"] == "inspection_report.md")
        report_response = self.client.get(
            f"/api/v1/artifacts/{report['artifact_id']}", headers=self.headers,
        )
        self.assertIn("Isaac Sim 仿真巡检报告", report_response.text)
        self.assertNotIn("离线模拟适配器生成", report_response.text)

    def test_result_import_rejects_tampered_model_provenance(self):
        settings = replace(
            self.settings,
            isaac_model_manifest_path="/cluster/models/manifest.json",
            isaac_model_manifest_sha256="0" * 64,
            isaac_model_artifact_sha256="1" * 64,
            isaac_model_id="inspection-baseline",
            isaac_model_version="1.2.3",
        )
        app = create_app(settings, engine_override=self.engine)
        with TestClient(app) as client:
            response = client.post("/api/v1/missions", json={
                "site_id": "SIM-FACTORY-001",
                "waypoint_ids": ["WP_01_PIPE", "WP_02_CABINET"],
                "seed": 23,
                "execution_backend": "slurm",
            }, headers=self.headers)
            self.assertEqual(response.status_code, 202, response.text)
            run_id = response.json()["run_id"]

            with self.factory() as session:
                record = session.get(MissionRecord, run_id)
                frozen_manifest_json = record.manifest_json
                frozen_manifest = json.loads(record.manifest_json)
            result_manifest, result, _artifacts = self._build_isaac_bundle(
                run_id, frozen_manifest, frozen_manifest_json,
            )
            result["results"][0]["observation"]["domain"]["model_provenance"][
                "model_version"
            ] = "9.9.9"
            rejected = client.post(
                f"/api/v1/missions/{run_id}/result",
                json={"manifest": result_manifest, "inspection_run": result},
                headers=self.headers,
            )

        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertIn("Model provenance", rejected.text)

    def test_slurm_deployment_rejects_client_offline_override_without_writes(self):
        response = self.client.post("/api/v1/missions", json={
            "site_id": "SIM-FACTORY-001",
            "waypoint_ids": ["WP_01_PIPE"],
            "execution_backend": "offline",
        }, headers=self.headers)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("controlled by deployment configuration", response.json()["detail"])
        with self.factory() as session:
            mission_count = session.scalar(
                select(func.count()).select_from(MissionRecord))
            audit_count = session.scalar(
                select(func.count()).select_from(AuditEventRecord))
        self.assertEqual(mission_count, 0)
        self.assertEqual(audit_count, 0)

    def test_partial_isaac_run_is_terminal_attention_and_idempotent(self):
        response = self.client.post("/api/v1/missions", json={
            "site_id": "SIM-FACTORY-001",
            "waypoint_ids": ["WP_01_PIPE", "WP_02_CABINET", "WP_03_PUMP"],
            "seed": 19,
            "execution_backend": "slurm",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]

        with self.factory() as session:
            record = session.get(MissionRecord, run_id)
            frozen_manifest_json = record.manifest_json
            frozen_manifest = json.loads(record.manifest_json)
        result_manifest, result, artifacts = self._build_isaac_bundle(
            run_id, frozen_manifest, frozen_manifest_json, failed_waypoint_index=2,
        )
        for name, content in artifacts.items():
            uploaded = self.client.post(
                f"/api/v1/missions/{run_id}/artifacts/{name}",
                files={"file": (name, content, "application/octet-stream")},
                headers=self.headers,
            )
            self.assertEqual(uploaded.status_code, 201, uploaded.text)

        imported = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": result},
            headers=self.headers,
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["status"], "PARTIAL")
        detail = self.client.get(f"/api/v1/missions/{run_id}", headers=self.headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["result"]["status"], "COMPLETED_WITH_ERRORS")

        with self.factory() as session:
            stored = session.get(MissionRecord, run_id)
            self.assertEqual(stored.status, "PARTIAL")
            self.assertEqual(
                session.scalar(select(func.count()).select_from(WorkOrderRecord)
                               .where(WorkOrderRecord.run_id == run_id)),
                2,
            )

        replay = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": result_manifest, "inspection_run": result},
            headers=self.headers,
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])
        self.assertEqual(replay.json()["status"], "PARTIAL")

    def test_api_fails_to_start_when_isaac_runtime_config_is_missing(self):
        settings = replace(self.settings, isaac_sim_version=None)
        with self.assertRaisesRegex(
                ValueError, "Isaac Sim Slurm execution requires: ISAAC_SIM_VERSION"):
            create_app(settings)


class PlatformLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings = Settings(
            database_url="sqlite://",
            environment="test",
            auth_mode="development",
            artifact_dir=Path(self.temp_dir.name) / "artifacts",
            executor_mode="offline",
        )
        self.engine, self.factory = create_database(
            self.settings.database_url, environment="test")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.app = create_app(self.settings, engine_override=self.engine)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)
        self.headers = {"X-Actor-Role": "admin"}
        self.site_id = "SIM-FACTORY-001"
        self.waypoint_ids = ["WP_01_PIPE", "WP_02_CABINET", "WP_03_PUMP"]

    def test_mission_idempotency_worker_import_and_manual_review(self):
        payload = {"site_id": self.site_id, "waypoint_ids": self.waypoint_ids, "seed": 42}
        first = self.client.post("/api/v1/missions", json=payload,
                                 headers={**self.headers, "Idempotency-Key": "request-1"})
        self.assertEqual(first.status_code, 202, first.text)
        run_id = first.json()["run_id"]
        replay = self.client.post("/api/v1/missions", json=payload,
                                  headers={**self.headers, "Idempotency-Key": "request-1"})
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json()["run_id"], run_id)

        worker = InspectionWorker(self.factory, self.settings)
        self.assertEqual(worker.run_once(), 1)
        mission_response = self.client.get(f"/api/v1/missions/{run_id}", headers=self.headers)
        self.assertEqual(mission_response.json()["status"], "SUCCEEDED")
        self.assertEqual(mission_response.json()["result"]["source"], "synthetic_simulation")
        self.assertEqual(self.client.get("/readyz").status_code, 200)

        artifact_response = self.client.get(
            f"/api/v1/missions/{run_id}/artifacts", headers=self.headers)
        self.assertEqual(artifact_response.status_code, 200, artifact_response.text)
        report = next(item for item in artifact_response.json()
                      if item["name"] == "inspection_report.md")
        with self.factory() as session:
            report_record = session.get(ArtifactRecord, report["artifact_id"])
            report_path = Path(report_record.storage_path)
        report_content = report_path.read_bytes()
        report_path.write_bytes(b"X" + report_content[1:])
        corrupt_download = self.client.get(
            f"/api/v1/artifacts/{report['artifact_id']}", headers=self.headers)
        report_path.write_bytes(report_content)
        self.assertEqual(corrupt_download.status_code, 503, corrupt_download.text)

        report_download = self.client.get(f"/api/v1/artifacts/{report['artifact_id']}",
                                          headers=self.headers)
        self.assertEqual(report_download.status_code, 200)
        self.assertIn("工业厂区模拟巡检报告", report_download.text)

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            frozen_manifest = json.loads(mission.manifest_json)
            imported_result = json.loads(mission.result_json)
            records = session.scalars(select(ArtifactRecord).where(
                ArtifactRecord.run_id == run_id)).all()
            artifacts = {
                item.name: Path(item.storage_path).read_bytes() for item in records
            }
            result_manifest = {
                "schema_version": 1,
                "run_id": run_id,
                "source": imported_result["source"],
                "software_version": "0.2.0",
                "config_sha256": frozen_manifest["config_sha256"],
                "artifacts": [{"name": item.name, "sha256": item.sha256,
                               "size_bytes": item.size_bytes} for item in records],
            }
        worker._persist_bundle(run_id, result_manifest, imported_result, artifacts)
        altered_result = {**imported_result, "replay_variant": "different"}
        with self.assertRaises(ResultValidationError):
            worker._persist_bundle(run_id, result_manifest, altered_result, artifacts)

        orders_response = self.client.get("/api/v1/work-orders", headers=self.headers)
        self.assertEqual(orders_response.status_code, 200)
        self.assertGreater(len(orders_response.json()), 0)
        order = orders_response.json()[0]
        review = self.client.post(
            f"/api/v1/work-orders/{order['ticket_id']}/review",
            json={"decision": "ACKNOWLEDGED", "comment": "Reviewed against simulated observation."},
            headers={"X-Actor-Role": "reviewer"},
        )
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(review.json()["review_status"], "REVIEWED")
        repeated_review = self.client.post(
            f"/api/v1/work-orders/{order['ticket_id']}/review",
            json={"decision": "DISMISSED", "comment": "Conflicting second review."},
            headers={"X-Actor-Role": "reviewer"},
        )
        self.assertEqual(repeated_review.status_code, 409, repeated_review.text)

        audit = self.client.get("/api/v1/audit-events", headers={"X-Actor-Role": "reviewer"})
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(any(event["event_type"] == "WORK_ORDER_REVIEWED" for event in audit.json()))
        with self.factory() as session:
            imported_events = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.event_type == "MISSION_RESULT_IMPORTED")).all()
            self.assertEqual(len(imported_events), 2)
            self.assertTrue(any(json.loads(item.payload_json)["idempotent_replay"]
                                for item in imported_events))

    def test_offline_virtual_world_mission_imports_rendered_sensor_artifacts(self):
        payload = {
            "site_id": self.site_id,
            "waypoint_ids": self.waypoint_ids,
            "seed": 137,
            "render_backend": "svg",
        }
        created = self.client.post("/api/v1/missions", json=payload, headers=self.headers)
        self.assertEqual(created.status_code, 202, created.text)
        run_id = created.json()["run_id"]
        with self.factory() as session:
            manifest = json.loads(session.get(MissionRecord, run_id).manifest_json)
        self.assertEqual(manifest["virtual_world"], {
            "engine": "local_kinematic", "render_backend": "svg",
        })

        worker = InspectionWorker(self.factory, self.settings)
        self.assertEqual(worker.run_once(), 1)
        detail = self.client.get(f"/api/v1/missions/{run_id}", headers=self.headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["status"], "SUCCEEDED")
        observation = detail.json()["result"]["results"][0]["observation"]
        self.assertEqual(observation["domain"]["render_backend"], "svg")
        artifact_name = observation["domain"]["sensor_provenance"]["artifacts"][0]["name"]
        artifacts = self.client.get(
            f"/api/v1/missions/{run_id}/artifacts", headers=self.headers).json()
        rendered = next(item for item in artifacts if item["name"] == artifact_name)
        downloaded = self.client.get(
            f"/api/v1/artifacts/{rendered['artifact_id']}", headers=self.headers)
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertIn(b"<svg", downloaded.content)

    def test_dashboard_reports_worker_heartbeat_and_marks_stale_instances(self):
        dashboard_url = "/api/v1/dashboard"
        response = self.client.get(dashboard_url, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["worker"]["status"], "not_seen")

        record_worker_heartbeat(
            self.factory,
            instance_id="worker-instance-1",
            execution_backend="offline",
            state="idle",
        )
        live = self.client.get(dashboard_url, headers=self.headers).json()["worker"]
        self.assertEqual(live["status"], "idle")
        self.assertEqual(live["execution_backend"], "offline")

        with self.factory() as session:
            record = session.get(ServiceHeartbeatRecord, "worker")
            record.last_seen_at = utc_now() - timedelta(
                seconds=self.settings.worker_heartbeat_stale_seconds + 1)
            session.commit()
        stale = self.client.get(dashboard_url, headers=self.headers).json()["worker"]
        self.assertEqual(stale["status"], "stale")

        record_worker_heartbeat(
            self.factory,
            instance_id="worker-instance-2",
            execution_backend="offline",
            state="degraded",
            error_type="SlurmError",
        )
        degraded = self.client.get(dashboard_url, headers=self.headers).json()["worker"]
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["last_error_type"], "SlurmError")

    def test_idempotency_key_cannot_be_reused_for_a_different_request(self):
        base = {"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]], "seed": 1}
        first = self.client.post("/api/v1/missions", json=base,
                                 headers={**self.headers, "Idempotency-Key": "same-key"})
        changed = {**base, "seed": 2}
        second = self.client.post("/api/v1/missions", json=changed,
                                  headers={**self.headers, "Idempotency-Key": "same-key"})
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        with self.factory() as session:
            self.assertEqual(len(session.scalars(select(MissionRecord)).all()), 1)

    def test_cancelled_mission_rejects_late_worker_and_api_results(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": self.waypoint_ids, "seed": 42},
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 202, created.text)
        run_id = created.json()["run_id"]
        with self.factory() as session:
            manifest = json.loads(session.get(MissionRecord, run_id).manifest_json)

        cancelled = self.client.post(f"/api/v1/missions/{run_id}/cancel", headers=self.headers)
        self.assertEqual(cancelled.status_code, 202, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")

        worker = InspectionWorker(self.factory, self.settings)
        with self.assertRaisesRegex(ResultValidationError, "late results are rejected"):
            worker._run_offline(manifest)

        late_import = self.client.post(
            f"/api/v1/missions/{run_id}/result",
            json={"manifest": {
                "schema_version": 1,
                "run_id": run_id,
                "source": "synthetic_simulation",
                "software_version": "0.2.0",
                "config_sha256": "0" * 64,
                "artifacts": [],
            }, "inspection_run": {}},
            headers=self.headers,
        )
        self.assertEqual(late_import.status_code, 409, late_import.text)

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "CANCELLED")
            self.assertIsNone(mission.result_json)
            self.assertEqual(len(session.scalars(select(ArtifactRecord).where(
                ArtifactRecord.run_id == run_id)).all()), 0)

    def test_slurm_cancellation_is_worker_owned_and_retried(self):
        slurm_settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
        )
        slurm_app = create_app(slurm_settings, engine_override=self.engine)
        with TestClient(slurm_app) as slurm_client:
            created = slurm_client.post(
                "/api/v1/missions",
                json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]],
                      "execution_backend": "slurm"},
                headers=self.headers,
            )
            self.assertEqual(created.status_code, 202, created.text)
            run_id = created.json()["run_id"]
            with self.factory() as session:
                record = session.get(MissionRecord, run_id)
                record.status = "RUNNING"
                record.slurm_job_id = "81234"
                record.remote_dir = f"/remote/{run_id}"
                session.commit()

            cancellation = slurm_client.post(
                f"/api/v1/missions/{run_id}/cancel", headers=self.headers)
            self.assertEqual(cancellation.status_code, 202, cancellation.text)
            self.assertEqual(cancellation.json()["status"], "CANCELLING")
            repeated = slurm_client.post(
                f"/api/v1/missions/{run_id}/cancel", headers=self.headers)
            self.assertEqual(repeated.json()["status"], "CANCELLING")

            late_result = slurm_client.post(
                f"/api/v1/missions/{run_id}/result",
                json={"manifest": {
                    "schema_version": 1, "run_id": run_id,
                    "source": "synthetic_simulation", "software_version": "0.2.0",
                    "config_sha256": "0" * 64, "artifacts": [],
                }, "inspection_run": {}},
                headers=self.headers,
            )
            self.assertEqual(late_result.status_code, 409, late_result.text)

            class RetryingSlurmClient:
                def __init__(self):
                    self.calls = []

                def status(self, job_id):
                    return "CANCELLED" if len(self.calls) >= 2 else "RUNNING"

                def cancel(self, job_id):
                    self.calls.append(job_id)
                    if len(self.calls) == 1:
                        raise RuntimeError("scheduler temporarily unavailable")

            slurm = RetryingSlurmClient()
            worker = InspectionWorker(self.factory, slurm_settings, slurm)
            self.assertEqual(worker.run_once(), 1)
            with self.factory() as session:
                record = session.get(MissionRecord, run_id)
                self.assertEqual(record.status, "CANCELLING")
                self.assertIn("retry pending", record.error)

            self.assertEqual(worker.run_once(), 1)
            with self.factory() as session:
                record = session.get(MissionRecord, run_id)
                self.assertEqual(record.status, "CANCELLING")
                self.assertIsNone(record.error)

            self.assertEqual(worker.run_once(), 1)
            with self.factory() as session:
                record = session.get(MissionRecord, run_id)
                self.assertEqual(record.status, "CANCELLED")
                events = session.scalars(select(AuditEventRecord).where(
                    AuditEventRecord.resource_id == run_id)).all()
                event_types = {event.event_type for event in events}
                self.assertIn("MISSION_CANCELLATION_REQUESTED", event_types)
                self.assertIn("SLURM_CANCELLATION_CONFIRMED", event_types)
            self.assertEqual(slurm.calls, ["81234", "81234"])

    def test_slurm_cancellation_survives_submission_and_poll_races(self):
        slurm_settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
        )
        slurm_app = create_app(slurm_settings, engine_override=self.engine)

        class SlurmClient:
            def __init__(self):
                self.states = iter(["RUNNING", "RUNNING", "CANCELLED"])
                self.cancelled = []

            def status(self, job_id):
                return next(self.states)

            def cancel(self, job_id):
                self.cancelled.append(job_id)

        slurm = SlurmClient()
        worker = InspectionWorker(self.factory, slurm_settings, slurm)
        with TestClient(slurm_app) as slurm_client:
            created = slurm_client.post(
                "/api/v1/missions",
                json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]],
                      "execution_backend": "slurm"},
                headers=self.headers,
            )
            self.assertEqual(created.status_code, 202, created.text)
            run_id = created.json()["run_id"]
            self.assertEqual(worker._claim_queued()["run_id"], run_id)

            cancellation = slurm_client.post(
                f"/api/v1/missions/{run_id}/cancel", headers=self.headers)
            self.assertEqual(cancellation.status_code, 202, cancellation.text)
            self.assertEqual(cancellation.json()["status"], "CANCELLING")

            worker._bind_submitted_job(run_id, "81234", f"/remote/{run_id}")
            stale_snapshot = {
                "run_id": run_id,
                "job_id": "81234",
                "remote_dir": f"/remote/{run_id}",
                "started_at": utc_now(),
                "poll_failures": 0,
                "status": "RUNNING",
            }
            self.assertTrue(worker._poll_one(stale_snapshot))
            with self.factory() as session:
                self.assertEqual(session.get(MissionRecord, run_id).status, "CANCELLING")

            self.assertTrue(worker._poll_slurm_jobs())
            with self.factory() as session:
                self.assertEqual(session.get(MissionRecord, run_id).status, "CANCELLING")
            self.assertTrue(worker._poll_slurm_jobs())
            with self.factory() as session:
                self.assertEqual(session.get(MissionRecord, run_id).status, "CANCELLED")
            self.assertEqual(slurm.cancelled, ["81234"])

    def test_completed_slurm_job_is_imported_when_cancel_arrives_too_late(self):
        slurm_settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
        )
        slurm_app = create_app(slurm_settings, engine_override=self.engine)
        with TestClient(slurm_app) as slurm_client:
            created = slurm_client.post(
                "/api/v1/missions",
                json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]],
                      "execution_backend": "slurm", "seed": 19},
                headers=self.headers,
            )
            self.assertEqual(created.status_code, 202, created.text)
            run_id = created.json()["run_id"]
            with self.factory() as session:
                mission = session.get(MissionRecord, run_id)
                mission.status = "RUNNING"
                mission.slurm_job_id = "81234"
                mission.remote_dir = f"/remote/{run_id}"
                frozen = json.loads(mission.manifest_json)
                session.commit()

            cancellation = slurm_client.post(
                f"/api/v1/missions/{run_id}/cancel", headers=self.headers)
            self.assertEqual(cancellation.json()["status"], "CANCELLING")

            run = MissionOrchestrator(
                site_id=frozen["site_id"],
                robot_id=frozen["robot_id"],
                waypoints=waypoints_from_config(frozen["site_config"]),
                run_id=run_id,
            ).run()
            camera_frame = Path(self.temp_dir.name) / "camera_frame.bin"
            camera_frame.write_bytes(b"\x00\x01\x02\x03" * 256 * 1024)
            artifact_name = f"{run.results[0].waypoint_id}__camera_frame.bin"
            run.results[0].observation.domain["sensor_provenance"] = {
                "sensor_ids": ["rgb_camera"],
                "frame_id": "base_link/rgb_camera",
                "artifacts": [{
                    "name": artifact_name,
                    "sensor_id": "rgb_camera",
                    "media_type": "application/octet-stream",
                    "timestamp_utc": run.results[0].observation.timestamp_utc,
                }],
            }
            bundle_path = build_result_bundle(
                Path(self.temp_dir.name) / "completed-race-bundle",
                run,
                frozen["config_sha256"],
                additional_artifacts={artifact_name: camera_frame},
            )

            class CompletedSlurmClient:
                def status(self, job_id):
                    return "COMPLETED"

                def fetch_result(self, remote_dir, max_uncompressed_bytes, destination_dir):
                    return RemoteResult(*extract_result_bundle(
                        bundle_path, destination_dir / "extracted", max_uncompressed_bytes))

            worker = InspectionWorker(
                self.factory, slurm_settings, CompletedSlurmClient())
            self.assertTrue(worker._poll_slurm_jobs())
            with self.factory() as session:
                mission = session.get(MissionRecord, run_id)
                self.assertEqual(mission.status, "SUCCEEDED")
                self.assertIsNone(mission.cancellation_target)
                self.assertIsNotNone(mission.result_json)
                artifact = session.scalar(select(ArtifactRecord).where(
                    ArtifactRecord.run_id == run_id,
                    ArtifactRecord.name == artifact_name,
                ))
                self.assertIsNotNone(artifact)
                self.assertEqual(artifact.size_bytes, camera_frame.stat().st_size)
                self.assertEqual(
                    worker.artifact_storage.read_bytes(artifact.storage_path),
                    camera_frame.read_bytes(),
                )
                events = session.scalars(select(AuditEventRecord).where(
                    AuditEventRecord.resource_id == run_id)).all()
                self.assertIn(
                    "MISSION_CANCELLATION_RACED_WITH_COMPLETION",
                    {event.event_type for event in events},
                )

    def test_completed_slurm_job_with_missing_bundle_fails_import(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]]},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        remote_dir = f"/remote/{run_id}"
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.execution_backend = "slurm"
            mission.status = "RUNNING"
            mission.slurm_job_id = "81235"
            mission.remote_dir = remote_dir
            session.commit()

        class MissingResultSlurmClient:
            def status(self, job_id):
                return "COMPLETED"

            def fetch_result(self, remote_dir, max_uncompressed_bytes, destination_dir):
                raise SlurmResultError("Completed job has no result bundle.")

        settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote",
        )
        worker = InspectionWorker(self.factory, settings, MissingResultSlurmClient())
        self.assertTrue(worker._poll_slurm_jobs())

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "RESULT_IMPORT_FAILED")
            self.assertIn("no result bundle", mission.error)
            events = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.resource_id == run_id)).all()
            self.assertIn("MISSION_TERMINATED", {event.event_type for event in events})

    def test_database_error_during_result_import_remains_retryable(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]]},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        remote_dir = f"/remote/{run_id}"
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.execution_backend = "slurm"
            mission.status = "IMPORTING"
            mission.remote_dir = remote_dir
            session.commit()

        class FetchResult:
            def fetch_result(self, remote_dir, max_uncompressed_bytes, destination_dir):
                return RemoteResult({}, {}, {})

        worker = InspectionWorker(self.factory, self.settings, FetchResult())
        error = OperationalError("COMMIT", {}, RuntimeError("connection unavailable"))
        with patch.object(worker, "_persist_bundle", side_effect=error):
            worker._import_slurm_result(run_id, remote_dir)

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "IMPORTING")
            self.assertIn("retry pending: OperationalError", mission.error)
            events = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.resource_id == run_id)).all()
            self.assertIn("MISSION_RESULT_IMPORT_RETRY_PENDING",
                          {event.event_type for event in events})

    def test_result_import_retries_respect_interval_and_restart_after_failure(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]]},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.execution_backend = "slurm"
            mission.status = "IMPORTING"
            mission.remote_dir = f"/remote/{run_id}"
            mission.updated_at = utc_now() - timedelta(seconds=10)
            session.commit()

        class TemporarilyUnavailableSlurmClient:
            calls = 0

            def fetch_result(self, remote_dir, max_uncompressed_bytes, destination_dir):
                self.calls += 1
                raise SlurmError("temporary transport failure")

        slurm_client = TemporarilyUnavailableSlurmClient()
        settings = replace(
            self.settings, executor_mode="slurm", result_import_retry_seconds=60)
        worker = InspectionWorker(self.factory, settings, slurm_client)
        self.assertFalse(worker._retry_imports())
        self.assertEqual(slurm_client.calls, 0)

        with self.factory() as session:
            session.get(MissionRecord, run_id).updated_at = (
                utc_now() - timedelta(seconds=120))
            session.commit()
        attempt_started_at = utc_now()

        self.assertTrue(worker._retry_imports())
        self.assertEqual(slurm_client.calls, 1)
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "IMPORTING")
            self.assertGreaterEqual(mission.updated_at.replace(tzinfo=timezone.utc),
                                    attempt_started_at)

        self.assertFalse(worker._retry_imports())
        self.assertEqual(slurm_client.calls, 1)

    def test_database_error_after_sbatch_acceptance_preserves_reconciliation(self):
        slurm_settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
        )
        class AcceptedSlurmClient:
            def submit(self, manifest):
                return "81239", f"/remote/inspection-test/{manifest['run_id']}"

        worker = InspectionWorker(self.factory, slurm_settings, AcceptedSlurmClient())
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]]},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        with self.factory() as session:
            session.get(MissionRecord, run_id).execution_backend = "slurm"
            session.commit()
        error = OperationalError("COMMIT", {}, RuntimeError("connection unavailable"))
        with patch.object(worker, "_bind_submitted_job", side_effect=error):
            self.assertTrue(worker._submit_next())

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "SUBMITTING")
            self.assertIsNone(mission.slurm_job_id)
            self.assertIn("reconciliation is pending", mission.error)
            events = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.resource_id == run_id)).all()
            self.assertIn("SLURM_SUBMISSION_OUTCOME_UNKNOWN",
                          {event.event_type for event in events})

    def test_importing_mission_cannot_be_cancelled(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]]},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        with self.factory() as session:
            session.get(MissionRecord, run_id).status = "IMPORTING"
            session.commit()

        response = self.client.post(
            f"/api/v1/missions/{run_id}/cancel", headers=self.headers)
        self.assertEqual(response.status_code, 409, response.text)
        with self.factory() as session:
            self.assertEqual(session.get(MissionRecord, run_id).status, "IMPORTING")

    def test_worker_requeues_abandoned_offline_submission(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": self.waypoint_ids, "seed": 42},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        stale_time = utc_now() - timedelta(minutes=10)
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.status = "SUBMITTING"
            mission.submission_attempts = 1
            mission.started_at = stale_time
            mission.updated_at = stale_time
            session.commit()

        settings = replace(self.settings, submission_recovery_seconds=1)
        worker = InspectionWorker(self.factory, settings)
        self.assertEqual(worker.run_once(), 1)

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "SUCCEEDED")
            self.assertEqual(mission.submission_attempts, 2)
            events = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.resource_id == run_id)).all()
            self.assertTrue(any(event.event_type == "MISSION_SUBMISSION_RECOVERED"
                                for event in events))

    def test_stale_submission_stops_after_recovery_attempt_limit(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": self.waypoint_ids, "seed": 42},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        stale_time = utc_now() - timedelta(minutes=10)
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.status = "SUBMITTING"
            mission.submission_attempts = 3
            mission.started_at = stale_time
            mission.updated_at = stale_time
            session.commit()

        settings = replace(self.settings, submission_recovery_seconds=1,
                            submission_attempt_limit=3)
        worker = InspectionWorker(self.factory, settings)
        self.assertEqual(worker.run_once(), 1)
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "FAILED")
            self.assertIn("attempt limit", mission.error)

    def test_worker_reconnects_stale_slurm_submission_to_existing_job(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": self.waypoint_ids, "seed": 42},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        stale_time = utc_now() - timedelta(minutes=10)
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.execution_backend = "slurm"
            mission.status = "SUBMITTING"
            mission.submission_attempts = 1
            mission.started_at = stale_time
            mission.updated_at = stale_time
            session.commit()

        class SlurmLookup:
            def find_jobs_for_runs(self, run_ids, submitted_after):
                self.run_ids = run_ids
                return {run_id: {"81234": "RUNNING"} for run_id in run_ids}

            def result_bundles_exist(self, remote_dirs):
                self.remote_dirs = remote_dirs
                return set()

        slurm = SlurmLookup()
        settings = replace(self.settings, submission_recovery_seconds=1,
                            slurm_remote_root="/cluster/inspection")
        worker = InspectionWorker(self.factory, settings, slurm)
        self.assertTrue(worker._recover_stale_submissions())

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "RUNNING")
            self.assertEqual(mission.slurm_job_id, "81234")
            self.assertEqual(mission.remote_dir, f"/cluster/inspection/{run_id}")

    def test_unknown_sbatch_outcome_is_reconciled_before_retry(self):
        slurm_settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
            submission_recovery_seconds=1,
        )
        slurm_app = create_app(slurm_settings, engine_override=self.engine)

        class SlurmClient:
            def __init__(self):
                self.run_ids = []

            def submit(self, manifest):
                raise SlurmSubmissionOutcomeUnknown("response lost")

            def find_jobs_for_runs(self, run_ids, submitted_after):
                self.run_ids = run_ids
                return {run_id: {} for run_id in run_ids}

            def result_bundles_exist(self, remote_dirs):
                return set()

        slurm = SlurmClient()
        worker = InspectionWorker(self.factory, slurm_settings, slurm)
        with TestClient(slurm_app) as slurm_client:
            created = slurm_client.post(
                "/api/v1/missions",
                json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]],
                      "execution_backend": "slurm"},
                headers=self.headers,
            )
            run_id = created.json()["run_id"]
            self.assertEqual(worker.run_once(), 1)
            with self.factory() as session:
                mission = session.get(MissionRecord, run_id)
                self.assertEqual(mission.status, "SUBMITTING")
                self.assertIn("reconciliation is pending", mission.error)

            stale_time = utc_now() - timedelta(minutes=1)
            with self.factory() as session:
                mission = session.get(MissionRecord, run_id)
                mission.updated_at = stale_time
                session.commit()
            self.assertTrue(worker._recover_stale_submissions())
            with self.factory() as session:
                mission = session.get(MissionRecord, run_id)
                self.assertEqual(mission.status, "QUEUED")
                events = session.scalars(select(AuditEventRecord).where(
                    AuditEventRecord.resource_id == run_id)).all()
                event_types = {event.event_type for event in events}
                self.assertIn("SLURM_SUBMISSION_OUTCOME_UNKNOWN", event_types)
                self.assertIn("MISSION_SUBMISSION_RECOVERED", event_types)

    def test_unknown_sbatch_outcome_preserves_cancellation_for_recovery(self):
        slurm_settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection-test",
            slurm_remote_root="/remote/inspection-test",
            submission_recovery_seconds=1,
        )
        slurm_app = create_app(slurm_settings, engine_override=self.engine)
        client_holder = {}
        actor_headers = {"X-Actor-Role": "admin"}

        class SlurmClient:
            def submit(self, manifest):
                run_id = manifest["run_id"]
                response = client_holder["client"].post(
                    f"/api/v1/missions/{run_id}/cancel", headers=actor_headers)
                if response.status_code != 202:
                    raise AssertionError(response.text)
                raise SlurmSubmissionOutcomeUnknown("response lost")

            def find_jobs_for_runs(self, run_ids, submitted_after):
                return {run_id: {} for run_id in run_ids}

            def result_bundles_exist(self, remote_dirs):
                return set()

        slurm = SlurmClient()
        worker = InspectionWorker(self.factory, slurm_settings, slurm)
        with TestClient(slurm_app) as slurm_client:
            client_holder["client"] = slurm_client
            created = slurm_client.post(
                "/api/v1/missions",
                json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]],
                      "execution_backend": "slurm"},
                headers=self.headers,
            )
            run_id = created.json()["run_id"]
            self.assertEqual(worker.run_once(), 1)
            with self.factory() as session:
                mission = session.get(MissionRecord, run_id)
                self.assertEqual(mission.status, "CANCELLING")
                self.assertEqual(mission.cancellation_target, "CANCELLED")

            with self.factory() as session:
                mission = session.get(MissionRecord, run_id)
                mission.updated_at = utc_now() - timedelta(minutes=1)
                session.commit()
            self.assertTrue(worker._recover_stale_submissions())
            with self.factory() as session:
                mission = session.get(MissionRecord, run_id)
                self.assertEqual(mission.status, "CANCELLED")
                self.assertIsNone(mission.cancellation_target)

    def test_submission_reconciliation_outage_never_triggers_duplicate_retry(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]]},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.execution_backend = "slurm"
            mission.status = "SUBMITTING"
            mission.submission_attempts = 1
            mission.updated_at = utc_now() - timedelta(minutes=10)
            session.commit()

        class UnavailableAccounting:
            def find_jobs_for_runs(self, run_ids, submitted_after):
                raise RuntimeError("accounting unavailable")

        worker = InspectionWorker(
            self.factory,
            replace(self.settings, executor_mode="slurm", submission_recovery_seconds=1),
            UnavailableAccounting(),
        )
        for _ in range(10):
            worker._recover_stale_submissions()
            with self.factory() as session:
                record = session.get(MissionRecord, run_id)
                record.updated_at = utc_now() - timedelta(minutes=10)
                session.commit()

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "SUBMITTING")
            self.assertEqual(mission.submission_attempts, 1)
            self.assertIn("automatic retry is paused", mission.error)
            events = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.resource_id == run_id)).all()
            self.assertIn("SLURM_RECONCILIATION_REQUIRED",
                          {event.event_type for event in events})

    def test_poll_failure_limit_enters_retryable_slurm_cancellation(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": self.waypoint_ids, "seed": 42},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.execution_backend = "slurm"
            mission.status = "RUNNING"
            mission.slurm_job_id = "81234"
            mission.remote_dir = f"/remote/{run_id}"
            mission.poll_failures = 9
            session.commit()

        class SlurmCancelFailure:
            def __init__(self):
                self.status_calls = 0
                self.cancel_calls = []

            def status(self, job_id):
                self.status_calls += 1
                if self.status_calls == 1:
                    raise RuntimeError("scheduler unavailable")
                return "CANCELLED" if self.status_calls >= 4 else "RUNNING"

            def cancel(self, job_id):
                self.cancel_calls.append(job_id)
                if len(self.cancel_calls) == 1:
                    raise RuntimeError("scheduler unavailable")

        slurm = SlurmCancelFailure()
        worker = InspectionWorker(
            self.factory, replace(self.settings, executor_mode="slurm"), slurm)
        worker.run_once()

        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "CANCELLING")
            self.assertIn("cancellation is pending", mission.error)
            events = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.resource_id == run_id)).all()
            self.assertTrue(any(event.event_type == "SLURM_CANCELLATION_REQUESTED_AFTER_POLL_FAILURES"
                                for event in events))

        worker.run_once()
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "CANCELLING")
            self.assertIn("retry pending", mission.error)
            events = session.scalars(select(AuditEventRecord).where(
                AuditEventRecord.resource_id == run_id)).all()
            self.assertTrue(any(event.event_type == "SLURM_CANCELLATION_ATTEMPT_FAILED"
                                for event in events))

        worker.run_once()
        with self.factory() as session:
            self.assertEqual(session.get(MissionRecord, run_id).status, "CANCELLING")
        worker.run_once()
        with self.factory() as session:
            self.assertEqual(session.get(MissionRecord, run_id).status, "FAILED")

    def test_slurm_timeout_retries_cancellation_and_keeps_timeout_outcome(self):
        created = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]]},
            headers=self.headers,
        )
        run_id = created.json()["run_id"]
        old_start = utc_now() - timedelta(minutes=5)
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            mission.execution_backend = "slurm"
            mission.status = "RUNNING"
            mission.slurm_job_id = "81234"
            mission.remote_dir = f"/remote/{run_id}"
            mission.started_at = old_start
            session.commit()

        class CancelledSlurmClient:
            def status(self, job_id):
                return "CANCELLED"

            def cancel(self, job_id):
                raise AssertionError("timeout cancellation must wait for worker polling")

        settings = replace(
            self.settings, executor_mode="slurm", mission_timeout_seconds=1)
        worker = InspectionWorker(self.factory, settings, CancelledSlurmClient())
        worker.run_once()
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "CANCELLING")
            self.assertEqual(mission.cancellation_target, "TIMED_OUT")

        worker.run_once()
        with self.factory() as session:
            mission = session.get(MissionRecord, run_id)
            self.assertEqual(mission.status, "TIMED_OUT")
            self.assertIsNone(mission.cancellation_target)

    def test_viewer_cannot_create_a_mission(self):
        response = self.client.post(
            "/api/v1/missions",
            json={"site_id": self.site_id, "waypoint_ids": [self.waypoint_ids[0]]},
            headers={"X-Actor-Role": "viewer"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "INSUFFICIENT_ROLE")


if __name__ == "__main__":
    unittest.main()
