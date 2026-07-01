"""Read a stored note's fields back into domain objects (the inverse of
:class:`~randomized_occlusion.collection.note_factory.NoteFactory`).

Editing an existing note reverses the build step: given the raw field values
Anki holds, reconstruct the :class:`StructureSet` and :class:`CardOptions` the
editor originally worked with, plus the header/back-extra text and the media
filename of the image. Kept pure (no Anki dependency) so the round-trip
``build -> read`` can be unit tested without a collection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser

from ..domain.card_options import CardMode, CardOptions, Direction, Interaction
from ..domain.codec import decode_json_b64
from ..domain.structure_set import StructureSet
from ..notetype.spec import NoteTypeSpec

__all__ = ["LoadedNote", "NoteReader"]


@dataclass(frozen=True, slots=True)
class LoadedNote:
    """Everything the editor needs to re-open an existing note for editing."""

    structures: StructureSet
    options: CardOptions
    image_filename: str
    header: str
    back_extra: str


class _ImgSrcExtractor(HTMLParser):
    """Pulls the ``src`` of the first ``<img>`` out of an ``Image`` field.

    ``HTMLParser`` resolves character references in attribute values, so an
    escaped filename (``&quot;``/``&amp;`` as written by the factory) comes back
    already unescaped — the exact basename stored in the media store.
    """

    def __init__(self) -> None:
        super().__init__()
        self.src: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "img" and self.src is None:
            for name, value in attrs:
                if name == "src" and value:
                    self.src = value


def _extract_image_filename(image_field: str) -> str:
    """The media basename referenced by an ``Image`` field, or ``""`` if none.

    A missing/odd image is non-fatal for editing: the user can simply load a new
    one, so this never raises — it returns an empty string the dialog treats as
    "no current image".
    """
    parser = _ImgSrcExtractor()
    parser.feed(image_field or "")
    parser.close()
    return parser.src or ""


class NoteReader:
    """Rebuilds domain objects from a note's stored field values."""

    def __init__(self, spec: NoteTypeSpec) -> None:
        self._spec = spec

    def read(self, fields: Mapping[str, str]) -> LoadedNote:
        spec = self._spec
        structures, direction, mode, context_labels = self._parse_payload(
            fields.get(spec.structures_field, "")
        )
        # The native type-in box is the only thing that distinguishes "reveal"
        # from "type" in the stored fields (single mode never uses it, so single
        # notes always read back as "reveal" — harmless, its own JS typer runs
        # regardless). A non-empty flag means the note was built with type-in on.
        interaction = (
            Interaction.TYPE
            if str(fields.get(spec.type_flag_field, "")).strip()
            else Interaction.REVEAL
        )
        options = CardOptions(
            direction=direction,
            interaction=interaction,
            context_labels=context_labels,
            mode=mode,
        )
        return LoadedNote(
            structures=structures,
            options=options,
            image_filename=_extract_image_filename(fields.get(spec.image_field, "")),
            header=fields.get(spec.header_field, ""),
            back_extra=fields.get(spec.back_extra_field, ""),
        )

    def _parse_payload(
        self, encoded: str
    ) -> tuple[StructureSet, Direction, CardMode, bool]:
        """Decode the ``Structures`` field into (structures, direction, mode,
        context-labels), accepting both the v2 object and the legacy v1 array.

        Mirrors the reviewer's ``readData``: a bare array is a pre-settings note
        (multi / forward / no context labels); the v2 object is self-describing.
        Anything else is unreadable and raises ``ValueError`` so the caller can
        tell the user rather than open the editor with empty/garbage state.
        """
        encoded = (encoded or "").strip()
        if not encoded:
            raise ValueError("this note has no stored structures to edit")
        try:
            payload = decode_json_b64(encoded)
        except Exception as exc:  # binascii / unicode / json errors
            raise ValueError("this note's structure data could not be decoded") from exc

        if isinstance(payload, list):
            return StructureSet.from_dicts(payload), Direction.FORWARD, CardMode.MULTI, False
        if isinstance(payload, dict) and isinstance(payload.get("structures"), list):
            return (
                StructureSet.from_dicts(payload["structures"]),
                Direction.coerce(payload.get("direction"), Direction.FORWARD),
                CardMode.coerce(payload.get("mode"), CardMode.MULTI),
                bool(payload.get("contextLabels")),
            )
        raise ValueError("this note's structure data is malformed")
