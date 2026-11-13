from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot
from typing import Sequence


@dataclass(frozen=True)
class GaugeReading:
    value: float
    pointer_progress_deg: float
    scale_span_deg: float
    in_range: bool
    confidence: float
    unit: str = "MPa"


class GaugeGeometryError(ValueError):
    """Raised when gauge keypoints do not define a usable scale."""


def _angle(center: Sequence[float], point: Sequence[float]) -> float:
    dx = float(point[0]) - float(center[0])
    dy = float(point[1]) - float(center[1])
    if hypot(dx, dy) < 1e-8:
        raise GaugeGeometryError("关键点与表盘圆心重合，无法计算角度。")
    # Image coordinates have y pointing down; atan2 therefore increases clockwise.
    return degrees(atan2(dy, dx)) % 360.0


def _clockwise_delta(start_deg: float, end_deg: float) -> float:
    return (end_deg - start_deg) % 360.0


def read_pointer_gauge(
    center_xy: Sequence[float],
    zero_tick_xy: Sequence[float],
    max_tick_xy: Sequence[float],
    pointer_tip_xy: Sequence[float],
    scale_min: float = 0.0,
    scale_max: float = 1.6,
    min_usable_span_deg: float = 20.0,
) -> GaugeReading:
    """Compute a linear pointer-gauge reading from four 2-D keypoints.

    This is a geometry baseline, not a trained keypoint detector. Perspective
    correction and nonlinear scale calibration are outside this function.
    """
    if len(center_xy) != 2 or any(len(p) != 2 for p in
                                  (zero_tick_xy, max_tick_xy, pointer_tip_xy)):
        raise GaugeGeometryError("圆心、零刻度、满量程和指针尖端均须为二维坐标。")
    if scale_max <= scale_min:
        raise GaugeGeometryError("scale_max 必须大于 scale_min。")

    zero_angle = _angle(center_xy, zero_tick_xy)
    max_angle = _angle(center_xy, max_tick_xy)
    pointer_angle = _angle(center_xy, pointer_tip_xy)
    span = _clockwise_delta(zero_angle, max_angle)
    progress = _clockwise_delta(zero_angle, pointer_angle)

    if span < min_usable_span_deg or span > 359.0:
        raise GaugeGeometryError(f"无效表盘角度跨度: {span:.2f}°")
    in_range = progress <= span
    ratio = min(max(progress / span, 0.0), 1.0)
    value = scale_min + ratio * (scale_max - scale_min)

    # Confidence reflects geometry validity only; it is not a calibrated probability.
    confidence = 0.95 if in_range else 0.55
    return GaugeReading(
        value=round(value, 4),
        pointer_progress_deg=round(progress, 3),
        scale_span_deg=round(span, 3),
        in_range=in_range,
        confidence=confidence,
    )
