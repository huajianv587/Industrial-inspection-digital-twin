from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def validate_logging(configuration: dict[str, Any]) -> int:
    services = configuration.get("services")
    if not isinstance(services, dict) or not services:
        raise ValueError("Compose configuration must define services.")

    invalid = [
        name for name, service in services.items()
        if not isinstance(service, dict)
        or service.get("logging") != {
            "driver": "json-file",
            "options": {"max-file": "5", "max-size": "10m"},
        }
    ]
    if invalid:
        raise ValueError("Compose log rotation is missing or incorrect for: "
                         + ", ".join(invalid))
    return len(services)


def validate_web_exposure(configuration: dict[str, Any], *, tls: bool = False) -> None:
    services = configuration.get("services")
    if not isinstance(services, dict) or "web" not in services:
        raise ValueError("Compose configuration must define the web service.")

    published_services = [
        (name, port)
        for name, service in services.items()
        if isinstance(service, dict)
        for port in service.get("ports", [])
    ]
    if tls:
        if "caddy" not in services:
            raise ValueError("TLS configuration must define the caddy service.")
        if any(name == "web" for name, _ in published_services):
            raise ValueError("TLS configuration must not publish the web service.")
        if any(name != "caddy" for name, _ in published_services):
            raise ValueError("Only the caddy service may publish host ports in TLS mode.")
        caddy_ports = published_services
        expected = {(80, 80, "tcp"), (443, 443, "tcp"), (443, 443, "udp")}
        actual = {
            (int(port.get("target")), int(port.get("published")),
             port.get("protocol", "tcp"))
            for _, port in caddy_ports
            if isinstance(port, dict)
        }
        if actual != expected:
            raise ValueError("TLS mode must publish only Caddy ports 80/tcp, 443/tcp and 443/udp.")
        if any(
            port.get("host_ip") not in (None, "", "0.0.0.0", "::")
            for _, port in caddy_ports
            if isinstance(port, dict)
        ):
            raise ValueError("TLS Caddy ports must be publicly reachable, not loopback-only.")
        return

    if len(published_services) != 1 or published_services[0][0] != "web":
        raise ValueError("Only the web service may publish a host port.")

    port = published_services[0][1]
    if (not isinstance(port, dict) or port.get("target") != 80
            or port.get("host_ip") != "127.0.0.1"):
        raise ValueError("The web HTTP port must be bound to 127.0.0.1 only.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tls", action="store_true", help="validate the public Caddy TLS overlay")
    args = parser.parse_args()
    try:
        configuration = json.load(sys.stdin)
        count = validate_logging(configuration)
        validate_web_exposure(configuration, tls=args.tls)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Compose validation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Compose logging and host exposure validated for {count} services.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
