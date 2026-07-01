"""The single, undo-safe entry point that mutates the collection.

Everything that changes the database — installing the note type, importing the
image into media, and adding the note — happens inside one ``CollectionOp`` so
it runs off the UI thread, refreshes the UI, and collapses into a single undo
step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from aqt.operations import CollectionOp

from ..collection.gateways import AnkiMediaGateway, AnkiModelGateway
from ..collection.note_factory import NoteFactory
from ..config.render_config import RenderConfig
from ..domain.structure_set import StructureSet
from ..notetype.installer import NoteTypeInstaller
from ..notetype.spec import DEFAULT_SPEC, NoteTypeSpec
from ..notetype.templates import TemplateAssembler
from ..resources import read_web

_UNDO_NAME = "Add Randomized Occlusion note"


@dataclass(frozen=True, slots=True)
class NoteRequest:
    """Everything needed to create one note, gathered from the editor."""

    image_path: str
    structures: StructureSet
    deck_name: str
    header: str = ""
    back_extra: str = ""


def add_randomized_occlusion_note(
    *,
    parent: Any,
    request: NoteRequest,
    render_config: RenderConfig,
    spec: NoteTypeSpec = DEFAULT_SPEC,
    on_success: Callable[[Any], None] | None = None,
) -> None:
    """Run the note-creation ``CollectionOp`` in the background."""

    def op(col: Any) -> Any:
        # Ensure the note type exists/updated BEFORE opening the undo entry.
        # add_dict/update_dict perform a schema change that clears Anki's undo
        # queue; doing it inside the entry would invalidate the "Add note" undo
        # step. In normal use this is a no-op — bootstrap installs the note type
        # at profile open, so nothing here changes the schema.
        assembler = TemplateAssembler(spec, read_web("review/render.js"))
        installer = NoteTypeInstaller(AnkiModelGateway(col), assembler, spec)
        installer.ensure_installed(render_config)

        undo_position = col.add_custom_undo_entry(_UNDO_NAME)
        filename = AnkiMediaGateway(col).add_image(request.image_path)
        content = NoteFactory(spec).build(
            image_filename=filename,
            structures=request.structures,
            deck_name=request.deck_name,
            direction=render_config.direction,
            header=request.header,
            back_extra=request.back_extra,
        )

        notetype = col.models.by_name(content.notetype_name)
        note = col.new_note(notetype)
        for name, value in content.fields.items():
            note[name] = value
        deck_id = col.decks.id(content.deck_name, create=True)
        col.add_note(note, deck_id)

        return col.merge_undo_entries(undo_position)

    operation = CollectionOp(parent=parent, op=op)
    if on_success is not None:
        operation = operation.success(on_success)
    operation.run_in_background()
