from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inspection_system.config import load_site_config, waypoints_from_config
from inspection_system.mission.orchestrator import MissionOrchestrator
from inspection_system.simulation import VirtualWorldRobotAdapter


class VirtualWorldAdapterTests(unittest.TestCase):
    def test_local_virtual_world_replays_route_and_renders_each_waypoint(self):
        config = load_site_config("configs/site.json")
        waypoints = waypoints_from_config(config)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            adapter = VirtualWorldRobotAdapter(
                site_id=config["site_id"],
                robot_id=config["robot"]["robot_id"],
                waypoints=waypoints,
                output_dir=output,
                seed=137,
                render_backend="svg",
            )
            run = MissionOrchestrator(
                config["site_id"], config["robot"]["robot_id"], waypoints,
                adapter=adapter,
            ).run(output)

            self.assertEqual(run.status, "COMPLETED")
            self.assertEqual(adapter.resolved_backend, "svg")
            self.assertGreater(len(adapter._trajectory), len(waypoints))
            for result in run.results:
                observation = result.observation
                self.assertIsNotNone(observation)
                assert observation is not None
                self.assertTrue(observation.domain["virtual_world"])
                self.assertEqual(observation.domain["render_backend"], "svg")
                artifact = observation.domain["sensor_provenance"]["artifacts"][0]["name"]
                artifact_path = output / "virtual_world" / artifact
                self.assertTrue(artifact_path.is_file())
                self.assertIn("<svg", artifact_path.read_text(encoding="utf-8"))

            manifest = json.loads(
                (output / "virtual_world" / "virtual_world_manifest.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(manifest["run_id"], run.run_id)
            self.assertEqual(manifest["resolved_render_backend"], "svg")
            self.assertEqual(len(adapter.additional_artifacts), len(waypoints))

            first_observation = run.results[0].observation
            self.assertIsNotNone(first_observation)
            assert first_observation is not None
            adapter._attach_scene_artifacts(
                run, ["factory_scene.glb", *adapter._observation_artifacts.values()])
            references = first_observation.domain["sensor_provenance"]["artifacts"]
            names = [item["name"] for item in references]
            first_capture = adapter._observation_artifacts[waypoints[0].waypoint_id]
            self.assertEqual(names.count(first_capture), 1)
            self.assertEqual(names.count("factory_scene.glb"), 1)
            for waypoint in waypoints[1:]:
                self.assertNotIn(adapter._observation_artifacts[waypoint.waypoint_id], names)

    def test_blender_backend_fails_closed_when_executable_is_missing(self):
        config = load_site_config("configs/site.json")
        with patch("inspection_system.simulation.virtual_world.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Blender was requested"):
                VirtualWorldRobotAdapter(
                    site_id=config["site_id"],
                    robot_id=config["robot"]["robot_id"],
                    waypoints=waypoints_from_config(config),
                    output_dir=Path(tempfile.mkdtemp()),
                    render_backend="blender",
                )


if __name__ == "__main__":
    unittest.main()
