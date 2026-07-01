"""Composition root: wires hooks, the menu, and note-type installation.

This is the only module that reaches out to the live ``mw`` singleton and to
Anki's hook registry. Everything it touches is constructed here and injected
into the collaborators, so the rest of the package has no hidden global state.
"""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import QAction, qconnect

from .config.config_service import AnkiConfigProvider, ConfigService
from .editor.launcher import EditorLauncher
from .notetype.factory import build_installer

_MENU_LABEL = "Randomized Image Occlusion…"

# Strong references kept for the lifetime of the process. Without these the
# EditorLauncher (a local in setup()) would be garbage-collected after setup()
# returns; PyQt does not keep its own strong reference to a connected bound
# method's receiver, so the menu item would silently do nothing when clicked.
_launcher: EditorLauncher | None = None
_action: Any = None


def setup(addon_module: str) -> None:
    """Entry point invoked once from ``__init__`` when running inside Anki."""
    global _launcher, _action

    config_service = ConfigService(
        AnkiConfigProvider(mw.addonManager, addon_module)
    )
    _launcher = EditorLauncher(mw, config_service)

    _action = QAction(_MENU_LABEL, mw)
    qconnect(_action.triggered, _launcher.open)
    mw.form.menuTools.addAction(_action)

    # Install the note type on every profile open, and also right now if a
    # profile is already open — add-ons can load *after* the initial
    # profile_did_open has fired, in which case the hook alone would miss it.
    gui_hooks.profile_did_open.append(
        lambda: _install_notetype(config_service)
    )
    if mw.col is not None:
        _install_notetype(config_service)


def _install_notetype(config_service: ConfigService) -> None:
    col = mw.col
    if col is None:
        return
    try:
        build_installer(col).ensure_installed(config_service.render_config())
    except Exception as exc:  # pragma: no cover - defensive, never block startup
        print(f"[Randomized Image Occlusion] note-type install failed: {exc!r}")
