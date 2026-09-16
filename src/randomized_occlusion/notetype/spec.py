"""Declarative description of the add-on's note type.

This is *data only*; it says what the note type looks like, not how to install
it (that is :class:`~randomized_occlusion.notetype.installer.NoteTypeInstaller`)
nor how to render it (that is the :mod:`templates` assembler). Splitting the
"what" from the "how" keeps each piece independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_SPEC", "NoteTypeSpec"]


@dataclass(frozen=True)
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
    #: user never edits by hand, so collapsing them keeps the Add window clean;
    #: the canvas is the way in. Header/Back Extra stay expanded.
    collapsed_fields: tuple[str, ...] = ()
    #: Fields an existing note type MUST already have. Anything in ``fields``
    #: but not here was introduced by a later version, so a note type lacking
    #: it is merely old and the installer may append it. A note type lacking
    #: one of THESE cannot be old -- it was created with them -- so the field
    #: was renamed or deleted in Anki, and appending an empty replacement
    #: would blank that field on every note of the note type while the real
    #: content sits in the renamed field, unreferenced.
    required_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject a spec that demands a field it would never create.

        Such a spec refuses EVERY existing install -- the installer looks for a
        field that is not in ``fields``, so it is never there -- and the add-on
        would report a renamed field on a note type nobody has touched. Cheaper
        to refuse the spec at import than to debug that.
        """
        unknown = tuple(n for n in self.required_fields if n not in self.fields)
        if unknown:
            raise ValueError(
                f"required_fields names {unknown}, which fields does not "
                f"declare: {self.fields}"
            )

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
    # Everything except TypeAnswer, which 1.1 added; see ``required_fields``.
    required_fields=("Image", "Structures", "Ordinals", "Header", "Back Extra"),
)
