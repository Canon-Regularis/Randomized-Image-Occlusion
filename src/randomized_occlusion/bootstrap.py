"""Composition root: wires hooks, the menu, and note-type installation.

This is the only module that reaches out to the live ``mw`` singleton and to
Anki's hook registry. Everything it touches is constructed here and injected
into the collaborators, so the rest of the package has no hidden global state.
"""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import QAction, qconnect

from .collection.note_reader import NoteReader
from .config.config_service import AnkiConfigProvider, ConfigService
from .domain.card_options import CardMode
from .editor.browser_integration import BrowserEditIntegration
from .editor.editor_integration import EditorIntegration
from .editor.launcher import EditorLauncher
from .notetype.factory import build_installer
from .notetype.spec import DEFAULT_SPEC
from .review_shortcuts import install as install_review_shortcuts

_MENU_LABEL = "Randomized Image Occlusion…"

# Strong references kept for the lifetime of the process. Without these the
# integrations (locals in setup()) would be garbage-collected after setup()
# returns; PyQt does not keep its own strong reference to a connected bound
# method's receiver, so the menu item would silently do nothing when clicked.
_launcher: EditorLauncher | None = None
_browser_integration: BrowserEditIntegration | None = None
_editor_integration: EditorIntegration | None = None
_action: Any = None


def setup(addon_module: str) -> None:
    """Entry point invoked once from ``__init__`` when running inside Anki."""
    global _launcher, _browser_integration, _editor_integration, _action

    config_service = ConfigService(
        AnkiConfigProvider(mw.addonManager, addon_module)
    )
    _launcher = EditorLauncher(mw, config_service)

    _action = QAction(_MENU_LABEL, mw)
    qconnect(_action.triggered, _launcher.open)
    mw.form.menuTools.addAction(_action)

    # Add the "edit existing note" entry point to the Browser context menu.
    _browser_integration = BrowserEditIntegration(mw, config_service)
    _browser_integration.register()

    # Add an Occlusion button to Anki's Add window that opens the same creator as
    # the Tools menu (shares the launcher, so only one dialog opens at a time).
    _editor_integration = EditorIntegration(_launcher)
    _editor_integration.register()

    # Anki binds Space/Enter as main-window shortcuts, so a single-card cycle
    # never sees them: one press flipped to the answer key mid-cycle.
    install_review_shortcuts(gui_hooks, mw, DEFAULT_SPEC.name, _is_single_card)

    # The editor is modeless and is NOT registered with aqt.dialogs, which is
    # the registry Anki's own shutdown walks -- so nothing would otherwise take
    # it down when the collection goes away, and a Save pressed on a surviving
    # window resolves mw.col at op time and would write into whatever collection
    # had since been loaded.
    #
    # profile_will_close ONLY. It already covers the cases where the collection
    # really is going away: a profile switch, quitting, and restoring a backup.
    # collection_will_temporarily_close also fires for a colpkg export and a
    # full sync, where the collection comes straight back -- closing the editor
    # there would throw away an in-progress marking session for no reason.
    gui_hooks.profile_will_close.append(_close_editors)

    # Install the note type on every profile open, and also right now if a
    # profile is already open; add-ons can load *after* the initial
    # profile_did_open has fired, in which case the hook alone would miss it.
    gui_hooks.profile_did_open.append(
        lambda: _install_notetype(config_service)
    )
    if mw.col is not None:
        _install_notetype(config_service)


def _is_single_card(note: Any) -> bool:
    """Whether `note` is one of ours in single-card mode. Raises on anything odd."""
    # `note.items()` is Anki's Note API, not a dict's: it yields (field, value).
    fields = dict(note.items())
    return NoteReader(DEFAULT_SPEC).read(fields).options.mode is CardMode.SINGLE


def _close_editors(*_args: Any) -> None:
    """Take the editor down with the collection it was marking up against."""
    for integration in (_launcher, _browser_integration):
        if integration is not None:
            integration.close_open()


def _install_notetype(config_service: ConfigService) -> None:
    col = mw.col
    if col is None:
        return
    try:
        build_installer(col).ensure_installed(config_service.render_config())
    except Exception as exc:  # pragma: no cover - defensive, never block startup
        print(f"[Randomized Image Occlusion] note-type install failed: {exc!r}")
