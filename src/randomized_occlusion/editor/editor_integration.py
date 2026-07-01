"""Add-window integration: mark up occlusion cards on the canvas, not raw fields.

When Anki's **Add** window is composing a Randomized Image Occlusion note, this
opens the marking canvas — automatically when the note type is selected, and on
demand via an editor toolbar button — instead of leaving the user to face the
raw (base64) occlusion fields. On save the canvas stages the field values onto
the in-progress note (see :class:`EditorFieldSaver`) and Anki's own **Add**
button creates the card.

Only Anki wiring lives here; reading a note back for re-editing is delegated to
:class:`NoteReader`, and persistence to the savers.
"""

from __future__ import annotations

import contextlib
import weakref
from typing import Any

from aqt import gui_hooks
from aqt.qt import QTimer, qconnect
from aqt.utils import showWarning

from ..collection.note_reader import LoadedNote, NoteReader
from ..config.config_service import ConfigService
from ..notetype.spec import DEFAULT_SPEC, NoteTypeSpec
from .dialog import MarkerDialog
from .savers import EditorFieldSaver

__all__ = ["EditorIntegration"]

_BUTTON_LABEL = "Occlusion"


class EditorIntegration:
    """Wires Anki's Add-window editor to the marking canvas."""

    def __init__(
        self,
        main_window: Any,
        config_service: ConfigService,
        spec: NoteTypeSpec = DEFAULT_SPEC,
    ) -> None:
        self._mw = main_window
        self._config = config_service
        self._spec = spec
        # Strong ref so the modeless canvas isn't garbage-collected while open.
        self._dialog: MarkerDialog | None = None
        # Notes we've already shown the canvas for (auto or manual), so re-renders
        # — and pending timers after the user dismisses the canvas — don't reopen
        # it. Keyed per note object, so several Add windows track independently;
        # entries drop automatically once Anki discards the note (and explicitly
        # on add, so a reused note object auto-opens again for the next card).
        self._handled_notes: weakref.WeakSet[Any] = weakref.WeakSet()

    def register(self) -> None:
        gui_hooks.editor_did_init_buttons.append(self._on_init_buttons)
        gui_hooks.editor_did_load_note.append(self._on_load_note)
        gui_hooks.add_cards_did_add_note.append(self._on_note_added)
        # Backup trigger: catch the Add window's very first note in case
        # editor_did_load_note timing differs across Anki versions.
        gui_hooks.add_cards_did_init.append(self._on_add_cards_init)

    # -- predicates ------------------------------------------------------------

    def _is_add_editor(self, editor: Any) -> bool:
        """True for the editor embedded in Anki's Add window.

        Anki has changed how "add mode" is exposed over releases, so check every
        signal — missing all of them would silently disable the whole feature.
        """
        # Newer Anki: an EditorMode enum on the editor.
        mode = getattr(editor, "editorMode", None)
        if getattr(mode, "name", "") == "ADD_CARDS":
            return True
        # Older Anki: a plain addMode flag.
        if getattr(editor, "addMode", False):
            return True
        # Structural fallback: the editor's window is the Add dialog.
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

    def _image_is_empty(self, note: Any) -> bool:
        try:
            return not str(note[self._spec.image_field]).strip()
        except Exception:
            return True

    # -- hooks -----------------------------------------------------------------

    def _on_init_buttons(self, buttons: list[str], editor: Any) -> None:
        if not self._is_add_editor(editor):
            return
        button = editor.addButton(
            icon=None,
            cmd="ro_occlusion_markup",
            func=lambda ed: self._open(ed),
            tip="Mark up the occlusion image (Randomized Image Occlusion)",
            label=_BUTTON_LABEL,
        )
        buttons.append(button)

    def _on_load_note(self, editor: Any) -> None:
        if not self._is_add_editor(editor):
            return
        note = getattr(editor, "note", None)
        if not self._is_our_note(note) or not self._image_is_empty(note):
            return
        if self._is_handled(note):
            return  # already shown for this note; don't reopen on re-render/cancel
        self._mark_handled(note)
        # Defer so we don't open a modal dialog while the editor is still loading.
        QTimer.singleShot(60, lambda: self._auto_open(editor, note))

    def _on_note_added(self, note: Any) -> None:
        # The Add window reuses (and clears) this note object for the next card;
        # forget it so that fresh, empty note auto-opens the canvas again.
        self._forget_handled(note)

    def _on_add_cards_init(self, addcards: Any) -> None:
        editor = getattr(addcards, "editor", None)
        if editor is not None:
            # Route through the normal path; it no-ops until the note is ready.
            self._on_load_note(editor)

    # -- "already handled this note" bookkeeping -------------------------------

    def _is_handled(self, note: Any) -> bool:
        try:
            return note in self._handled_notes
        except TypeError:  # note not weak-referenceable
            return False

    def _mark_handled(self, note: Any) -> None:
        with contextlib.suppress(TypeError):  # note not weak-referenceable
            self._handled_notes.add(note)

    def _forget_handled(self, note: Any) -> None:
        with contextlib.suppress(TypeError):
            self._handled_notes.discard(note)

    # -- opening the canvas ----------------------------------------------------

    def _auto_open(self, editor: Any, note: Any) -> None:
        # Re-validate: the note may have changed or been marked up during the delay.
        if self._dialog is not None:
            return
        if getattr(editor, "note", None) is not note:
            return
        if not self._is_our_note(note) or not self._image_is_empty(note):
            return
        self._open(editor)

    def _open(self, editor: Any) -> None:
        if self._dialog is not None:
            return  # one canvas at a time
        if self._mw.col is None:
            return
        note = getattr(editor, "note", None)
        if not self._is_our_note(note):
            showWarning('Switch to the "Randomized Image Occlusion" note type first.')
            return
        # Showing the canvas (auto or manual) counts as handling this note, so a
        # pending auto-open timer won't reopen it after the user closes it.
        self._mark_handled(note)
        prefill = self._read_prefill(note)
        saver = EditorFieldSaver(self._config, self._mw, editor, self._spec)
        dialog = MarkerDialog(self._mw, self._config, saver=saver, prefill=prefill)
        self._dialog = dialog
        qconnect(dialog.finished, self._on_dialog_finished)
        dialog.show()

    def _read_prefill(self, note: Any) -> LoadedNote | None:
        """Restore markers/options if the note already has occlusion data.

        A fresh note (nothing marked yet) opens a blank canvas; a partially
        marked one re-opens exactly as left.
        """
        try:
            field_names = [field["name"] for field in note.note_type()["flds"]]
            fields = {name: note[name] for name in field_names}
        except Exception:
            return None
        if not str(fields.get(self._spec.structures_field, "")).strip():
            return None
        try:
            return NoteReader(self._spec).read(fields)
        except Exception:
            return None

    def _on_dialog_finished(self, _result: int) -> None:
        self._dialog = None
