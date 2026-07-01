"""Routing of ``pycmd`` messages from the editor webview.

Kept free of Qt and Anki so the protocol can be unit tested directly: construct
a bridge with stub callbacks and feed it message strings.
"""

from __future__ import annotations

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
    ) -> None:
        self._on_ready = on_ready
        self._on_count = on_count

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

        return None


def _parse_count(raw: str) -> int:
    try:
        return max(0, int(raw))
    except ValueError:
        return 0
