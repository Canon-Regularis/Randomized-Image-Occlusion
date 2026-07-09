"""Owns the lifetime of a modeless dialog.

PyQt keeps no strong reference to a connected slot's receiver, so a modeless
dialog with no other owner is garbage-collected the instant the opening method
returns — the window silently vanishes. The launcher, the Browser integration,
and the Add-window integration all previously reimplemented the same dance (hold
a strong reference, release it when the dialog finishes). This captures it once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt.qt import qconnect


class ModelessDialogHost:
    """Holds a strong reference to one modeless dialog, released when it closes."""

    def __init__(self) -> None:
        self._dialog: Any = None

    def is_showing(self) -> bool:
        """Whether a dialog is currently presented and not yet finished."""
        return self._dialog is not None

    def present(self, build: Callable[[], Any]) -> bool:
        """Build and show a dialog unless one is already up; say whether it opened.

        ``build`` is a *factory* rather than a ready-made dialog, for two reasons:

        * the one-at-a-time guard then lives here, so no entry point can forget it
          — two dialogs open on the same note race each other's Save, and the
          later one silently overwrites the earlier (a lost update); and
        * a dialog is never constructed only to be thrown away. A ``QDialog``
          parented to the main window outlives the discarded Python reference, so
          building one we then refuse to show would leak it for the session.
        """
        if self.is_showing():
            return False
        dialog = build()
        self._dialog = dialog
        qconnect(dialog.finished, self._release)
        dialog.show()
        return True

    def _release(self, *_args: Any) -> None:
        self._dialog = None
