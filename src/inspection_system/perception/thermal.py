from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Sequence

from ..models import Severity


@dataclass(frozen=True)
class ThermalHotspot:
    x: int
    y: int
    width: int
    height: int
    area_px: int
    max_temp_c: float
    mean_temp_c: float
    delta_t_c: float
    severity: Severity


def analyze_temperature_matrix(
    matrix: Sequence[Sequence[float]],
    ambient_temp_c: float,
    warning_temp_c: float = 55.0,
    critical_temp_c: float = 60.0,
    min_area_px: int = 1,
) -> list[ThermalHotspot]:
    """Extract 8-connected hot regions from a rectangular temperature matrix.

    Values must already be expressed in degrees Celsius. This function does not
    perform radiometric calibration and must not be treated as a real thermal
    camera calibration pipeline.
    """
    if not matrix or not matrix[0]:
        raise ValueError("温度矩阵不能为空。")
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise ValueError("温度矩阵每一行的长度必须一致。")
    if critical_temp_c < warning_temp_c:
        raise ValueError("critical_temp_c 不能低于 warning_temp_c。")
    if min_area_px < 1:
        raise ValueError("min_area_px 必须至少为 1。")

    height = len(matrix)
    hot = [[float(matrix[y][x]) >= warning_temp_c for x in range(width)]
           for y in range(height)]
    visited = [[False] * width for _ in range(height)]
    hotspots: list[ThermalHotspot] = []
    neighbors = [(-1, -1), (0, -1), (1, -1), (-1, 0),
                 (1, 0), (-1, 1), (0, 1), (1, 1)]

    for y0 in range(height):
        for x0 in range(width):
            if not hot[y0][x0] or visited[y0][x0]:
                continue
            queue = deque([(x0, y0)])
            visited[y0][x0] = True
            points: list[tuple[int, int]] = []
            while queue:
                x, y = queue.popleft()
                points.append((x, y))
                for dx, dy in neighbors:
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < width and 0 <= ny < height
                            and hot[ny][nx] and not visited[ny][nx]):
                        visited[ny][nx] = True
                        queue.append((nx, ny))
            if len(points) < min_area_px:
                continue
            values = [float(matrix[y][x]) for x, y in points]
            max_temp = max(values)
            severity = (Severity.CRITICAL if max_temp >= critical_temp_c
                        else Severity.WARNING)
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            hotspots.append(ThermalHotspot(
                x=min(xs), y=min(ys), width=max(xs) - min(xs) + 1,
                height=max(ys) - min(ys) + 1, area_px=len(points),
                max_temp_c=round(max_temp, 3),
                mean_temp_c=round(sum(values) / len(values), 3),
                delta_t_c=round(max_temp - ambient_temp_c, 3),
                severity=severity,
            ))
    return sorted(hotspots, key=lambda item: item.max_temp_c, reverse=True)
