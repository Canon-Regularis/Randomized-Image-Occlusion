from __future__ import annotations

import pytest

from randomized_occlusion.domain.geometry import NormalizedPoint


def test_accepts_unit_interval_bounds():
    assert NormalizedPoint(0.0, 1.0).to_dict() == {"x": 0.0, "y": 1.0}


@pytest.mark.parametrize("x,y", [(-0.01, 0.5), (0.5, 1.01), (1.5, 0.5)])
def test_rejects_out_of_range(x, y):
    with pytest.raises(ValueError):
        NormalizedPoint(x, y)


def test_rejects_nan():
    with pytest.raises(ValueError):
        NormalizedPoint(float("nan"), 0.5)


def test_is_immutable():
    point = NormalizedPoint(0.2, 0.3)
    with pytest.raises(AttributeError):  # frozen dataclass
        point.x = 0.9  # type: ignore[misc]


def test_roundtrip_dict():
    point = NormalizedPoint(0.42, 0.67)
    assert NormalizedPoint.from_dict(point.to_dict()) == point


def test_coordinates_are_stored_as_floats():
    # The payload is JSON; an int here would serialise as `0` rather than `0.0`,
    # and a Decimal or numpy scalar would not serialise at all.
    point = NormalizedPoint(x=0, y=1)
    assert isinstance(point.x, float)
    assert isinstance(point.y, float)
    assert repr(point.x) == "0.0"
