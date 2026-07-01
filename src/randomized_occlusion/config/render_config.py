"""The subset of configuration that shapes how a card renders.

``RenderConfig`` is the single translation point between the add-on's snake_case
Python config and the two representations the card needs:
  * a camelCase JSON blob the reviewer JavaScript reads, and
  * a set of CSS custom properties the note-type stylesheet reads.

Centralising this mapping (rather than scattering string keys across the
template code) keeps the JS/CSS contract in one auditable place.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .defaults import DEFAULT_CONFIG

__all__ = ["RenderConfig"]

# Strings a user might type into config.json that should read as ``False``.
_FALSEY_STRINGS = {"false", "0", "no", "off", "", "none"}

# A conservative allow-list for CSS colours. These values are written verbatim
# into the note type's stylesheet, so anything not matching (which could break
# the CSS or inject rules) is rejected in favour of the default.
_COLOR_RE = re.compile(
    r"^(#[0-9A-Fa-f]{3,8}"
    r"|[A-Za-z]+"
    r"|(?:rgb|rgba|hsl|hsla)\([0-9.,%\s/]+\))$"
)


def _as_float(value: Any, default: float, *, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def _as_int(value: Any, default: int, *, minimum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, number)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in _FALSEY_STRINGS
    return default


def _as_str(value: Any, default: str) -> str:
    return default if value is None else str(value)


def _as_color(value: Any, default: str) -> str:
    text = "" if value is None else str(value).strip()
    return text if _COLOR_RE.match(text) else default


@dataclass(frozen=True, slots=True)
class RenderConfig:
    """The config that actually shapes the installed template/CSS.

    Per-note choices (direction/interaction/mode) live on
    :class:`~randomized_occlusion.domain.card_options.CardOptions`, not here —
    this object only carries values baked into the note type's HTML/CSS/JS.
    """

    min_arrow_fraction: float
    show_target_dot: bool
    prompt_text: str
    max_placement_attempts: int
    show_decoy_dots: bool
    show_context_labels: bool
    accent_color: str
    box_fill: str
    box_text_color: str
    target_dot_color: str

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> RenderConfig:
        """Build from a (possibly partial) config mapping.

        This is *total*: any missing, wrongly-typed, or out-of-range value falls
        back to its default rather than raising. A user hand-editing config.json
        must never be able to make a card fail to render or crash the save path.
        """

        def get(key: str) -> Any:
            return config.get(key, DEFAULT_CONFIG[key])

        return cls(
            min_arrow_fraction=_as_float(
                get("min_arrow_fraction"),
                DEFAULT_CONFIG["min_arrow_fraction"],
                low=0.0,
                high=1.0,
            ),
            show_target_dot=_as_bool(
                get("show_target_dot"), DEFAULT_CONFIG["show_target_dot"]
            ),
            prompt_text=_as_str(get("prompt_text"), DEFAULT_CONFIG["prompt_text"]),
            max_placement_attempts=_as_int(
                get("max_placement_attempts"),
                DEFAULT_CONFIG["max_placement_attempts"],
                minimum=1,
            ),
            show_decoy_dots=_as_bool(
                get("show_decoy_dots"), DEFAULT_CONFIG["show_decoy_dots"]
            ),
            show_context_labels=_as_bool(
                get("show_context_labels"), DEFAULT_CONFIG["show_context_labels"]
            ),
            accent_color=_as_color(get("accent_color"), DEFAULT_CONFIG["accent_color"]),
            box_fill=_as_color(get("box_fill"), DEFAULT_CONFIG["box_fill"]),
            box_text_color=_as_color(
                get("box_text_color"), DEFAULT_CONFIG["box_text_color"]
            ),
            target_dot_color=_as_color(
                get("target_dot_color"), DEFAULT_CONFIG["target_dot_color"]
            ),
        )

    def behaviour(self) -> dict[str, Any]:
        """The behaviour settings ``render.js`` reads from ``#ro-config``.

        camelCase keys matching the JS; the template encodes this to base64 JSON.
        """
        return {
            "minArrowFraction": self.min_arrow_fraction,
            "showTargetDot": self.show_target_dot,
            "promptText": self.prompt_text,
            "maxPlacementAttempts": self.max_placement_attempts,
            "showDecoyDots": self.show_decoy_dots,
            "showContextLabels": self.show_context_labels,
        }

    def css_variables(self) -> dict[str, str]:
        """CSS custom properties injected onto ``.ro-root``."""
        return {
            "--ro-accent": self.accent_color,
            "--ro-box-fill": self.box_fill,
            "--ro-box-text": self.box_text_color,
            "--ro-dot": self.target_dot_color,
        }
