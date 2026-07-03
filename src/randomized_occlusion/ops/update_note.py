"""The undo-safe entry point that edits an existing Randomized Occlusion note.

The mirror of :mod:`create_note`: it rebuilds the note's fields from the edited
:class:`StructureSet`/:class:`CardOptions` (reusing the same
:class:`~randomized_occlusion.collection.note_factory.NoteFactory`) and writes
them back inside one ``CollectionOp`` so the edit runs off the UI thread and is a
single undo step. Changing the number of markers, the direction, or the mode
changes the cloze ordinals, so ``update_note`` regenerates the note's cards to
match — exactly as editing any cloze note does.
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

__all__ = ["UpdateRequest", "update_randomized_occlusion_note"]

_UNDO_NAME = "Edit Randomized Occlusion note"


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    """Everything needed to rewrite one existing note, gathered from the editor.

    ``existing_image_filename`` is the media basename the note already points at;
    it is reused verbatim unless ``new_image_path`` is set (the user loaded a
    different image), in which case that file is imported and replaces it.
    """

    note_id: int
    structures: StructureSet
    existing_image_filename: str
    options: CardOptions = field(default_factory=CardOptions)
    new_image_path: str | None = None
    header: str = ""
    back_extra: str = ""


def update_randomized_occlusion_note(
    *,
    parent: Any,
    request: UpdateRequest,
    render_config: RenderConfig,
    spec: NoteTypeSpec = DEFAULT_SPEC,
    on_success: Callable[[Any], None] | None = None,
) -> None:
    """Run the note-editing ``CollectionOp`` in the background."""

    def op(col: Any) -> Any:
        # Everything that can fail on external state — importing the image (the
        # file may have gone away) and loading the note (it may have been deleted
        # or synced away) — happens BEFORE the custom undo entry is opened. That
        # way such a failure can't leave a half-open undo entry that corrupts
        # Anki's undo queue; only the actual write is wrapped by the entry.
        #
        # ensure_installed also runs first: add_dict/update_dict perform a schema
        # change that clears the undo queue, so it must precede the entry too.
        build_installer(col, spec).ensure_installed(render_config)
        filename = (
            AnkiMediaGateway(col).add_image(request.new_image_path)
            if request.new_image_path
            else request.existing_image_filename
        )
        content = NoteFactory(spec).build(
            image_filename=filename,
            structures=request.structures,
            deck_name="",  # unused when editing: cards keep their current decks
            options=request.options,
            header=request.header,
            back_extra=request.back_extra,
        )
        note = col.get_note(request.note_id)
        for name, value in content.fields.items():
            note[name] = value

        # col.update_note persists the fields and regenerates cards for any cloze
        # ordinals the edit added or removed.
        return commit_with_undo(col, _UNDO_NAME, lambda: col.update_note(note))

    run_note_op(parent=parent, op=op, on_success=on_success)
