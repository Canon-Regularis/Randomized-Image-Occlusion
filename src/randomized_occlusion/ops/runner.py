"""Shared wiring for the note-mutating ``CollectionOp``s.

The add and edit ops differ only in how they resolve the image and how they write
the note. Everything around that — launching the op off the UI thread, the
fallible prelude that must precede any undo entry, and opening/merging that entry
— is identical, so it lives here once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt.operations import CollectionOp

from ..collection.note_factory import NoteContent, NoteFactory
from ..config.render_config import RenderConfig
from ..domain.card_options import CardOptions
from ..domain.structure_set import StructureSet
from ..notetype.factory import build_installer
from ..notetype.spec import NoteTypeSpec

__all__ = ["commit_with_undo", "prepare_content", "run_note_op"]


def run_note_op(
    *,
    parent: Any,
    op: Callable[[Any], Any],
    on_success: Callable[[Any], None] | None,
    on_failure: Callable[[Exception], None] | None = None,
) -> None:
    operation = CollectionOp(parent=parent, op=op)
    if on_success is not None:
        operation = operation.success(on_success)
    if on_failure is not None:
        operation = operation.failure(on_failure)
    operation.run_in_background()


def prepare_content(
    col: Any,
    *,
    spec: NoteTypeSpec,
    render_config: RenderConfig,
    resolve_image: Callable[[Any], str],
    structures: StructureSet,
    options: CardOptions,
    header: str,
    back_extra: str,
) -> NoteContent:
    """Build a note's field values — the fallible prelude both note ops share.

    Two steps here can fail on external state, and both MUST happen before
    :func:`commit_with_undo` opens a custom undo entry, or the failure would
    strand a half-open entry and corrupt Anki's undo queue:

    * ``ensure_installed`` may add or update the note type, a schema change that
      clears the undo queue outright (normally a no-op — bootstrap installs the
      note type at profile open); and
    * ``resolve_image`` may import a file the user has since moved or deleted.

    Callers keep their *own* fallible work (looking up the deck, loading the note)
    before ``commit_with_undo`` for the same reason; only the write is wrapped.
    """
    build_installer(col, spec).ensure_installed(render_config)
    return NoteFactory(spec).build(
        image_filename=resolve_image(col),
        structures=structures,
        options=options,
        header=header,
        back_extra=back_extra,
    )


def commit_with_undo(col: Any, name: str, write: Callable[[], None]) -> Any:
    """Run ``write`` wrapped in a custom undo entry so the change collapses into
    one undo step, returning the ``OpChanges`` to hand back to ``CollectionOp``.

    The caller MUST have already done everything that can fail on external state
    (importing media, loading the note, a schema-changing install) BEFORE calling
    this: a failure between opening the entry and merging it would leave a
    half-open entry that corrupts Anki's undo queue. See :func:`prepare_content`.
    """
    undo_position = col.add_custom_undo_entry(name)
    write()
    return col.merge_undo_entries(undo_position)
