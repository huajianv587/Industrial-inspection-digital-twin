from __future__ import annotations

from typing import Literal, Protocol

from ..models import Observation, Waypoint


class RobotAdapter(Protocol):
    source: Literal["synthetic_simulation", "robot"]

    def navigate(self, waypoint: Waypoint) -> bool: ...

    def capture(self, waypoint: Waypoint, index: int) -> Observation: ...
