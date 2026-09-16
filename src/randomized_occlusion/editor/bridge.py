"""Routing of ``pycmd`` messages from the editor webview.

Kept free of Qt and Anki so the protocol can be unit tested directly: construct
a bridge with stub callbacks and feed it message strings.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

__all__ = ["MarkerBridge"]

_PREFIX = "ro:"


class MarkerBridge:
    """Translates editor ``pycmd`` strings into callback invocations."""

    def __init__(
        self,
        *,
        on_ready: Callable[[], None],
        on_count: Callable[[int], None],
        on_zoom: Callable[[float], None],
        on_text_focus: Callable[[bool], None],
        on_broken: Callable[[bool], None],
    ) -> None:
        self._on_ready = on_ready
        self._on_count = on_count
        self._on_zoom = on_zoom
        self._on_text_focus = on_text_focus
        self._on_broken = on_broken

    def handle(self, message: str) -> Any:
        """Dispatch one message. Returns ``None`` (no value flows back to JS).

        Messages we do not recognise are ignored, so the bridge can coexist with
        Anki's own webview messages.
        """
        if not isinstance(message, str) or not message.startswith(_PREFIX):
            return None
        body = message[len(_PREFIX):]

        if body == "ready":
            self._on_ready()
            return None

        if body.startswith("count:"):
            self._on_count(_parse_count(body[len("count:"):]))
            return None

        if body.startswith("zoom:"):
            self._on_zoom(_parse_zoom(body[len("zoom:"):]))
            return None

        if body.startswith("textfocus:"):
            self._on_text_focus(body[len("textfocus:"):] == "1")
            return None

        if body.startswith("broken:"):
            self._on_broken(body[len("broken:"):] == "1")
            return None

        return None


def _parse_count(raw: str) -> int:
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _parse_zoom(raw: str) -> float:
    """The zoom level, as a multiple of the fitted size.

    Total, like :func:`_parse_count`: the canvas is the only sender, but a
    malformed message must never raise out of Anki's webview callback. NaN and
    the infinities are rejected too, since they would poison the stored config.
    """
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    if not math.isfinite(value):
        return 1.0
    return value
