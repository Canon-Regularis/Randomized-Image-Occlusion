"""Browser integration: an "edit" entry point for existing notes.

Adds a context-menu action in the card/note Browser that re-opens a Randomized
Occlusion note in the marking dialog. The action only appears when exactly one
note of our note type is selected, so it never clutters the menu for unrelated
notes. Reading the note back into domain objects is delegated to
:class:`~randomized_occlusion.collection.note_reader.NoteReader`; this module only
handles Anki wiring.
"""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks
from aqt.qt import qconnect
from aqt.utils import showWarning

from ..collection.note_reader import NoteReader
from ..config.config_service import ConfigService
from ..notetype.spec import DEFAULT_SPEC, NoteTypeSpec
from .dialog import EditContext, MarkerDialog

__all__ = ["BrowserEditIntegration"]

_MENU_LABEL = "Edit with Randomized Image Occlusion"


class BrowserEditIntegration:
    """Wires the Browser context menu to the edit flow."""

    def __init__(
        self,
        main_window: Any,
        config_service: ConfigService,
        spec: NoteTypeSpec = DEFAULT_SPEC,
    ) -> None:
        self._mw = main_window
        self._config = config_service
        self._spec = spec
        # Strong ref so the modeless dialog is not garbage-collected while open.
        self._dialog: MarkerDialog | None = None

    def register(self) -> None:
        gui_hooks.browser_will_show_context_menu.append(self._on_context_menu)

    def _on_context_menu(self, browser: Any, menu: Any) -> None:
        note_id = self._sole_selected_note_of_our_type(browser)
        if note_id is None:
            return
        action = menu.addAction(_MENU_LABEL)
        qconnect(action.triggered, lambda: self._open(note_id))

    def _sole_selected_note_of_our_type(self, browser: Any) -> int | None:
        """The selected note id iff exactly one is selected and it is ours.

        Defensive throughout: a Browser in an odd state (or an API shift across
        Anki versions) should silently show no action rather than raise into
        Anki's menu-building code.
        """
        try:
            note_ids = browser.selected_notes()
        except Exception:
            return None
        if len(note_ids) != 1:
            return None
        try:
            note = browser.col.get_note(note_ids[0])
            notetype = note.note_type()
        except Exception:
            return None
        if not notetype or notetype.get("name") != self._spec.name:
            return None
        return note_ids[0]

    def _open(self, note_id: int) -> None:
        col = self._mw.col
        if col is None:
            return
        try:
            note = col.get_note(note_id)
            field_names = [field["name"] for field in note.note_type()["flds"]]
            fields = {name: note[name] for name in field_names}
            loaded = NoteReader(self._spec).read(fields)
        except Exception as exc:
            showWarning(
                "This note could not be opened for editing:\n\n"
                f"{exc}\n\nIt may have been created by a different tool or "
                "hand-edited."
            )
            return
        dialog = MarkerDialog(
            self._mw,
            self._config,
            edit=EditContext(note_id=int(note_id), loaded=loaded),
        )
        self._dialog = dialog
        dialog.show()
