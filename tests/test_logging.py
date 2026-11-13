import json
import logging
import unittest

from inspection_system.platform.logging_config import JsonLogFormatter


class JsonLogFormatterTests(unittest.TestCase):
    def test_emits_parseable_log_with_run_context(self):
        record = logging.LogRecord(
            "inspection_system.platform.worker", logging.ERROR, __file__, 12,
            "Mission import failed", (), None,
        )
        record.run_id = "RUN-123"
        record.execution_backend = "slurm"

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["message"], "Mission import failed")
        self.assertEqual(payload["run_id"], "RUN-123")
        self.assertEqual(payload["execution_backend"], "slurm")
        self.assertEqual(payload["level"], "ERROR")
        self.assertTrue(payload["timestamp"].endswith("Z"))

    def test_emits_http_request_context(self):
        record = logging.LogRecord(
            "inspection_system.platform.api", logging.INFO, __file__, 20,
            "HTTP request completed", (), None,
        )
        record.request_id = "trace-123"
        record.http_method = "GET"
        record.http_path = "/healthz"
        record.http_status = 200
        record.duration_ms = 1.25

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["request_id"], "trace-123")
        self.assertEqual(payload["http_status"], 200)
        self.assertEqual(payload["duration_ms"], 1.25)


if __name__ == "__main__":
    unittest.main()
