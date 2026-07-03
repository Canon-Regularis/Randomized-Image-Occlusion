"""The single, undo-safe entry point that mutates the collection.

Everything that changes the database — installing the note type, importing the
image into media, and adding the note — happens inside one ``CollectionOp`` so
it runs off the UI thread, refreshes the UI, and collapses into a single undo
step.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..collection.gateways import AnkiMediaGateway
from ..collection.note_factory import NoteFactory
from ..config.render_config import RenderConfig
from ..domain.card_options import CardOptions
from ..domain.structure_set import StructureSet
from ..notetype.factory import build_installer
from ..notetype.spec import DEFAULT_SPEC, NoteTypeSpec
from .runner import commit_with_undo, run_note_op

__all__ = ["NoteRequest", "add_randomized_occlusion_note"]

_UNDO_NAME = "Add Randomized Occlusion note"


@dataclass(frozen=True, slots=True)
class NoteRequest:
    """Everything needed to create one note, gathered from the editor."""

    image_path: str
    structures: StructureSet
    deck_name: str
    options: CardOptions = field(default_factory=CardOptions)
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
        # Everything that can fail on external state — importing the image (the
        # chosen file may have gone away) — happens BEFORE the custom undo entry
        # is opened, so a failure can't leave a half-open entry that corrupts
        # Anki's undo queue. Only the note write is wrapped by the entry.
        #
        # ensure_installed also runs first: add_dict/update_dict perform a schema
        # change that clears the undo queue, so it must precede the entry too. In
        # normal use it's a no-op (bootstrap installs the note type at profile
        # open).
        build_installer(col, spec).ensure_installed(render_config)
        filename = AnkiMediaGateway(col).add_image(request.image_path)
        content = NoteFactory(spec).build(
            image_filename=filename,
            structures=request.structures,
            options=request.options,
            header=request.header,
            back_extra=request.back_extra,
        )
        notetype = col.models.by_name(content.notetype_name)
        note = col.new_note(notetype)
        for name, value in content.fields.items():
            note[name] = value
        deck_id = col.decks.id(request.deck_name, create=True)

        return commit_with_undo(col, _UNDO_NAME, lambda: col.add_note(note, deck_id))

    run_note_op(parent=parent, op=op, on_success=on_success)
