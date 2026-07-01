"""An ordered, validated collection of structures for a single image."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .card_options import CardMode, CardOptions, Direction
from .codec import encode_json_b64
from .structure import Structure

__all__ = ["StructureSet"]


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

    @classmethod
    def from_json(cls, payload: str) -> StructureSet:
        """Deserialize a JSON array of structure dicts (the payload's
        ``structures``).

        Ordinals must already be contiguous ``1..N``. Unlike
        :meth:`from_unordered`, this does *not* renumber: ordinals map to Anki
        cloze card ordinals, so a corrupt/hand-edited payload with gaps should
        surface as an error rather than be silently (and wrongly) renumbered.
        """
        data = json.loads(payload)
        return cls(structures=tuple(Structure.from_dict(item) for item in data))

    # -- anki helpers ----------------------------------------------------------

    def cloze_field(self, options: CardOptions) -> str:
        """The contents of the hidden cloze field that generates the cards.

        Each ``{{cN::...}}`` makes Anki emit one card; the renderer reads the
        active cloze's ``data-ordinal`` to learn which structure/direction this
        card is. The label is the cloze answer so "type-to-answer" mode
        (``{{type:cloze:...}}``) can grade what the learner types, and labels are
        escaped so cloze syntax can't break the field.

        In single mode exactly one card is generated (one cloze); the renderer
        cycles through all structures on that single card, so the cloze answer
        content is inert. Otherwise, for ``Direction.BOTH`` each structure gets
        two consecutive ordinals (a forward and a reverse card); otherwise one.
        """
        if options.mode == CardMode.SINGLE:
            return "{{c1::.}}"
        ordered = self.ordered
        if options.direction == Direction.BOTH:
            parts = []
            for index, structure in enumerate(ordered):
                answer = _cloze_escape(structure.label)
                parts.append(f"{{{{c{2 * index + 1}::{answer}}}}}")
                parts.append(f"{{{{c{2 * index + 2}::{answer}}}}}")
            return "".join(parts)
        return "".join(
            f"{{{{c{s.ordinal}::{_cloze_escape(s.label)}}}}}" for s in ordered
        )

    def to_payload_base64(self, options: CardOptions) -> str:
        """Base64 of the per-note payload the renderer reads.

        Carries the per-note render settings (mode, direction, context-labels)
        with every structure, so a note renders correctly regardless of the
        current global config (self-describing). Enum values are serialised via
        ``.value`` so the payload stays byte-identical to the legacy strings.
        """
        payload = {
            "v": 2,
            "mode": options.mode.value,
            "direction": options.direction.value,
            "contextLabels": options.context_labels,
            "structures": [s.to_dict() for s in self.ordered],
        }
        return encode_json_b64(payload)
