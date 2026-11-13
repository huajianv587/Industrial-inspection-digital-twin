import unittest
from inspection_system.config import load_site_config, waypoints_from_config
from inspection_system.models import Observation, Severity
from inspection_system.perception.rules import RuleBasedDiagnosticEngine

CONFIG = "configs/site.json"

class RuleEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_site_config(CONFIG)
        cls.waypoints = {w.waypoint_id: w for w in waypoints_from_config(cls.config)}
        cls.engine = RuleBasedDiagnosticEngine()

    def test_critical_temperature(self):
        w = self.waypoints["WP_01_PIPE"]
        o = Observation("x", "2026-01-01T00:00:00+00:00", "synthetic_simulation",
                        "r", w.waypoint_id, w.device_id, temperature_c=65,
                        ambient_temperature_c=25)
        result = self.engine.assess(o, w)
        self.assertEqual(result.severity, Severity.CRITICAL)
        self.assertIn("TEMPERATURE_CRITICAL", [a.code for a in result.anomalies])

    def test_open_required_door_is_warning(self):
        w = self.waypoints["WP_02_CABINET"]
        o = Observation("x", "2026-01-01T00:00:00+00:00", "synthetic_simulation",
                        "r", w.waypoint_id, w.device_id, temperature_c=40,
                        cabinet_door_closed=False)
        result = self.engine.assess(o, w)
        self.assertEqual(result.severity, Severity.WARNING)
        self.assertIn("CABINET_DOOR_OPEN", [a.code for a in result.anomalies])

    def test_missing_required_pressure_is_not_silently_normal(self):
        w = self.waypoints["WP_01_PIPE"]
        o = Observation("x", "2026-01-01T00:00:00+00:00", "synthetic_simulation",
                        "r", w.waypoint_id, w.device_id, pressure_mpa=None,
                        temperature_c=35, ambient_temperature_c=25)
        result = self.engine.assess(o, w)
        self.assertEqual(result.severity, Severity.UNKNOWN)
        self.assertIn("MEASUREMENT_MISSING", [a.code for a in result.anomalies])

    def test_empty_measurements_are_unknown(self):
        w = self.waypoints["WP_01_PIPE"]
        o = Observation("x", "2026-01-01T00:00:00+00:00", "synthetic_simulation",
                        "r", w.waypoint_id, w.device_id)
        self.assertEqual(self.engine.assess(o, w).severity, Severity.UNKNOWN)

    def test_work_order_preserves_model_and_quality_provenance(self):
        w = self.waypoints["WP_01_PIPE"]
        o = Observation(
            "x", "2026-01-01T00:00:00+00:00", "robot", "r",
            w.waypoint_id, w.device_id, temperature_c=35,
            model_version="vision-baseline/1.0.0",
            calibration_version="thermal-cal-2026-01",
            quality_flags=["LOW_LIGHT"], inference_latency_ms=18.5,
        )
        assessment = self.engine.assess(o, w)
        order = self.engine.create_work_order(o, w, assessment, "SITE-1", run_id="RUN-1")
        self.assertEqual(order.observations["model_version"], "vision-baseline/1.0.0")
        self.assertEqual(order.observations["calibration_version"], "thermal-cal-2026-01")
        self.assertEqual(order.observations["quality_flags"], ["LOW_LIGHT"])
        self.assertEqual(order.observations["inference_latency_ms"], 18.5)

if __name__ == "__main__":
    unittest.main()
