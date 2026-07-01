"""Value objects for the add-on's coordinate model.

All structure positions are stored as *normalized* coordinates — fractions of
the image's width and height in the closed interval ``[0, 1]``. This keeps the
data resolution-independent: the same note renders correctly whether the image
is shown at 200px on a phone or 1600px on a desktop, because the reviewer maps
these fractions onto whatever size the image is actually displayed at.

These types are intentionally free of any Anki dependency so they can be unit
tested in isolation and reused anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["NormalizedPoint"]

_UNIT_INTERVAL = (0.0, 1.0)


def _ensure_unit_interval(value: float, name: str) -> float:
    """Validate that ``value`` lies within ``[0, 1]`` and return it as a float.

    Raises:
        ValueError: if ``value`` is outside the unit interval or not finite.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} must be a real number, got {value!r}") from exc
    if number != number:  # NaN check without importing math
        raise ValueError(f"{name} must be a finite number, got NaN")
    low, high = _UNIT_INTERVAL
    if not low <= number <= high:
        raise ValueError(f"{name} must be within [{low}, {high}], got {number}")
    return number


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    """An immutable point expressed as fractions of an image's dimensions.

    ``x`` runs left (0.0) to right (1.0); ``y`` runs top (0.0) to bottom (1.0),
    matching the convention used by image/canvas coordinate systems.
    """

    x: float
    y: float

    def __post_init__(self) -> None:
        # ``frozen`` dataclasses forbid normal attribute assignment, so we go
        # through ``object.__setattr__`` to coerce the validated float values.
        object.__setattr__(self, "x", _ensure_unit_interval(self.x, "x"))
        object.__setattr__(self, "y", _ensure_unit_interval(self.y, "y"))

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> NormalizedPoint:
        return cls(x=data["x"], y=data["y"])
