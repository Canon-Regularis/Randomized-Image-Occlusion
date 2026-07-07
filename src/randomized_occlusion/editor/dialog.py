"""The image-marking editor dialog.

Hosts the marking canvas in an :class:`AnkiWebView`, collects native inputs
(header, extra, deck, card options), and hands a validated :class:`MarkupResult`
to a :class:`NoteSaver`. The dialog knows nothing about *how* the note is stored:

* creating a new note (Tools menu / Add-window button) and editing an existing
  one (Browser) are just different savers;
* an optional ``prefill`` (a :class:`LoadedNote`) restores an existing note's
  image, markers, and options onto the canvas.

The dialog stays a thin shell: validation lives in the domain layer, routing in
:class:`MarkerBridge`, persistence in the saver.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from typing import Any

from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    qconnect,
)
from aqt.utils import showWarning, tooltip
from aqt.webview import AnkiWebView

from ..collection.note_reader import LoadedNote
from ..config.config_service import ConfigService
from ..domain.card_options import CardMode, CardOptions, Direction, Interaction
from ..domain.geometry import NormalizedPoint
from ..domain.structure import Structure
from ..domain.structure_set import StructureSet
from ..resources import read_web
from .bridge import MarkerBridge
from .savers import MarkupResult, NoteSaver

__all__ = ["MarkerDialog"]

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.svg)"

# (enum member, display label) pairs backing the option combo boxes.
_DIRECTION_CHOICES: tuple[tuple[Direction, str], ...] = (
    (Direction.FORWARD, "Forward — name the structure"),
    (Direction.REVERSE, "Reverse — locate the structure"),
    (Direction.BOTH, "Both"),
)
_CARD_MODE_CHOICES: tuple[tuple[CardMode, str], ...] = (
    (CardMode.MULTI, "Multi — one card per label"),
    (CardMode.SINGLE, "Single — cycle all on one card"),
)


class MarkerDialog(QDialog):
    def __init__(
        self,
        main_window: Any,
        config_service: ConfigService,
        *,
        saver: NoteSaver,
        prefill: LoadedNote | None = None,
    ) -> None:
        super().__init__(main_window)
        self._mw = main_window
        self._config = config_service
        self._saver = saver
        self._prefill = prefill
        # A newly chosen file to import (set when the user picks/replaces an
        # image). When a prefilled note's image is unchanged, `_existing_filename`
        # is reused instead.
        self._new_image_path: str | None = None
        self._existing_filename: str | None = (
            prefill.image_filename if prefill is not None else None
        )
        self._deck_combo: QComboBox | None = None
        self._web_ready = False
        # Held from the moment a Save is committed until the async persist op
        # resolves, so a second Save press can't queue a duplicate note.
        self._saving = False
        self._marker_count = len(prefill.structures) if prefill is not None else 0
        # An image to show once the webview signals it is ready. (data_url, markers).
        self._pending_display: tuple[str, list[dict[str, Any]] | None] | None = None
        self._bridge = MarkerBridge(
            on_ready=self._on_web_ready, on_count=self._on_count
        )

        self.setWindowTitle(saver.title())
        self.setMinimumSize(720, 520)
        self.resize(960, 680)
        self._build_ui()
        self._load_page()
        if prefill is not None:
            self._queue_existing_image(prefill)
        qconnect(self.finished, self._on_finished)

    # -- construction ----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._load_button = QPushButton(self._saver.load_button_label())
        self._load_button.setToolTip("Choose the image to mark up")
        qconnect(self._load_button.clicked, self._choose_image)
        toolbar.addWidget(self._load_button)
        toolbar.addStretch(1)
        self._status = QLabel("Load an image to begin.")
        self._status.setStyleSheet("color: palette(mid);")  # dim, theme-aware
        toolbar.addWidget(self._status)
        layout.addLayout(toolbar)

        self.web = AnkiWebView(parent=self, title="randomized-occlusion-editor")
        self.web.set_bridge_command(self._bridge.handle, self)
        layout.addWidget(self.web, stretch=1)

        layout.addLayout(self._build_content_form())
        layout.addWidget(self._build_options_group())

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        qconnect(self._buttons.accepted, self._save)
        qconnect(self._buttons.rejected, self.reject)
        layout.addWidget(self._buttons)
        self._update_status()
        self._update_save_enabled()
        self._set_tab_order()
        self._load_button.setFocus()

    def _build_content_form(self) -> QFormLayout:
        form = QFormLayout()
        self._header_edit = QLineEdit()
        self._header_edit.setPlaceholderText("Optional title shown above the image")
        self._header_edit.setToolTip("Shown above the image on both sides of the card")
        form.addRow("Header:", self._header_edit)

        self._extra_edit = QPlainTextEdit()
        self._extra_edit.setPlaceholderText("Optional extra info shown on the answer side")
        self._extra_edit.setToolTip("Revealed on the answer side, below the image")
        self._extra_edit.setMinimumHeight(48)
        self._extra_edit.setMaximumHeight(90)
        form.addRow("Back extra:", self._extra_edit)

        # The deck picker only matters when this dialog adds the note itself
        # (CreateNoteSaver — the Tools menu and the Add-window button); the Browser
        # edit flow reuses the note's existing deck.
        if self._saver.wants_deck:
            self._deck_combo = QComboBox()
            self._deck_combo.setToolTip("Deck the new card(s) are added to")
            self._populate_decks()
            form.addRow("Deck:", self._deck_combo)

        if self._prefill is not None:
            self._header_edit.setText(self._prefill.header)
            self._extra_edit.setPlainText(self._prefill.back_extra)
        return form

    def _build_options_group(self) -> QGroupBox:
        defaults = (
            self._prefill.options
            if self._prefill is not None
            else self._config.editor_defaults()
        )
        group = QGroupBox("Card options")
        form = QFormLayout(group)

        self._mode_combo = QComboBox()
        for mode, label in _CARD_MODE_CHOICES:
            self._mode_combo.addItem(label, mode)
        self._mode_combo.setCurrentIndex(max(0, self._mode_combo.findData(defaults.mode)))
        self._mode_combo.setToolTip(
            "Multi: one card per label. Single: one card that cycles through every "
            "label in a fresh random order each review, with a running counter."
        )
        form.addRow("Mode:", self._mode_combo)

        self._direction_combo = QComboBox()
        for direction, label in _DIRECTION_CHOICES:
            self._direction_combo.addItem(label, direction)
        self._direction_combo.setCurrentIndex(
            max(0, self._direction_combo.findData(defaults.direction))
        )
        self._direction_combo.setToolTip(
            "Forward: name the arrowed structure. Reverse: given the name, locate it. "
            "Both: a random mix, re-rolled each review (per marker in single-card mode)."
        )
        form.addRow("Direction:", self._direction_combo)

        self._type_check = QCheckBox("Type the answer (Anki grades it)")
        # The user's own multi-mode choice, remembered so a detour through single
        # mode (which force-locks the box) can restore it on the way back rather
        # than leaving single mode's forced value behind (which would silently
        # flip the saved interaction).
        self._manual_type_choice = defaults.interaction == Interaction.TYPE
        self._type_check.setChecked(self._manual_type_choice)
        self._type_check.setToolTip(
            "Type the label and let Anki grade it, instead of flipping to reveal it."
        )
        # `clicked` fires only on genuine user interaction (not programmatic
        # setChecked), and the box is disabled in single mode, so this records
        # exactly the user's manual multi-mode intent.
        qconnect(self._type_check.clicked, self._on_type_clicked)
        form.addRow("", self._type_check)

        self._context_check = QCheckBox("Show other labels as context")
        self._context_check.setChecked(defaults.context_labels)
        self._context_check.setToolTip("Reveal the other structures' labels around the tested one")
        form.addRow("", self._context_check)

        # Single mode's typing is fixed by direction, so refresh the "Type the
        # answer" box whenever the mode or direction changes: it stays visible but
        # disabled — locked ON for single forward/both, locked OFF for single +
        # reverse (all "locate it", nothing to type). Multi mode leaves it free.
        qconnect(self._mode_combo.currentIndexChanged, self._sync_type_option)
        qconnect(self._direction_combo.currentIndexChanged, self._sync_type_option)
        self._sync_type_option()
        return group

    def _on_type_clicked(self, checked: bool) -> None:
        """Remember the user's manual (multi-mode) 'Type the answer' choice."""
        self._manual_type_choice = checked

    def _sync_type_option(self) -> None:
        """Single mode's typing is fixed by the direction, so the box stays visible
        but non-selectable: forward/both always type their 'name it' markers
        (locked ON), reverse is all 'locate it' so typing is unavailable (locked
        OFF). Multi mode restores the user's own choice and leaves the box free to
        toggle — so a detour into single mode never rewrites their multi-mode
        interaction."""
        single = self._mode_combo.currentData() is CardMode.SINGLE
        reverse = self._direction_combo.currentData() is Direction.REVERSE
        if single:
            self._type_check.setChecked(not reverse)  # forward/both on, reverse off
            self._type_check.setEnabled(False)
        else:
            self._type_check.setChecked(self._manual_type_choice)
            self._type_check.setEnabled(True)

    def _set_tab_order(self) -> None:
        self.setTabOrder(self._load_button, self._header_edit)
        self.setTabOrder(self._header_edit, self._extra_edit)
        prev: Any = self._extra_edit
        if self._deck_combo is not None:
            self.setTabOrder(self._extra_edit, self._deck_combo)
            prev = self._deck_combo
        self.setTabOrder(prev, self._mode_combo)
        self.setTabOrder(self._mode_combo, self._direction_combo)
        self.setTabOrder(self._direction_combo, self._type_check)
        self.setTabOrder(self._type_check, self._context_check)

    def _populate_decks(self) -> None:
        if self._deck_combo is None:
            return
        names = sorted(d.name for d in self._mw.col.decks.all_names_and_ids())
        self._deck_combo.addItems(names)
        current = self._config.deck()
        index = self._deck_combo.findText(current)
        if index >= 0:
            self._deck_combo.setCurrentIndex(index)

    def _load_page(self) -> None:
        # The accent is a validated CSS colour (see RenderConfig._as_color), so
        # it is safe to inline; it makes the editor markers match the card accent.
        accent = self._config.render_config().accent_color
        body = "\n".join(
            [
                f"<style>:root {{ --ed-accent: {accent}; }}</style>",
                f"<style>{read_web('editor/marker.css')}</style>",
                read_web("editor/marker.html"),
                f"<script>{read_web('editor/marker.js')}</script>",
            ]
        )
        self.web.stdHtml(body)

    # -- bridge callbacks ------------------------------------------------------

    def _on_web_ready(self) -> None:
        self._web_ready = True
        if self._pending_display is not None:
            data_url, markers = self._pending_display
            self._pending_display = None
            self._show_image(data_url, markers)

    def _on_count(self, count: int) -> None:
        self._marker_count = count
        self._refresh_marker_state()

    def _refresh_marker_state(self) -> None:
        """Reflect the current marker count in the status line and Save button."""
        self._update_status()
        self._update_save_enabled()

    # -- image handling --------------------------------------------------------

    def _queue_existing_image(self, prefill: LoadedNote) -> None:
        """Show the prefilled note's image with its markers once the page is ready.

        A missing media file (e.g. the collection is not fully synced) must not
        block editing: warn, and let the user reload an image and re-mark.
        """
        filename = prefill.image_filename
        path = (
            os.path.join(self._mw.col.media.dir(), filename) if filename else ""
        )
        if not path or not os.path.exists(path):
            # Without the image the canvas can't show the markers, so treat it as
            # "no markers yet": disable Save until the user reloads an image.
            self._marker_count = 0
            self._update_save_enabled()
            self._status.setText(
                "Image file not found — click “Replace image…” to reload it."
            )
            return
        markers = [
            {"x": s.target.x, "y": s.target.y, "label": s.label}
            for s in prefill.structures.ordered
        ]
        self._display_from_path(path, markers)

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose image", "", _IMAGE_FILTER
        )
        if not path:
            return
        # A newly chosen image replaces whatever was there and starts fresh: the
        # canvas resets its markers, so old positions (relative to the old image)
        # are not carried onto a different picture.
        self._new_image_path = path
        self._marker_count = 0
        self._display_from_path(path, None)
        self._refresh_marker_state()

    def _display_from_path(
        self, path: str, markers: list[dict[str, Any]] | None
    ) -> None:
        data_url = self._read_data_url(path)
        if data_url is None:
            return
        if self._web_ready:
            self._show_image(data_url, markers)
        else:
            self._pending_display = (data_url, markers)

    def _read_data_url(self, path: str) -> str | None:
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            showWarning(f"Could not read the image:\n{exc}")
            return None
        mime = mimetypes.guess_type(path)[0] or "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _show_image(
        self, data_url: str, markers: list[dict[str, Any]] | None
    ) -> None:
        js_markers = json.dumps(markers) if markers is not None else "null"
        self.web.eval(f"ROEditor.setImage({json.dumps(data_url)}, {js_markers})")

    def _has_image(self) -> bool:
        return bool(self._new_image_path or self._existing_filename)

    # -- saving ----------------------------------------------------------------

    def _save(self) -> None:
        if self._saving:
            return  # a save is already in flight; ignore the extra press
        if not self._has_image():
            showWarning("Load an image before saving.")
            return
        # Reading the markers is an async round-trip to the webview. Freeze the
        # image controls until it returns so the picture can't be swapped in that
        # window — otherwise the markers we're about to capture (which belong to
        # the image shown *now*) could be paired with a different image. The
        # `_saving` lock is held from here until the persist op resolves so a
        # second Save press can't queue a duplicate note.
        self._saving = True
        self._freeze_for_save(True)
        self.web.evalWithCallback("ROEditor.getMarkers()", self._on_markers)

    def _abort_save(self) -> None:
        """Release the pre-save freeze so the user can fix input and retry."""
        self._saving = False
        self._freeze_for_save(False)

    def _freeze_for_save(self, frozen: bool) -> None:
        self._load_button.setEnabled(not frozen)
        save = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        if save is not None:
            save.setEnabled(not frozen)
        if not frozen:
            self._update_save_enabled()

    def _on_markers(self, markers: Any) -> None:
        # Markers are now captured for the image that was shown when Save ran.
        if not self._has_image():  # image was cleared between Save and callback
            self._abort_save()
            return
        structures = self._structures_from_markers(markers)
        if structures is None:  # invalid input; the helper already told the user
            self._abort_save()
            return
        result = MarkupResult(
            structures=structures,
            options=self._read_options(),
            header=self._header_edit.text().strip(),
            back_extra=self._extra_edit.toPlainText().strip(),
            new_image_path=self._new_image_path,
            existing_image_filename=self._existing_filename,
            deck_name=(
                self._deck_combo.currentText() if self._deck_combo is not None else None
            ),
        )
        # Controls stay frozen and `_saving` stays held until the background
        # persist op resolves: on success the saver closes the dialog via
        # finish_saved(); on failure it calls save_failed() to release the lock.
        self._saver.save(self, result)

    def _structures_from_markers(self, markers: Any) -> StructureSet | None:
        """Validate the raw markers from the canvas into a StructureSet.

        Returns ``None`` (after telling the user what's wrong) on any invalid
        input, so the caller can simply bail.
        """
        if not isinstance(markers, list) or not markers:
            showWarning("Add at least one marker before saving.")
            return None
        invalid = [i for i, m in enumerate(markers) if not str(m.get("label", "")).strip()]
        if invalid:
            self.web.eval(f"ROEditor.markInvalid({json.dumps(invalid)})")
            showWarning("Every marker needs a label.")
            return None
        try:
            return StructureSet.from_unordered(
                [
                    Structure(
                        ordinal=1,
                        target=NormalizedPoint(x=float(m["x"]), y=float(m["y"])),
                        label=str(m["label"]).strip(),
                    )
                    for m in markers
                ]
            )
        except (KeyError, ValueError) as exc:
            showWarning(f"Could not build the card:\n{exc}")
            return None

    def _read_options(self) -> CardOptions:
        """Read the card-option widgets into the immutable domain value object."""
        return CardOptions(
            direction=self._direction_combo.currentData(),
            interaction=(
                Interaction.TYPE if self._type_check.isChecked() else Interaction.REVEAL
            ),
            context_labels=self._context_check.isChecked(),
            mode=self._mode_combo.currentData(),
        )

    def finish_saved(self, message: str) -> None:
        """Called by a saver once persistence succeeds: notify and close."""
        self._saving = False
        tooltip(message)
        self.accept()

    def save_failed(self, message: str) -> None:
        """Called by a saver if persistence fails: release the save lock so the
        user can retry, and surface the error."""
        self._abort_save()
        showWarning(message)

    # -- status / lifecycle ----------------------------------------------------

    def _update_status(self) -> None:
        if not self._has_image():
            self._status.setText("Load an image to begin.")
        else:
            self._status.setText(
                f"{self._marker_count} marker{'s' if self._marker_count != 1 else ''}"
                " placed — click the image to add more."
            )

    def _update_save_enabled(self) -> None:
        save = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        if save is not None:
            # Never re-enable Save while a persist op is in flight (`_saving`),
            # so a second press can't queue a duplicate note.
            save.setEnabled(
                not self._saving and self._has_image() and self._marker_count > 0
            )

    def _on_finished(self, _result: int) -> None:
        # AnkiWebView should be torn down explicitly or Anki can leak/crash on
        # close. cleanup() exists on modern AnkiWebView; guard for safety across
        # versions so a missing method can't raise out of this close handler.
        cleanup = getattr(self.web, "cleanup", None)
        if callable(cleanup):
            cleanup()
        # The dialog is parented to the main window, so closing it only hides it;
        # schedule its deletion so repeated opens (especially edits from the
        # Browser) don't accumulate hidden dialogs for the whole session.
        self.deleteLater()
