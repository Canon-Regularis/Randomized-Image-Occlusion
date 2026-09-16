"""Opens the editor dialog, keeping a reference so Qt does not garbage-collect it."""

from __future__ import annotations

import traceback
from typing import Any

from aqt.utils import showInfo, showWarning

from ..config.config_service import ConfigService
from .dialog import MarkerDialog
from .dialog_host import ModelessDialogHost
from .savers import CreateNoteSaver


class EditorLauncher:
    def __init__(self, main_window: Any, config_service: ConfigService) -> None:
        self._mw = main_window
        self._config = config_service
        self._host = ModelessDialogHost()

    def close_open(self, *_args: Any) -> None:
        """Close the editor if one is open (profile switch, shutdown)."""
        self._host.close_open()

    def open(self, *_args: Any) -> None:
        # *_args absorbs the bool QAction.triggered emits, so this works whether
        # or not PyQt truncates the signal's argument.
        if self._mw.col is None:
            showInfo("Please open a collection first.")
            return
        try:
            # The host builds the dialog only when none is open, so the Tools menu
            # and the Add-window button, which share this launcher, can never
            # stack two editors. The editor is modeless, though, so the one
            # already open may be behind the main window: raise it rather than
            # letting the click do nothing at all.
            opened = self._host.present(
                lambda: MarkerDialog(
                    self._mw, self._config, saver=CreateNoteSaver(self._config)
                )
            )
            if not opened:
                self._host.raise_existing()
        except Exception:
            # Surface the failure instead of silently doing nothing.
            showWarning(
                "Randomized Image Occlusion could not open the editor:\n\n"
                + traceback.format_exc()
            )
