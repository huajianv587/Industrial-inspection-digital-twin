from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from inspection_system.config import waypoints_from_config
from inspection_system.industrial import IndustrialSiteError, industrial_readiness, load_industrial_site
from inspection_system.platform.api import create_app
from inspection_system.platform.db import Base, create_database
from inspection_system.platform.settings import Settings


INDUSTRIAL_CONFIG = Path(__file__).parents[1] / "configs" / "industrial_site_v12.json"
SITE_CONFIG = Path(__file__).parents[1] / "configs" / "site.json"


class IndustrialSiteRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = load_industrial_site(INDUSTRIAL_CONFIG)

    def write_config(self, payload: dict) -> Path:
        directory = Path(self.temp_dir.name)
        path = directory / "industrial.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def test_valid_registry_preserves_asset_links_and_readiness_boundary(self):
        waypoints = waypoints_from_config(self.site)
        self.assertEqual(len(waypoints), 10)
        self.assertEqual(waypoints[0].asset_id, "AST-PIPE-302")
        self.assertEqual(
            {waypoint.asset_id for waypoint in waypoints},
            {asset["asset_id"] for asset in self.site["assets"]},
        )

        readiness = industrial_readiness(self.site)
        self.assertEqual(readiness["status"], "SIMULATION_READY_FIELD_DATA_PENDING")
        self.assertEqual(readiness["asset_count"], 10)
        self.assertEqual(readiness["model_status_counts"]["procedural_proxy"], 10)
        self.assertEqual(readiness["sensor_source_counts"]["not_connected"], 2)

    def test_missing_asset_waypoint_is_rejected(self):
        payload = deepcopy(self.site)
        payload["waypoints"] = payload["waypoints"][:-1]
        with self.assertRaisesRegex(IndustrialSiteError, "Every registered asset"):
            load_industrial_site(self.write_config(payload))

    def test_duplicate_asset_is_rejected(self):
        payload = deepcopy(self.site)
        payload["assets"].append(deepcopy(payload["assets"][0]))
        with self.assertRaisesRegex(IndustrialSiteError, "Duplicate asset_id"):
            load_industrial_site(self.write_config(payload))

    def test_unknown_zone_is_rejected(self):
        payload = deepcopy(self.site)
        payload["assets"][0]["zone_id"] = "UNKNOWN-ZONE"
        with self.assertRaisesRegex(IndustrialSiteError, "unknown zone_id"):
            load_industrial_site(self.write_config(payload))


class IndustrialSiteApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.settings = Settings(
            database_url="sqlite://",
            environment="test",
            auth_mode="development",
            site_config_path=SITE_CONFIG,
            industrial_site_config_path=INDUSTRIAL_CONFIG,
            artifact_dir=root / "artifacts",
        )
        self.engine, _ = create_database(self.settings.database_url, environment="test")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.app = create_app(self.settings, engine_override=self.engine)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    def test_industrial_site_endpoint_returns_readiness_and_registry(self):
        response = self.client.get("/api/v1/industrial/site", headers={"X-Actor-Role": "viewer"})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["site"]["site_id"], "IND-PLANT-001")
        self.assertEqual(payload["readiness"]["status"], "SIMULATION_READY_FIELD_DATA_PENDING")
        self.assertEqual(payload["site"]["waypoints"][0]["asset_id"], "AST-PIPE-302")


if __name__ == "__main__":
    unittest.main()
