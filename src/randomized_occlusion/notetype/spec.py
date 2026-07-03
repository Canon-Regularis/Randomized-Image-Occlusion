"""Declarative description of the add-on's note type.

This is *data only* — it says what the note type looks like, not how to install
it (that is :class:`~randomized_occlusion.notetype.installer.NoteTypeInstaller`)
nor how to render it (that is the :mod:`templates` assembler). Splitting the
"what" from the "how" keeps each piece independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_SPEC", "NoteTypeSpec"]


@dataclass(frozen=True, slots=True)
class NoteTypeSpec:
    """Field layout and identity of the note type."""

    name: str
    fields: tuple[str, ...]
    cloze_field: str
    image_field: str
    structures_field: str
    header_field: str
    back_extra_field: str
    type_flag_field: str
    sort_field: str
    template_name: str
    #: Fields collapsed by default in Anki's editor. These hold machine data
    #: (the image tag, the base64 payload, the cloze ordinals, the type flag) the
    #: user never edits by hand, so collapsing them keeps the Add window clean —
    #: the visual canvas is the way in. Header/Back Extra stay expanded.
    collapsed_fields: tuple[str, ...] = ()

    @property
    def sort_index(self) -> int:
        return self.fields.index(self.sort_field)


#: The single canonical specification used throughout the add-on.
#:
#: Field roles:
#:   * ``Image``       — the picture, stored as a full ``<img src=...>`` tag so
#:                       Anki's media check keeps the file.
#:   * ``Structures``  — base64-encoded JSON of every structure on the image.
#:   * ``Ordinals``    — hidden cloze field (``{{c1::<label>}}...{{cN::<label>}}``
#:                       in multi mode, ``{{c1::.}}`` in single) that drives
#:                       one-card-per-structure generation.
#:   * ``Header``      — optional title shown above the image.
#:   * ``Back Extra``  — optional notes revealed on the answer side.
#:   * ``TypeAnswer``  — per-note flag ("1" or empty); when set the card shows a
#:                       native type-in box (``{{type:cloze:...}}``).
DEFAULT_SPEC = NoteTypeSpec(
    name="Randomized Image Occlusion",
    fields=("Image", "Structures", "Ordinals", "Header", "Back Extra", "TypeAnswer"),
    cloze_field="Ordinals",
    image_field="Image",
    structures_field="Structures",
    header_field="Header",
    back_extra_field="Back Extra",
    type_flag_field="TypeAnswer",
    sort_field="Header",
    template_name="Randomized Occlusion",
    collapsed_fields=("Image", "Structures", "Ordinals", "TypeAnswer"),
)
