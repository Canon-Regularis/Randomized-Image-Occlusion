"""Pure transformation from a structure set into note field values."""

from __future__ import annotations

import html
from dataclasses import dataclass

from ..domain.card_options import CardMode, CardOptions, Interaction
from ..domain.structure_set import StructureSet
from ..notetype.spec import NoteTypeSpec

__all__ = ["NoteContent", "NoteFactory"]

_DEFAULT_OPTIONS = CardOptions()


def _image_field_html(filename: str) -> str:
    """Build the ``<img>`` tag stored in the ``Image`` field.

    Storing a real ``<img src=...>`` (rather than a bare filename) ensures
    Anki's "Check Media" sees the reference and never garbage-collects the file.
    """
    return f'<img src="{html.escape(filename, quote=True)}">'


@dataclass(frozen=True, slots=True)
class NoteContent:
    """The fully-resolved field values for a single note, ready to be added."""

    notetype_name: str
    deck_name: str
    fields: dict[str, str]


class NoteFactory:
    """Builds :class:`NoteContent` from domain objects.

    Deliberately pure: it takes an already-stored image *filename* (the media
    side effect happens elsewhere) and returns plain data, so it can be unit
    tested without Anki.
    """

    def __init__(self, spec: NoteTypeSpec) -> None:
        self._spec = spec

    def build(
        self,
        *,
        image_filename: str,
        structures: StructureSet,
        deck_name: str,
        options: CardOptions = _DEFAULT_OPTIONS,
        header: str = "",
        back_extra: str = "",
    ) -> NoteContent:
        spec = self._spec
        # Single mode drives typing itself (a JS-graded cycler), so the native
        # {{type:cloze}} box is never used for it.
        native_type = (
            options.interaction == Interaction.TYPE and options.mode != CardMode.SINGLE
        )
        fields = {
            spec.image_field: _image_field_html(image_filename),
            spec.structures_field: structures.to_payload_base64(options),
            spec.cloze_field: structures.cloze_field(options),
            spec.header_field: header,
            spec.back_extra_field: back_extra,
            # A non-empty flag makes {{#TypeAnswer}} render the type-in box.
            spec.type_flag_field: "1" if native_type else "",
        }
        return NoteContent(
            notetype_name=spec.name,
            deck_name=deck_name,
            fields=fields,
        )
