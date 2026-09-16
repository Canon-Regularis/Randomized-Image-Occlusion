"""An ordered, validated collection of structures for a single image."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .card_options import CardMode, CardOptions
from .codec import encode_json_b64
from .structure import Structure, StructureDict

__all__ = ["MAX_ORDINAL", "StructureSet"]

#: Anki clamps any cloze number above 500 to 500, so two structures past it
#: would generate the SAME card and the rest would render "No cloze 500 found".
#: Verified against anki 26.09.2: c499 -> card ord 498, but c501 and c2000 both
#: -> card ord 499. Ordinals no longer have to be contiguous, so this is what
#: stops a note asking for one Anki cannot address.
MAX_ORDINAL = 500


def _some(ordinals: Sequence[int], limit: int = 6) -> str:
    """A few ordinals for an error message, never the whole list.

    A note can legitimately hold hundreds, and a message that enumerates them
    is a dialog the user has to scroll rather than something they can act on.
    """
    if len(ordinals) <= limit:
        return str(list(ordinals))
    shown = ", ".join(str(o) for o in ordinals[:limit])
    return f"[{shown}, ... {len(ordinals) - limit} more]"


def _cloze_escape(label: str) -> str:
    """Neutralise cloze *and* HTML metacharacters so a label is safe here.

    Collapse to a fixpoint, not in a single pass: a one-shot replace turns
    ``{{{{`` into ``{{``, reconstituting a live cloze opener, so a crafted
    label like ``{{{{c2::::x}}}}`` would slip a valid ``{{c2::…}}`` into the
    Ordinals field and make Anki generate a *phantom* card 2 for a note that has
    only one structure (an ordinal with no matching structure). Looping until the
    string stops changing guarantees no ``{{``, ``}}`` or ``::`` survives. Each
    pass only shortens the string, so this always terminates. (The visible answer
    comes from the base64 ``Structures`` payload, so a stronger escape here never
    changes what the learner sees.)

    The field is then rendered as HTML, immediately before the ``<script>`` tags
    carrying the payload, so a label is markup once it lands here. An unescaped
    ``<style>`` or ``<!--`` makes the tokeniser swallow everything up to the next
    closing tag, and ``#ro-data`` never becomes an element: ``readData`` finds
    nothing, ``render`` bails on an empty structure list, and EVERY OTHER card of
    the note shows a bare image -- no prompt, no arrow, no answer, no error.
    ``</div>`` is quieter and worse: ``#ro-ordinal`` closes early, so
    ``readActiveOrdinal`` finds no ``.cloze`` and falls back to 1, and every card
    of the note asks about structure 1 while Anki grades against its own. Hence
    the HTML escape.

    Finally, a label whose escaped form ends in ``}`` would merge with the
    wrapper's own ``}}``: Anki reads the first two as the closing delimiter and
    the answer loses its last character. A numeric entity keeps them apart
    without changing the text Anki grades, because rslib strips HTML and decodes
    entities on the expected side before comparing.
    """
    previous = ""
    while previous != label:
        previous = label
        label = label.replace("{{", "{").replace("}}", "}").replace("::", ":")
    # `&` first, or the entities introduced below would be escaped in turn.
    label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if label.endswith("}"):
        label = label[:-1] + "&#125;"
    return label


@dataclass(frozen=True)
class StructureSet:
    """All structures marked on one image, forming one Anki note.

    Invariants enforced at construction time:
      * at least one structure is present;
      * ordinals are positive and distinct.

    Ordinals need NOT be contiguous. Each one becomes an Anki cloze
    ``{{cN::...}}``, and Anki binds a card to its ordinal for life, so an
    ordinal is a card's identity and its whole review history. Renumbering after
    a deletion therefore hands card 2's six months of scheduling to what used to
    be structure 3 -- silently, with nothing visible in the UI. Deleting the
    second of five structures leaves ``c1, c3, c4, c5``, exactly as deleting a
    cloze by hand does in Anki's own editor: the orphaned card becomes an empty
    card for Tools > Empty Cards to clear, and every other card goes on testing
    what it always tested.
    """

    structures: tuple[Structure, ...]
    #: The next ordinal to hand out, which only ever goes up. Deleting the
    #: HIGHEST structure frees its number, and `max(surviving) + 1` would hand
    #: that number straight back to the next marker added -- which re-adopts the
    #: deleted structure's card, and its whole review history, exactly the theft
    #: the gapped ordinals exist to prevent. Carried in the payload so it
    #: survives the round trip; a legacy note without one starts at max + 1,
    #: which is right because nothing has been deleted from it yet.
    next_ordinal: int = 0

    def __post_init__(self) -> None:
        if not self.structures:
            raise ValueError("a StructureSet must contain at least one structure")
        ordinals = sorted(s.ordinal for s in self.structures)
        if len(set(ordinals)) != len(ordinals):
            raise ValueError(
                f"structure ordinals must be distinct; got {_some(ordinals)}"
            )
        # Only the upper bound is checked here: Structure itself refuses an
        # ordinal below 1, so a set cannot hold one.
        if ordinals[-1] > MAX_ORDINAL:
            # Says the rule and a remedy, and does NOT list the ordinals. An
            # older version of this add-on had no upper bound, so a note with
            # 600 structures could be saved -- and enumerating them produced a
            # ~3,000-character dialog that named neither the limit's reason nor
            # anything the user could do about it.
            raise ValueError(
                f"this note has {len(ordinals)} structures, numbered up to "
                f"{ordinals[-1]}. Anki can only address {MAX_ORDINAL} cloze "
                "deletions on one note, so it cannot be edited here. Remove "
                "some structures in Anki's own note editor first."
            )
        floor = ordinals[-1] + 1
        if self.next_ordinal < floor or self.next_ordinal > MAX_ORDINAL:
            # Below the floor it would hand out an ordinal already in use. Above
            # the ceiling it names a card Anki cannot address, so every new
            # structure would be refused for ever -- on a note that may hold
            # only two. The mark is a hint about numbering, not data, so a
            # nonsensical one is discarded and the floor stands in for it. That
            # can reuse an ordinal freed earlier on an already-corrupt note,
            # which is the lesser harm against a note nothing can add to again.
            object.__setattr__(self, "next_ordinal", floor)

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

        Ordinals are reassigned ``1..N`` in the given order, so callers creating
        a BRAND-NEW note need not manage ordinals themselves. Do not use this to
        re-save an existing note: it would renumber the survivors and move every
        later card's review history onto a different structure. Use
        :meth:`keeping_ordinals` there.
        """
        renumbered = tuple(
            Structure(ordinal=i, target=s.target, label=s.label)
            for i, s in enumerate(labels_and_points, start=1)
        )
        return cls(structures=renumbered)

    @classmethod
    def keeping_ordinals(
        cls,
        marked: Sequence[tuple[int | None, Structure]],
        *,
        next_ordinal: int = 0,
    ) -> StructureSet:
        """Build a set from ``(existing ordinal or None, structure)`` pairs.

        A structure that already has an ordinal keeps it, so its card keeps its
        scheduling. A new one is given the next ordinal after the highest ever
        used here -- never a number freed by a deletion, because Anki would hand
        the new structure the deleted one's card, and with it a review history
        that belongs to something else entirely.
        """
        # Duplicates are not checked here: __post_init__ rejects them for every
        # construction path, and one message for one rule reads better than two.
        #
        # `next_ordinal` is the note's own high-water mark, and it is what makes
        # "never a number freed by a deletion" true even when the deletion was
        # the highest structure -- `max(kept)` alone drops back the moment the
        # top one goes.
        kept = [ordinal for ordinal, _ in marked if ordinal is not None]
        nxt = max(max(kept, default=0) + 1, next_ordinal)
        out = []
        for ordinal, structure in marked:
            if ordinal is None:
                ordinal, nxt = nxt, nxt + 1
            out.append(
                Structure(ordinal=ordinal, target=structure.target, label=structure.label)
            )
        return cls(structures=tuple(out), next_ordinal=nxt)

    # -- serialization ---------------------------------------------------------

    @classmethod
    def from_dicts(
        cls, items: Sequence[StructureDict], *, next_ordinal: int = 0
    ) -> StructureSet:
        """Build a set from already-parsed structure dicts (the payload's
        ``structures``).

        Ordinals are taken as given. Unlike :meth:`from_unordered`, this does
        *not* renumber: an ordinal maps to an Anki cloze card ordinal and so to
        that card's review history, and a note edited since its creation can
        legitimately carry gaps. Only duplicates and non-positive values are
        rejected, by :meth:`__post_init__`.
        """
        return cls(
            structures=tuple(Structure.from_dict(item) for item in items),
            next_ordinal=next_ordinal,
        )

    @classmethod
    def from_json(cls, payload: str) -> StructureSet:
        """Deserialize a JSON array of structure dicts (the payload's
        ``structures``)."""
        return cls.from_dicts(json.loads(payload))

    # -- anki helpers ----------------------------------------------------------

    def card_count(self, options: CardOptions) -> int:
        """How many cards Anki will generate for these options.

        One per cloze ordinal in :meth:`cloze_field`, which is one per
        structure in multi mode and exactly ONE in single mode however many
        structures there are. Reporting ``len(structures)`` told a user who
        marked five structures in single mode "Added 5 cards." and gave them
        one.
        """
        return 1 if options.mode == CardMode.SINGLE else len(self.ordered)

    def cloze_field(self, options: CardOptions) -> str:
        """The contents of the hidden cloze field that generates the cards.

        Each ``{{cN::...}}`` makes Anki emit one card; the renderer reads the
        active cloze's ``data-ordinal`` to learn which structure this card tests.
        The label is the cloze answer so "type-to-answer" mode
        (``{{type:cloze:...}}``) can grade what the learner types, and labels are
        escaped so cloze syntax can't break the field.

        KNOWN LIMITATION: the escaping (:func:`_cloze_escape`) is what Anki's
        NATIVE type box grades against, so a label containing ``::``, ``{{`` or
        ``}}`` (e.g. ``std::vector``) is graded in its escaped form (``std:vector``)
        even though the learner sees the raw label, so typing the displayed answer
        is marked wrong. This only affects *multi-mode type-to-answer*; the drawn
        prompt and single-mode's own grader use the raw label. Cloze metacharacters
        can't be un-escaped without breaking Anki's cloze parsing, so for labels
        with ``::``/``{{``/``}}`` use reveal or single-card mode.

        The HTML escape and the trailing-``}`` entity are a different matter: both
        survive Anki's own comparison, which strips HTML and decodes entities on
        the expected side, so a label containing ``<``, ``&`` or a trailing ``}``
        grades on exactly what the learner sees.

        Multi mode emits one card per structure. Single mode emits exactly ONE
        card whatever the structure count, and that card cycles through all of
        them (its cloze answer is inert). In multi mode the card's direction
        (forward, reverse, or, for ``Direction.BOTH``, a fresh random pick each
        review) is chosen by the renderer, not encoded in the ordinal, so all
        three directions share these clozes.
        """
        if options.mode == CardMode.SINGLE:
            return "{{c1::.}}"
        return "".join(
            f"{{{{c{s.ordinal}::{_cloze_escape(s.label)}}}}}" for s in self.ordered
        )

    def to_payload_base64(self, options: CardOptions) -> str:
        """Base64 of the per-note payload the renderer reads.

        Carries the per-note render settings (mode, direction, interaction,
        context-labels) with every structure, so a note renders correctly
        regardless of the current global config (self-describing). Enum values
        are serialised via ``.value`` so the payload stays byte-identical to the
        legacy strings.
        """
        payload = {
            "v": 2,
            "mode": options.mode.value,
            "direction": options.direction.value,
            "interaction": options.interaction.value,
            "contextLabels": options.context_labels,
            # The note's high-water mark, so a freed ordinal is never handed out
            # again after a reopen. render.js ignores the key; it exists for the
            # editor's next save.
            "nextOrd": self.next_ordinal,
            "structures": [s.to_dict() for s in self.ordered],
        }
        return encode_json_b64(payload)
