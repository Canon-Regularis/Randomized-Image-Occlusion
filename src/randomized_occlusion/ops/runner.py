"""Shared wiring for running a note-mutating ``CollectionOp`` in the background.

The add and edit ops differ only in what their ``op(col)`` body does; how that op
is launched (off the UI thread, with an optional success callback) is identical,
so it lives here once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt.operations import CollectionOp


def run_note_op(
    *,
    parent: Any,
    op: Callable[[Any], Any],
    on_success: Callable[[Any], None] | None,
) -> None:
    operation = CollectionOp(parent=parent, op=op)
    if on_success is not None:
        operation = operation.success(on_success)
    operation.run_in_background()
