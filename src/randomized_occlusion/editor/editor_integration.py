"""Add-window integration: an opt-in button that opens the occlusion creator.

When Anki's **Add** window is composing a note with the **Randomized Image
Occlusion** note type selected, this adds an **Occlusion** button to the editor
toolbar. Clicking it opens the same marking dialog the Tools menu opens
(:class:`~randomized_occlusion.editor.launcher.EditorLauncher`) — the marking
canvas, a deck picker, and the undo-safe create op — so an occlusion card can be
built straight from the Add window instead of hand-editing the raw base64 fields.

The button only opens the creator when the occlusion note type is the one
selected in the Add window; on any other note type it asks the user to switch
first, so the creator never appears out of context on an unrelated card.

Only Anki wiring lives here; the dialog and persistence belong to the launcher.
"""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks
from aqt.utils import showWarning

from ..notetype.spec import DEFAULT_SPEC, NoteTypeSpec
from .launcher import EditorLauncher

__all__ = ["EditorIntegration"]

_BUTTON_LABEL = "Occlusion"


class EditorIntegration:
    """Adds an opt-in button to Anki's Add window that opens the occlusion creator."""

    def __init__(
        self, launcher: EditorLauncher, spec: NoteTypeSpec = DEFAULT_SPEC
    ) -> None:
        self._launcher = launcher
        self._spec = spec

    def register(self) -> None:
        gui_hooks.editor_did_init_buttons.append(self._on_init_buttons)

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
        """True when the Add window's current note is the occlusion note type."""
        if note is None:
            return False
        try:
            notetype = note.note_type()
        except Exception:
            return False
        return bool(notetype) and notetype.get("name") == self._spec.name

    def _on_init_buttons(self, buttons: list[str], editor: Any) -> None:
        if not self._is_add_editor(editor):
            return
        button = editor.addButton(
            icon=None,
            cmd="ro_occlusion_markup",
            func=lambda ed: self._open(ed),
            tip="Create a Randomized Image Occlusion card from an image",
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
        # Only usable when the Add window has the occlusion note type selected;
        # on any other note type the creator would appear out of context, so ask
        # the user to switch first instead of opening it.
        if not self._is_our_note(getattr(editor, "note", None)):
            showWarning(
                'Select the "Randomized Image Occlusion" note type in the Add '
                "window first, then press Occlusion."
            )
            return
        self._launcher.open()
