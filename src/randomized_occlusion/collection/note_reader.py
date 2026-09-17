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
from typing import Any

from ..domain.card_options import (
    CardMode,
    CardOptions,
    Direction,
    Interaction,
    coerce_bool,
)
from ..domain.codec import decode_json_b64
from ..domain.structure_set import StructureSet
from ..notetype.spec import NoteTypeSpec

__all__ = ["LoadedNote", "NoteReader", "note_fields"]


def note_fields(note: Any) -> dict[str, str]:
    """A stored note's field values keyed by field name.

    Reaches through Anki's note-dict API (``note.note_type()["flds"]`` then
    ``note[name]``) so that this one reach lives beside its consumer,
    :class:`NoteReader`, instead of being duplicated at every call site. Only
    duck-types the note, so this module stays import-pure and unit-testable with
    a stub note.
    """
    field_names = [field["name"] for field in note.note_type()["flds"]]
    return {name: note[name] for name in field_names}


@dataclass(frozen=True)
class LoadedNote:
    """Everything the editor needs to re-open an existing note for editing."""

    structures: StructureSet
    options: CardOptions
    image_filename: str
    header: str
    back_extra: str
    #: The fields exactly as stored. `header`/`back_extra` are these read as
    #: plain text for the dialog's boxes, which drops any markup they hold.
    header_source: str = ""
    back_extra_source: str = ""


#: Shown when a note's payload cannot be turned into structures at all.
_MALFORMED = "this note's structure data is malformed"

#: Tags that end a line when a field is read back as plain text. Anki's own
#: editor wraps each line in a <div>, and uses <br> inside one.
_BLOCK_TAGS = frozenset({"div", "p", "li", "tr"})


class _FieldText(HTMLParser):
    """Collects an Anki field's visible text, with its line breaks kept.

    Markup is dropped rather than shown. That matters because the field can hold
    either of two things: text this add-on wrote (escaped, so it contains no
    tags at all) or text typed into Anki's own note editor (real HTML). For the
    first, dropping tags is a no-op and ``convert_charrefs`` undoes the escape
    exactly, so the round trip is lossless and re-saving is byte-identical. For
    the second, the dialog shows the words rather than the tags -- where merely
    unescaping would have displayed ``<b>bold</b>`` as literal text and then
    escaped it on save, putting those tags on the card for the learner to read.

    Line breaks are emitted lazily, so a run of block tags cannot introduce a
    leading or trailing newline that was never in the text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._pending_break = False

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self._pending_break and self._parts:
            self._parts.append("\n")
        self._pending_break = False
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "br":
            self._pending_break = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._pending_break = True

    @property
    def text(self) -> str:
        return "".join(self._parts)


def _field_text(value: str) -> str:
    """An Anki field as plain text. Never raises: a field is user input."""
    if not value:
        return ""
    parser = _FieldText()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        # HTMLParser is lenient, but a field is whatever someone typed; showing
        # the raw value beats refusing to open the note.
        return value
    return parser.text


def _stored_ordinal(value: Any) -> int:
    """A stored high-water mark, or 0 when the note carries none.

    Only the lower bound is checked here. ``StructureSet`` discards a mark past
    the ceiling as well -- one that names a card Anki cannot address would
    otherwise be read, written straight back, and refuse every new structure for
    the life of the note -- so repeating that check here would be dead code.
    """
    try:
        ordinal = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return ordinal if ordinal > 0 else 0


def _stored_flag(value: Any) -> bool | None:
    """A boolean the payload actually stored, or ``None`` for "not stored".

    ``None`` covers both an absent key and one whose value has no boolean
    reading. render.js treats a null as absent and falls back to the global
    config, so reporting either as a stored ``False`` would bake the opposite of
    what the note currently renders with into the next save. Returning ``None``
    lets the caller apply its own default, which is the rule everywhere else.
    """
    if isinstance(value, (bool, int, float, str)):
        # coerce_bool never falls back for these, so the default is irrelevant.
        return coerce_bool(value, False)
    return None


class _ImgSrcExtractor(HTMLParser):
    """Pulls the ``src`` of the first ``<img>`` out of an ``Image`` field.

    ``HTMLParser`` resolves character references in attribute values, so an
    escaped filename (``&quot;``/``&amp;`` as written by the factory) comes back
    already unescaped: the exact basename stored in the media store.
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
    one, so this never raises; it returns an empty string the dialog treats as
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

    def read(
        self, fields: Mapping[str, str], *, context_labels_default: bool = False
    ) -> LoadedNote:
        spec = self._spec
        structures, direction, mode, context_labels, payload_interaction = (
            self._parse_payload(fields.get(spec.structures_field, ""))
        )
        # A payload predating the contextLabels key (a v1 array, or a v2 note from
        # before per-note context labels) has no stored value. render.js falls
        # back to the global config for such notes, so mirror that here via the
        # caller-supplied default; otherwise editing + saving would bake in a
        # literal False and silently suppress the labels the note currently shows.
        if context_labels is None:
            context_labels = context_labels_default
        # The interaction (type vs reveal) is carried in the payload for every
        # note. Notes that predate that key fall back to the TypeAnswer field
        # (which only multi mode sets); a legacy SINGLE note has neither, so
        # default it to "type" to match how render.js renders such notes; that
        # keeps a plain edit + save from silently flipping it to reveal.
        if payload_interaction is not None:
            interaction = payload_interaction
        elif mode == CardMode.SINGLE:
            interaction = Interaction.TYPE
        else:
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
            # These land in a plain-text box, so they come back as plain text --
            # and ALSO verbatim, because the conversion is deliberately lossy
            # (an <img> a user put there through Anki's own editor has no plain
            # text at all). The dialog writes the verbatim copy back when its
            # box was never edited, so opening a note and pressing Save cannot
            # quietly strip a picture or a link out of it.
            header=_field_text(fields.get(spec.header_field, "")),
            back_extra=_field_text(fields.get(spec.back_extra_field, "")),
            header_source=fields.get(spec.header_field, ""),
            back_extra_source=fields.get(spec.back_extra_field, ""),
        )

    def _parse_payload(
        self, encoded: str
    ) -> tuple[StructureSet, Direction, CardMode, bool | None, Interaction | None]:
        """Decode the ``Structures`` field into (structures, direction, mode,
        context-labels, interaction), accepting both the v2 object and the legacy
        v1 array. ``context-labels`` and ``interaction`` are ``None`` when the
        payload predates those keys (the caller supplies the fallback).

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
        except ValueError as exc:
            # Every expected decode failure is a ValueError subclass: bad base64
            # (binascii.Error), invalid UTF-8 (UnicodeDecodeError), and malformed
            # JSON (json.JSONDecodeError). A genuine bug (AttributeError, etc.)
            # raises something else and is deliberately left to surface.
            raise ValueError("this note's structure data could not be decoded") from exc

        if isinstance(payload, list):
            return self._structures(payload), Direction.FORWARD, CardMode.MULTI, None, None
        if isinstance(payload, dict) and isinstance(payload.get("structures"), list):
            return (
                self._structures(
                    payload["structures"],
                    # A legacy note has no high-water mark; its highest ordinal
                    # is the right start, because nothing has been deleted yet.
                    _stored_ordinal(payload.get("nextOrd")),
                ),
                Direction.coerce(payload.get("direction"), Direction.FORWARD),
                CardMode.coerce(payload.get("mode"), CardMode.MULTI),
                _stored_flag(payload.get("contextLabels")),
                Interaction.coerce(payload.get("interaction"), Interaction.REVEAL)
                if payload.get("interaction") is not None
                else None,
            )
        raise ValueError(_MALFORMED)

    @staticmethod
    def _structures(entries: Any, next_ordinal: int = 0) -> StructureSet:
        """``StructureSet.from_dicts``, holding this module's error contract.

        ``from_dicts`` indexes ``data["ord"]`` and calls ``int``/``float`` on the
        results, so one corrupt entry escapes as KeyError, TypeError or -- for a
        value ordinary JSON can carry, such as ``1e999`` or a 400-digit integer --
        OverflowError. ``render_config`` already catches OverflowError on both its
        numeric paths for exactly this reason.

        The class promises ValueError for unreadable user data and reserves
        anything else for a genuine bug. The Browser catches ``Exception`` and
        prints it, so a bare ``KeyError('ord')`` reached the user as ``'ord'``;
        the point of this method is the message, not the crash.

        A message that already reads well is kept. ``StructureSet`` goes to
        trouble to say "structure ordinals must be distinct; got [2, 2]", which
        is something a user can act on, and replacing it with "malformed" threw
        that away.
        """
        try:
            return StructureSet.from_dicts(entries, next_ordinal=next_ordinal)
        except ValueError as exc:
            raise ValueError(str(exc) or _MALFORMED) from exc
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError(_MALFORMED) from exc
