import unittest

from scripts.validate_compose_logging import validate_logging, validate_web_exposure


class ComposeLoggingValidationTests(unittest.TestCase):
    def test_accepts_rotated_logs_for_all_services(self):
        configuration = {"services": {
            name: {"logging": {
                "driver": "json-file",
                "options": {"max-size": "10m", "max-file": "5"},
            }, **({"ports": [{
                "target": 80, "published": "8080", "protocol": "tcp",
                "host_ip": "127.0.0.1",
            }]} if name == "web" else {})}
            for name in ("api", "worker", "web")
        }}

        self.assertEqual(validate_logging(configuration), 3)
        validate_web_exposure(configuration)

    def test_rejects_web_port_published_on_all_interfaces(self):
        configuration = {"services": {"web": {"ports": [{
            "target": 80, "published": "8080", "protocol": "tcp",
            "host_ip": "0.0.0.0",
        }]}}}

        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            validate_web_exposure(configuration)

    def test_rejects_host_published_api_port(self):
        configuration = {"services": {
            "web": {"ports": [{"target": 80, "host_ip": "127.0.0.1"}]},
            "api": {"ports": [{"target": 8000, "host_ip": "127.0.0.1"}]},
        }}

        with self.assertRaisesRegex(ValueError, "Only the web service"):
            validate_web_exposure(configuration)

    def test_rejects_service_without_the_expected_rotation(self):
        configuration = {"services": {
            "api": {"logging": {
                "driver": "json-file",
                "options": {"max-size": "10m", "max-file": "5"},
            }},
            "worker": {},
        }}

        with self.assertRaisesRegex(ValueError, "worker"):
            validate_logging(configuration)

    def test_rejects_empty_or_missing_services(self):
        for configuration in ({}, {"services": {}}):
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(ValueError, "must define services"):
                    validate_logging(configuration)

    def test_accepts_caddy_public_ports_in_tls_mode(self):
        configuration = {"services": {
            "web": {},
            "caddy": {"ports": [
                {"target": 80, "published": "80", "protocol": "tcp"},
                {"target": 443, "published": "443", "protocol": "tcp"},
                {"target": 443, "published": "443", "protocol": "udp"},
            ]},
        }}

        validate_web_exposure(configuration, tls=True)

    def test_rejects_web_port_in_tls_mode(self):
        configuration = {"services": {
            "web": {"ports": [{"target": 80, "published": 8080}]},
            "caddy": {"ports": [
                {"target": 80, "published": "80", "protocol": "tcp"},
                {"target": 443, "published": "443", "protocol": "tcp"},
                {"target": 443, "published": "443", "protocol": "udp"},
            ]},
        }}

        with self.assertRaisesRegex(ValueError, "must not publish the web"):
            validate_web_exposure(configuration, tls=True)

    def test_rejects_extra_public_port_in_tls_mode(self):
        configuration = {"services": {
            "web": {},
            "caddy": {"ports": [
                {"target": 80, "published": "80", "protocol": "tcp"},
                {"target": 443, "published": "443", "protocol": "tcp"},
                {"target": 443, "published": "443", "protocol": "udp"},
                {"target": 2019, "published": "2019", "protocol": "tcp"},
            ]},
        }}

        with self.assertRaisesRegex(ValueError, "only Caddy ports"):
            validate_web_exposure(configuration, tls=True)


if __name__ == "__main__":
    unittest.main()
