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

    def open(self, *_args: Any) -> None:
        # *_args absorbs the bool QAction.triggered emits, so this works whether
        # or not PyQt truncates the signal's argument.
        if self._mw.col is None:
            showInfo("Please open a collection first.")
            return
        try:
            dialog = MarkerDialog(
                self._mw, self._config, saver=CreateNoteSaver(self._config)
            )
        except Exception:
            # Surface the failure instead of silently doing nothing.
            showWarning(
                "Randomized Image Occlusion could not open the editor:\n\n"
                + traceback.format_exc()
            )
            return
        self._host.present(dialog)
