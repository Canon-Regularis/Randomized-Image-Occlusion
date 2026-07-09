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
from ..config.render_config import RenderConfig
from ..domain.card_options import CardOptions
from ..domain.structure_set import StructureSet
from ..notetype.spec import DEFAULT_SPEC, NoteTypeSpec
from .runner import commit_with_undo, prepare_content, run_note_op

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
    on_failure: Callable[[Exception], None] | None = None,
) -> None:
    """Run the note-creation ``CollectionOp`` in the background."""

    def op(col: Any) -> Any:
        # prepare_content installs the note type and imports the chosen image —
        # the fallible work that must precede the undo entry (see its docstring).
        content = prepare_content(
            col,
            spec=spec,
            render_config=render_config,
            resolve_image=lambda c: AnkiMediaGateway(c).add_image(request.image_path),
            structures=request.structures,
            options=request.options,
            header=request.header,
            back_extra=request.back_extra,
        )
        # Resolving the note type and the deck can fail too, so they also stay
        # outside the entry; only the note write is wrapped by it.
        notetype = col.models.by_name(content.notetype_name)
        note = col.new_note(notetype)
        for name, value in content.fields.items():
            note[name] = value
        deck_id = col.decks.id(request.deck_name, create=True)

        return commit_with_undo(col, _UNDO_NAME, lambda: col.add_note(note, deck_id))

    run_note_op(parent=parent, op=op, on_success=on_success, on_failure=on_failure)
