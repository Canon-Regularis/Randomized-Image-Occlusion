"""Owns the lifetime of a modeless dialog.

PyQt keeps no strong reference to a connected slot's receiver, so a modeless
dialog with no other owner is garbage-collected the instant the opening method
returns; the window silently vanishes. The launcher, the Browser integration,
and the Add-window integration all previously reimplemented the same dance (hold
a strong reference, release it when the dialog finishes). This captures it once.
"""

from __future__ import annotations

import contextlib
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

    def raise_existing(self) -> bool:
        """Bring the open dialog to the front. False if none is open.

        The editor is modeless, so it can sit behind the main window. Without
        this, a second Tools-menu click did nothing whatsoever: present()
        returned False and both call sites discarded the answer, so the user
        saw no window, no message, and no reason why.
        """
        dialog = self._dialog
        if dialog is None:
            return False
        with contextlib.suppress(Exception):
            dialog.raise_()
            dialog.activateWindow()
        return True

    def present(self, build: Callable[[], Any]) -> bool:
        """Build and show a dialog unless one is already up; say whether it opened.

        ``build`` is a *factory* rather than a ready-made dialog, for two reasons:

        * the one-at-a-time guard then lives here, so no entry point can forget
          it; two dialogs open on the same note race each other's Save, and the
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

    def close_open(self, *_args: Any) -> None:
        """Close the open dialog, if any. Never raises.

        Anki's shutdown walks `aqt.dialogs`, which only knows the windows it
        registered, so this dialog was invisible to it: a profile switch closed
        the collection and left the editor on screen. `CollectionOp` resolves
        `mw.col` when the op RUNS, so a Save pressed afterwards wrote the note,
        the image and a freshly created deck into whichever profile had since
        been loaded -- and reported "Added N cards", so the user had no reason
        to doubt where it went.

        Closing is enough: `MarkerDialog.silentlyClose` lets `close()` run the
        normal reject path, which fires `finished` and so reaches `_release`
        and the dialog's own teardown.
        """
        dialog = self._dialog
        if dialog is None:
            return
        with contextlib.suppress(Exception):
            dialog.close()
        # Drop the reference even if close() refused, so a stale window can
        # never keep the next Tools-menu click from opening a fresh one.
        self._dialog = None

    def _release(self, *_args: Any) -> None:
        self._dialog = None
