"""Remembering the zoom level the marking canvas was left at.

The canvas reports its level as the user changes it, and the dialog writes the
last one back on close. Doing that naively would materialise the key in the
user's config the first time they so much as open the editor, freezing it
against any later change to the default, so a level that was never actually
changed is deliberately not written at all.

Qt-free: it takes a :class:`~randomized_occlusion.config.config_service.ConfigService`
and nothing else, so the rule can be tested with an in-memory provider.
"""

from __future__ import annotations

import contextlib
from typing import Any

__all__ = ["ZoomMemory"]


class ZoomMemory:
    """The zoom level for one editor session."""

    def __init__(self, config: Any) -> None:
        self._config = config
        # Read once, not per use: a config write from elsewhere mid-session must
        # not change the level out from under an open dialog.
        self._opening = config.editor_zoom()
        self._level = self._opening

    @property
    def opening_level(self) -> float:
        """The level the canvas should open at."""
        return self._opening

    def record(self, zoom: float) -> None:
        """Note the level the canvas is now at. Nothing is written yet."""
        self._level = zoom

    def commit(self) -> None:
        """Persist the level, if the user actually changed it.

        Best-effort: this runs from the dialog's close handler, so a config store
        that refuses the write must not raise out of it and leave the dialog
        half-torn-down. Committing twice writes once.
        """
        if self._level == self._opening:
            return
        with contextlib.suppress(Exception):
            self._config.set_editor_zoom(self._level)
        self._opening = self._level  # commit is idempotent, success or not
