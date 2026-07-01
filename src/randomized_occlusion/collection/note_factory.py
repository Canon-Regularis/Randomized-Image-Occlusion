"""Pure transformation from a structure set into note field values."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.structure_set import StructureSet
from ..notetype.spec import NoteTypeSpec
from .gateways import image_field_html


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
        direction: str = "forward",
        header: str = "",
        back_extra: str = "",
    ) -> NoteContent:
        spec = self._spec
        fields = {
            spec.image_field: image_field_html(image_filename),
            spec.structures_field: structures.to_payload_base64(direction),
            spec.cloze_field: structures.cloze_field(direction),
            spec.header_field: header,
            spec.back_extra_field: back_extra,
        }
        return NoteContent(
            notetype_name=spec.name,
            deck_name=deck_name,
            fields=fields,
        )
