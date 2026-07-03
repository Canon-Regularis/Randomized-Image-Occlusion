"""Per-note card options: the choices that shape a note's generated cards.

These four settings are chosen together in the editor and consumed together when
a note is built, so they are grouped into one immutable value object rather than
threaded as four loose parameters through every layer.

The choice values are ``str``-backed enums so they are type-safe in Python yet
compare and serialise as the exact same lowercase strings the renderer and the
config already use. ``StrEnum`` (3.11+) is avoided for Python 3.10 support; JSON
serialisation always goes through ``.value`` so the on-the-wire payload is
byte-identical regardless of enum ``__str__`` behaviour.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

__all__ = ["CardMode", "CardOptions", "Direction", "Interaction"]

_Choice = TypeVar("_Choice", bound="_StrChoice")


class _StrChoice(str, Enum):
    """Base for string-valued choice enums with a total ``coerce``."""

    @classmethod
    def coerce(cls: type[_Choice], value: Any, default: _Choice) -> _Choice:
        """Return the matching member, or ``default`` for anything unrecognised.

        Never raises, so a hand-edited config value can't crash the save path.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return default


class Direction(_StrChoice):
    """Which cards a note generates."""

    FORWARD = "forward"  # name the arrowed structure
    REVERSE = "reverse"  # given the name, locate the structure
    BOTH = "both"  # one forward + one reverse card per structure


class Interaction(_StrChoice):
    """How the learner answers a card."""

    REVEAL = "reveal"  # flip to see the label
    TYPE = "type"  # type the name; graded by Anki in multi, the cycler in single


class CardMode(_StrChoice):
    """The card model for a note."""

    MULTI = "multi"  # one card per structure
    SINGLE = "single"  # one card that cycles through all structures


@dataclass(frozen=True, slots=True)
class CardOptions:
    """The per-note choices that determine how a note's cards are generated."""

    direction: Direction = Direction.FORWARD
    interaction: Interaction = Interaction.REVEAL
    context_labels: bool = False
    mode: CardMode = CardMode.MULTI

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> CardOptions:
        """Build the editor's default options from the add-on config mapping.

        The config persists the card model under the key ``card_mode`` (a stable
        key in users' profiles), which maps to :attr:`mode` — this method is the
        single place that translation lives.
        """
        return cls(
            direction=Direction.coerce(config.get("direction"), Direction.FORWARD),
            interaction=Interaction.coerce(
                config.get("interaction"), Interaction.REVEAL
            ),
            context_labels=bool(config.get("show_context_labels", False)),
            mode=CardMode.coerce(config.get("card_mode"), CardMode.MULTI),
        )
