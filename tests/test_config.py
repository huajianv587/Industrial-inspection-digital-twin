from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

from inspection_system.config import ConfigError, load_site_config


class SiteConfigValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.valid_config = load_site_config("configs/site.json")

    def assert_invalid(self, mutate):
        config = deepcopy(self.valid_config)
        mutate(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site.json"
            path.write_text(json.dumps(config, allow_nan=True), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_site_config(path)

    def test_rejects_invalid_site_and_asset_identifiers(self):
        cases = [
            lambda config: config.update(site_id=17),
            lambda config: config.update(site_name="  "),
            lambda config: config["robot"].update(robot_id=True),
            lambda config: config["waypoints"][0].update(device_id=None),
            lambda config: config["waypoints"][0].update(waypoint_id="  "),
        ]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.assert_invalid(mutate)

    def test_rejects_non_finite_and_coerced_numeric_fields(self):
        cases = [
            (lambda item: item["position"].update(x=math.nan)),
            (lambda item: item.update(yaw_deg=math.inf)),
            (lambda item: item.update(warning_temp_c=True)),
            (lambda item: item.update(critical_temp_c="60")),
            (lambda item: item.update(pressure_max_mpa=-math.inf)),
        ]
        for mutate_waypoint in cases:
            with self.subTest(mutate_waypoint=mutate_waypoint):
                self.assert_invalid(lambda config: mutate_waypoint(config["waypoints"][0]))

    def test_rejects_nonstandard_json_numbers_in_unused_fields(self):
        self.assert_invalid(lambda config: config["robot"].update(max_speed=math.nan))

    def test_rejects_inverted_temperature_thresholds(self):
        self.assert_invalid(lambda config: config["waypoints"][0].update(
            warning_temp_c=80, critical_temp_c=70))

    def test_rejects_non_boolean_door_policy(self):
        self.assert_invalid(lambda config: config["waypoints"][0].update(
            require_door_closed="false"))

    def test_reports_unreadable_and_malformed_files_as_config_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with self.assertRaises(ConfigError):
                load_site_config(path)

            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_site_config(path)

            with self.assertRaises(ConfigError):
                load_site_config(directory)


if __name__ == "__main__":
    unittest.main()
