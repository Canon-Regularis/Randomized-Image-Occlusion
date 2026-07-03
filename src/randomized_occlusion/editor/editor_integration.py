"""Add-window integration: an opt-in button to mark up occlusion cards.

When Anki's **Add** window is composing a note, this adds an **Occlusion** button
to the editor toolbar. Clicking it (with the Randomized Image Occlusion note type
selected) opens the marking canvas instead of leaving the user to edit the raw
base64 fields by hand; on save the canvas stages the field values onto the
in-progress note (see :class:`EditorFieldSaver`) and Anki's own **Add** button
creates the card.

The canvas is *never* launched automatically — the Add window opens normally so
the user can pick whichever note type they want first.

Only Anki wiring lives here; reading a note back for re-editing is delegated to
:class:`NoteReader`, and persistence to the savers.
"""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks
from aqt.utils import showWarning

from ..collection.note_reader import LoadedNote, NoteReader, note_fields
from ..config.config_service import ConfigService
from ..notetype.spec import DEFAULT_SPEC, NoteTypeSpec
from .dialog import MarkerDialog
from .dialog_host import ModelessDialogHost
from .savers import EditorFieldSaver

__all__ = ["EditorIntegration"]

_BUTTON_LABEL = "Occlusion"


class EditorIntegration:
    """Adds the opt-in marking-canvas button to Anki's Add-window editor."""

    def __init__(
        self,
        main_window: Any,
        config_service: ConfigService,
        spec: NoteTypeSpec = DEFAULT_SPEC,
    ) -> None:
        self._mw = main_window
        self._config = config_service
        self._spec = spec
        self._host = ModelessDialogHost()

    def register(self) -> None:
        gui_hooks.editor_did_init_buttons.append(self._on_init_buttons)

    # -- predicates ------------------------------------------------------------

    def _is_add_editor(self, editor: Any) -> bool:
        """True for the editor embedded in Anki's Add window.

        Anki has changed how "add mode" is exposed over releases, so check every
        signal — missing all of them would silently hide the button.
        """
        mode = getattr(editor, "editorMode", None)
        if getattr(mode, "name", "") == "ADD_CARDS":
            return True
        if getattr(editor, "addMode", False):
            return True
        try:
            from aqt.addcards import AddCards

            if isinstance(getattr(editor, "parentWindow", None), AddCards):
                return True
        except Exception:
            pass
        return False

    def _is_our_note(self, note: Any) -> bool:
        if note is None:
            return False
        try:
            notetype = note.note_type()
        except Exception:
            return False
        return bool(notetype) and notetype.get("name") == self._spec.name

    # -- the toolbar button ----------------------------------------------------

    def _on_init_buttons(self, buttons: list[str], editor: Any) -> None:
        if not self._is_add_editor(editor):
            return
        button = editor.addButton(
            icon=None,
            cmd="ro_occlusion_markup",
            func=lambda ed: self._open(ed),
            tip="Mark up the occlusion image (Randomized Image Occlusion)",
            label=_BUTTON_LABEL,
            # Anki force-disables every add-on right-side button matching
            # `button.linkb:not(.perm)` whenever no editor field is focused
            # (setAddonButtonsDisabled, fired on field focusout). Switching note
            # type via the chooser blurs the field and leaves focus on a Qt
            # widget — not a field — so the button would stay stuck-disabled and
            # unclickable until the Add window is reopened. This action opens a
            # dialog and never touches the focused field, so mark it permanent
            # (adds the `perm` class) to opt out of that focus-gating entirely.
            disables=False,
        )
        buttons.append(button)

    def _open(self, editor: Any) -> None:
        if self._host.is_showing():
            return  # one canvas at a time
        if self._mw.col is None:
            return
        note = getattr(editor, "note", None)
        if not self._is_our_note(note):
            showWarning('Switch to the "Randomized Image Occlusion" note type first.')
            return
        prefill = self._read_prefill(note)
        saver = EditorFieldSaver(self._config, self._mw, editor, self._spec)
        dialog = MarkerDialog(self._mw, self._config, saver=saver, prefill=prefill)
        self._host.present(dialog)

    def _read_prefill(self, note: Any) -> LoadedNote | None:
        """Restore markers/options if the note already has occlusion data.

        A fresh note (nothing marked yet) opens a blank canvas; a partially
        marked one re-opens exactly as left.
        """
        try:
            fields = note_fields(note)
        except Exception:
            return None
        if not str(fields.get(self._spec.structures_field, "")).strip():
            return None
        try:
            return NoteReader(self._spec).read(fields)
        except Exception:
            return None
