"""Owns the lifetime of a modeless dialog.

PyQt keeps no strong reference to a connected slot's receiver, so a modeless
dialog with no other owner is garbage-collected the instant the opening method
returns — the window silently vanishes. The launcher, the Browser integration,
and the Add-window integration all previously reimplemented the same dance (hold
a strong reference, release it when the dialog finishes). This captures it once.
"""

from __future__ import annotations

from typing import Any

from aqt.qt import qconnect


class ModelessDialogHost:
    """Holds a strong reference to one modeless dialog, released when it closes."""

    def __init__(self) -> None:
        self._dialog: Any = None

    def is_showing(self) -> bool:
        """Whether a dialog is currently presented and not yet finished."""
        return self._dialog is not None

    def present(self, dialog: Any) -> None:
        """Show ``dialog`` and keep it alive until it is finished."""
        self._dialog = dialog
        qconnect(dialog.finished, self._release)
        dialog.show()

    def _release(self, *_args: Any) -> None:
        self._dialog = None
