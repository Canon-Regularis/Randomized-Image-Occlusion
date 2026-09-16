"""Composition root: wires hooks, the menu, and note-type installation.

This is the only module that reaches out to the live ``mw`` singleton and to
Anki's hook registry. Everything it touches is constructed here and injected
into the collaborators, so the rest of the package has no hidden global state.
"""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import QAction, Qt, qconnect

from .collection.note_reader import NoteReader
from .config.config_service import AnkiConfigProvider, ConfigService
from .domain.card_options import CardMode
from .editor.browser_integration import BrowserEditIntegration
from .editor.editor_integration import EditorIntegration
from .editor.launcher import EditorLauncher
from .notetype.factory import build_installer
from .notetype.installer import InstallResult
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
#: setup() adds menu entries and appends hooks, none of which it can take back,
#: so it must run at most once per process however often __init__ is reached.
_installed = False


def setup(addon_module: str) -> None:
    """Entry point invoked once from ``__init__`` when running inside Anki.

    Guarded rather than merely documented as once-only: nothing below undoes
    itself, so a second call would add a second Tools entry, a second Browser
    action, and a second copy of every hook -- including the reviewer key
    override, which would then run its handler twice per press and advance a
    single-card cycle two steps at a time.
    """
    global _launcher, _browser_integration, _editor_integration, _action
    global _installed
    if _installed:
        return
    _installed = True

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
    #
    # The keys are spelled exactly as Anki spells them in Reviewer._shortcutKeys:
    # " " as a string, Return and Enter as Qt.Key members. Anki dedupes bindings
    # through {QKeySequence(key): fn}, so a mismatched spelling would leave BOTH
    # bindings alive and Qt would report an ambiguous shortcut -- taking Return
    # and Enter out of the reviewer for every card, not only ours.
    install_review_shortcuts(
        gui_hooks,
        mw,
        DEFAULT_SPEC.name,
        _is_single_card,
        keys=(" ", Qt.Key.Key_Return, Qt.Key.Key_Enter),
    )

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
    """Whether `note` is in single-card mode. Raises if its payload is unreadable.

    Deliberately does NOT check the note type: `should_intercept` has already
    done that before calling this, which is what keeps the payload decode off
    the path of every key press on every other note type.
    """
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
        result = build_installer(col).ensure_installed(config_service.render_config())
    except Exception as exc:  # pragma: no cover - defensive, never block startup
        print(f"[Randomized Image Occlusion] note-type install failed: {exc!r}")
        return
    if result is InstallResult.CUSTOMISED:
        # The card template or its CSS has been edited by hand, so this update
        # left it alone rather than overwriting the work silently. Said out loud
        # because the cost of not saying it is a user whose cards quietly keep
        # an older renderer, missing whatever this release fixed.
        print(
            "[Randomized Image Occlusion] the note type's template or CSS has "
            "been edited by hand, so it was not updated. Cards will keep the "
            "older renderer until the customisation is removed (Tools > Manage "
            "Note Types > Cards)."
        )
    elif result is InstallResult.FIELDS_MISSING:
        # Nothing was written, and nothing the add-on does will work until this
        # is put right, so the one place it can be said at profile open says it.
        print(
            "[Randomized Image Occlusion] the note type is missing one of the "
            f"fields it was created with ({', '.join(DEFAULT_SPEC.required_fields)}), "
            "so it was left untouched. Restore the original field name in Tools > "
            "Manage Note Types > Fields; adding an empty field back would blank it "
            "on every card."
        )
