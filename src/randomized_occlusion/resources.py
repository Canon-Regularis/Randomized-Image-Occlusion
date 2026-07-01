"""Filesystem access to bundled web assets.

Add-ons installed from AnkiWeb live in a folder named by a numeric id, so the
package name is not stable. We therefore locate bundled files relative to this
module's own location rather than via a hard-coded package name.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

__all__ = ["read_web"]

_WEB_DIR = Path(__file__).resolve().parent / "web"


@cache
def read_web(relative_path: str) -> str:
    """Read a UTF-8 text asset under ``web/`` (e.g. ``"review/render.js"``)."""
    path = _WEB_DIR / relative_path
    return path.read_text(encoding="utf-8")
