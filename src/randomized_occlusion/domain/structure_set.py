"""An ordered, validated collection of structures for a single image."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from .structure import Structure


def _cloze_escape(label: str) -> str:
    """Neutralise cloze metacharacters so a label is safe as a cloze answer."""
    return label.replace("{{", "{").replace("}}", "}").replace("::", ":")


@dataclass(frozen=True, slots=True)
class StructureSet:
    """All structures marked on one image, forming one Anki note.

    Invariants enforced at construction time:
      * at least one structure is present;
      * ordinals are exactly ``1..N`` with no gaps or duplicates.

    The contiguous-ordinal invariant matters because each ordinal becomes an
    Anki cloze ``{{cN::...}}`` and therefore one generated card; gaps would
    create blank cards and break the structure<->card mapping.
    """

    structures: tuple[Structure, ...]

    def __post_init__(self) -> None:
        if not self.structures:
            raise ValueError("a StructureSet must contain at least one structure")
        ordinals = sorted(s.ordinal for s in self.structures)
        expected = list(range(1, len(self.structures) + 1))
        if ordinals != expected:
            raise ValueError(
                "structure ordinals must be exactly 1..N with no gaps or "
                f"duplicates; got {ordinals}"
            )

    def __iter__(self) -> Iterator[Structure]:
        return iter(self.structures)

    def __len__(self) -> int:
        return len(self.structures)

    @property
    def ordered(self) -> tuple[Structure, ...]:
        """Structures sorted by ascending ordinal."""
        return tuple(sorted(self.structures, key=lambda s: s.ordinal))

    # -- factory ---------------------------------------------------------------

    @classmethod
    def from_unordered(cls, labels_and_points: Sequence[Structure]) -> StructureSet:
        """Build a set from structures whose ordinals may be unset/duplicated.

        Ordinals are reassigned ``1..N`` in the given order, so callers (e.g. the
        editor) need not manage ordinals themselves.
        """
        renumbered = tuple(
            Structure(ordinal=i, target=s.target, label=s.label)
            for i, s in enumerate(labels_and_points, start=1)
        )
        return cls(structures=renumbered)

    # -- serialization ---------------------------------------------------------

    def to_json(self) -> str:
        """Compact JSON array of structures, ordered by ordinal."""
        return json.dumps(
            [s.to_dict() for s in self.ordered],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def to_base64(self) -> str:
        """Base64 of the UTF-8 JSON payload.

        The reviewer reads this out of a field and ``JSON.parse``s it. Encoding
        as base64 sidesteps every HTML/`</script>`-injection and quoting hazard
        that arbitrary label text could otherwise introduce into the template.
        """
        return base64.b64encode(self.to_json().encode("utf-8")).decode("ascii")

    @classmethod
    def from_json(cls, payload: str) -> StructureSet:
        """Deserialize a payload produced by :meth:`to_json`.

        Ordinals must already be contiguous ``1..N``. Unlike
        :meth:`from_unordered`, this does *not* renumber: ordinals map to Anki
        cloze card ordinals, so a corrupt/hand-edited payload with gaps should
        surface as an error rather than be silently (and wrongly) renumbered.
        """
        data = json.loads(payload)
        return cls(structures=tuple(Structure.from_dict(item) for item in data))

    @classmethod
    def from_base64(cls, payload: str) -> StructureSet:
        decoded = base64.b64decode(payload.encode("ascii")).decode("utf-8")
        return cls.from_json(decoded)

    # -- anki helpers ----------------------------------------------------------

    def cloze_field(self, direction: str = "forward") -> str:
        """The contents of the hidden cloze field that generates the cards.

        Each ``{{cN::...}}`` makes Anki emit one card; the renderer reads the
        active cloze's ``data-ordinal`` to learn which structure/direction this
        card is. The label is the cloze answer so "type-to-answer" mode
        (``{{type:cloze:...}}``) can grade what the learner types, and labels are
        escaped so cloze syntax can't break the field.

        For ``direction == "both"`` each structure gets two consecutive
        ordinals (a forward and a reverse card); otherwise one each.
        """
        ordered = self.ordered
        if direction == "both":
            parts = []
            for index, structure in enumerate(ordered):
                answer = _cloze_escape(structure.label)
                parts.append(f"{{{{c{2 * index + 1}::{answer}}}}}")
                parts.append(f"{{{{c{2 * index + 2}::{answer}}}}}")
            return "".join(parts)
        return "".join(
            f"{{{{c{s.ordinal}::{_cloze_escape(s.label)}}}}}" for s in ordered
        )

    def to_payload_base64(self, direction: str = "forward") -> str:
        """Base64 of the per-note payload the renderer reads.

        Carries the direction alongside every structure, so a note renders
        correctly regardless of the current global config (self-describing).
        """
        payload = {
            "v": 2,
            "direction": direction,
            "structures": [s.to_dict() for s in self.ordered],
        }
        return base64.b64encode(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).decode("ascii")

    def labels(self) -> Iterable[str]:
        return (s.label for s in self.ordered)
