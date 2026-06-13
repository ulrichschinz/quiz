"""app.shared.charts — pure SVG geometry helpers for the results page.

Cross-cutting presentation helpers (no domain logic): turn a list of 0–100
scores into ready-to-render SVG coordinates so the results page needs no
client-side JS. Exposed to templates via a Jinja global. The donut gauge needs
no helper (a stroke-dasharray circle is pure template arithmetic); the radar
does, because it needs trigonometry Jinja can't express.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RadarAxis:
    """One spoke of the radar: the data point, the outer edge, and the label."""

    x: float  # data point, scaled by the dimension's score
    y: float
    edge_x: float  # outer edge of the spoke (the 100% ring)
    edge_y: float
    label_x: float
    label_y: float
    anchor: str  # SVG text-anchor: "start" | "middle" | "end"


@dataclass(frozen=True)
class RadarGeometry:
    size: float  # viewBox is "0 0 size size"
    cx: float
    cy: float
    radius: float
    polygon: str  # "x,y x,y …" — the filled data area
    axes: list[RadarAxis]
    rings: list[float]  # concentric grid-ring radii


def radar_geometry(
    scores: list[int],
    *,
    radius: float = 110.0,
    padding: float = 72.0,
    rings: int = 4,
) -> RadarGeometry:
    """Lay out a radar/net chart for `scores` (each 0–100), first axis at top.

    `padding` leaves room for the axis labels outside the 100% ring. A point's
    distance from the centre is proportional to its score, so 0 sits at the
    centre and 100 on the outer ring.
    """
    n = len(scores)
    center = radius + padding
    size = center * 2
    label_radius = radius + 20

    axes: list[RadarAxis] = []
    points: list[str] = []
    for i, score in enumerate(scores):
        # Start at the top (-90°) and go clockwise.
        angle = -math.pi / 2 + (2 * math.pi * i / n)
        cos_a, sin_a = math.cos(angle), math.sin(angle)

        r = radius * max(0, min(score, 100)) / 100
        x, y = center + r * cos_a, center + r * sin_a
        points.append(f"{x:.1f},{y:.1f}")

        if abs(cos_a) < 0.3:
            anchor = "middle"
        elif cos_a > 0:
            anchor = "start"
        else:
            anchor = "end"

        axes.append(
            RadarAxis(
                x=round(x, 1),
                y=round(y, 1),
                edge_x=round(center + radius * cos_a, 1),
                edge_y=round(center + radius * sin_a, 1),
                label_x=round(center + label_radius * cos_a, 1),
                label_y=round(center + label_radius * sin_a, 1),
                anchor=anchor,
            )
        )

    ring_radii = [round(radius * k / rings, 1) for k in range(1, rings + 1)]
    return RadarGeometry(
        size=round(size, 1),
        cx=round(center, 1),
        cy=round(center, 1),
        radius=radius,
        polygon=" ".join(points),
        axes=axes,
        rings=ring_radii,
    )
