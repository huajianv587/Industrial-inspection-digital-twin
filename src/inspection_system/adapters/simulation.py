from __future__ import annotations
from dataclasses import dataclass, field
from ..models import Observation, Waypoint
from ..synthetic import reference_observation

@dataclass
class SimulatedRobotAdapter:
    """Deterministic navigation/sensor adapter; no robot or simulator is connected."""
    robot_id: str
    fail_waypoints: set[str] = field(default_factory=set)
    event_log: list[dict[str, str]] = field(default_factory=list)
    source = "synthetic_simulation"

    def navigate(self, waypoint: Waypoint) -> bool:
        if waypoint.waypoint_id in self.fail_waypoints:
            self.event_log.append({"event": "navigation_failed", "waypoint_id": waypoint.waypoint_id})
            return False
        self.event_log.append({"event": "navigation_succeeded", "waypoint_id": waypoint.waypoint_id})
        return True

    def capture(self, waypoint: Waypoint, index: int) -> Observation:
        self.event_log.append({"event": "synthetic_capture", "waypoint_id": waypoint.waypoint_id})
        return reference_observation(waypoint, self.robot_id, index)
