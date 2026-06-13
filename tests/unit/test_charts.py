"""Unit tests for the pure SVG radar-geometry helper."""

from __future__ import annotations

import math

from app.shared.charts import radar_geometry


def test_radar_has_one_axis_and_point_per_score() -> None:
    geo = radar_geometry([100, 50, 0, 75])
    assert len(geo.axes) == 4
    assert len(geo.polygon.split()) == 4  # one "x,y" token per score
    assert len(geo.rings) == 4  # default ring count


def test_radar_first_axis_points_to_top() -> None:
    # First axis sits at -90° (straight up): same x as centre, y = centre - r.
    geo = radar_geometry([100, 100, 100], radius=100.0, padding=50.0)
    top = geo.axes[0]
    assert math.isclose(top.x, geo.cx, abs_tol=0.1)
    assert math.isclose(top.y, geo.cy - geo.radius, abs_tol=0.1)


def test_radar_scales_point_distance_by_score() -> None:
    # A 0 score sits at the centre; 100 sits on the outer ring.
    geo = radar_geometry([0, 100, 100], radius=100.0, padding=50.0)
    centre_pt = geo.axes[0]
    assert math.isclose(centre_pt.x, geo.cx, abs_tol=0.1)
    assert math.isclose(centre_pt.y, geo.cy, abs_tol=0.1)


def test_radar_size_accounts_for_label_padding() -> None:
    geo = radar_geometry([100, 50, 25], radius=110.0, padding=72.0)
    assert geo.size == (110.0 + 72.0) * 2
    assert geo.cx == geo.cy == 110.0 + 72.0
