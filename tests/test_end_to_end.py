import json
import tempfile
import unittest
from pathlib import Path
from inspection_system.config import load_site_config, waypoints_from_config
from inspection_system.adapters.simulation import SimulatedRobotAdapter
from inspection_system.mission.orchestrator import MissionOrchestrator

class EndToEndTests(unittest.TestCase):
    def test_demo_writes_run_report_and_orders(self):
        config = load_site_config("configs/site.json")
        waypoints = waypoints_from_config(config)
        with tempfile.TemporaryDirectory() as tmp:
            runner = MissionOrchestrator(config["site_id"], config["robot"]["robot_id"], waypoints)
            run = runner.run(tmp)
            self.assertEqual(run.status, "COMPLETED")
            self.assertEqual(len(run.results), len(waypoints))
            run_file = Path(tmp) / "inspection_run.json"
            report_file = Path(tmp) / "inspection_report.md"
            self.assertTrue(run_file.exists())
            self.assertTrue(report_file.exists())
            payload = json.loads(run_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["source"], "synthetic_simulation")
            self.assertEqual(len(list((Path(tmp) / "work_orders").glob("*.json"))), len(waypoints))

    def test_navigation_failure_is_recorded_and_does_not_crash_run(self):
        config = load_site_config("configs/site.json")
        waypoints = waypoints_from_config(config)
        fail_id = waypoints[0].waypoint_id
        adapter = SimulatedRobotAdapter(config["robot"]["robot_id"], {fail_id})
        run = MissionOrchestrator(config["site_id"], config["robot"]["robot_id"],
                                  waypoints, adapter=adapter).run()
        self.assertEqual(run.status, "COMPLETED_WITH_ERRORS")
        self.assertEqual(run.results[0].navigation_status, "FAILED")
        self.assertEqual(run.results[0].inspection_status, "SKIPPED")

if __name__ == "__main__":
    unittest.main()
