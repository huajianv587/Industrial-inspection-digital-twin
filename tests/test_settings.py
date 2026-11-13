from dataclasses import replace
import math
import unittest

from inspection_system.platform.settings import Settings


class RuntimeSettingsValidationTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            database_url="sqlite://",
            environment="test",
            auth_mode="development",
        )

    def test_rejects_non_finite_or_non_positive_runtime_timeouts(self):
        cases = (
            ("slurm_poll_seconds", math.nan, "SLURM_POLL_SECONDS"),
            ("slurm_poll_seconds", math.inf, "SLURM_POLL_SECONDS"),
            ("slurm_command_timeout_seconds", -math.inf,
             "SLURM_COMMAND_TIMEOUT_SECONDS"),
            ("slurm_command_timeout_seconds", 0, "SLURM_COMMAND_TIMEOUT_SECONDS"),
            ("worker_heartbeat_stale_seconds", math.nan,
             "WORKER_HEARTBEAT_STALE_SECONDS"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                settings = replace(self.settings, **{field: value})
                with self.assertRaisesRegex(ValueError, expected):
                    settings.validate()

    def test_rejects_zero_or_non_integer_mission_timeout(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value):
                settings = replace(self.settings, mission_timeout_seconds=value)
                with self.assertRaisesRegex(ValueError, "MISSION_TIMEOUT_SECONDS"):
                    settings.validate()

    def test_rejects_invalid_slurm_port(self):
        slurm_settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection",
            slurm_remote_root="/shared/inspection",
        )
        for port in (0, 65536, True, 22.0):
            with self.subTest(port=port):
                settings = replace(slurm_settings, slurm_port=port)
                with self.assertRaisesRegex(ValueError, "SLURM_PORT"):
                    settings.validate(require_slurm_credentials=False)

    def test_accepts_valid_slurm_port_and_timeout_configuration(self):
        settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection",
            slurm_remote_root="/shared/inspection",
            slurm_port=65535,
        )
        settings.validate(require_slurm_credentials=False)

    def test_rejects_partial_isaac_model_configuration(self):
        settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection",
            slurm_remote_root="/shared/inspection",
            slurm_source="isaac_sim",
            isaac_sim_version="1.2.3",
            isaac_robot_usd_path="/cluster/assets/go2.usd",
            isaac_sim_python="/opt/isaac-sim/python.sh",
            isaac_sim_adapter="inspection_system.adapters.site:create_adapter",
            isaac_slurm_gres="gpu:1",
            isaac_model_manifest_path="/cluster/models/manifest.json",
        )
        with self.assertRaisesRegex(ValueError, "ISAAC_MODEL_MANIFEST_SHA256"):
            settings.validate(require_slurm_credentials=False)

    def test_accepts_complete_isaac_model_configuration(self):
        settings = replace(
            self.settings,
            executor_mode="slurm",
            slurm_host="cluster.example.test",
            slurm_user="inspection",
            slurm_remote_root="/shared/inspection",
            slurm_source="isaac_sim",
            isaac_sim_version="1.2.3",
            isaac_robot_usd_path="/cluster/assets/go2.usd",
            isaac_sim_python="/opt/isaac-sim/python.sh",
            isaac_sim_adapter="inspection_system.adapters.site:create_adapter",
            isaac_slurm_gres="gpu:1",
            isaac_model_manifest_path="/cluster/models/manifest.json",
            isaac_model_manifest_sha256="0" * 64,
            isaac_model_artifact_sha256="1" * 64,
            isaac_model_id="inspection-baseline",
            isaac_model_version="1.2.3",
        )
        settings.validate(require_slurm_credentials=False)


if __name__ == "__main__":
    unittest.main()
