"""Shared wiring for running a note-mutating ``CollectionOp`` in the background.

The add and edit ops differ only in what their ``op(col)`` body does; how that op
is launched (off the UI thread, with an optional success callback) is identical,
so it lives here once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt.operations import CollectionOp

__all__ = ["commit_with_undo", "run_note_op"]


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


def commit_with_undo(col: Any, name: str, write: Callable[[], None]) -> Any:
    """Run ``write`` wrapped in a custom undo entry so the change collapses into
    one undo step, returning the ``OpChanges`` to hand back to ``CollectionOp``.

    The caller MUST have already done everything that can fail on external state
    (importing media, loading the note, a schema-changing install) BEFORE calling
    this: a failure between opening the entry and merging it would leave a
    half-open entry that corrupts Anki's undo queue.
    """
    undo_position = col.add_custom_undo_entry(name)
    write()
    return col.merge_undo_entries(undo_position)
