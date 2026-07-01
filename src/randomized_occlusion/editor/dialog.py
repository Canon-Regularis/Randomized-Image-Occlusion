"""The image-marking editor dialog.

Hosts the marking canvas in an :class:`AnkiWebView`, collects native inputs
(header, extra, deck), and hands a fully-formed :class:`NoteRequest` to the
note-creation op. The dialog is a thin shell: validation lives in the domain
layer and routing lives in :class:`MarkerBridge`.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from typing import Any

from aqt.qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
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

from ..config.config_service import ConfigService
from ..domain.geometry import NormalizedPoint
from ..domain.structure import Structure
from ..domain.structure_set import StructureSet
from ..ops.create_note import NoteRequest, add_randomized_occlusion_note
from ..resources import read_web
from .bridge import MarkerBridge

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.svg)"


class MarkerDialog(QDialog):
    def __init__(self, main_window: Any, config_service: ConfigService) -> None:
        super().__init__(main_window)
        self._mw = main_window
        self._config = config_service
        self._image_path: str | None = None
        self._web_ready = False
        self._marker_count = 0
        self._bridge = MarkerBridge(
            on_ready=self._on_web_ready, on_count=self._on_count
        )

        self.setWindowTitle("Randomized Image Occlusion")
        self.resize(960, 680)
        self._build_ui()
        self._load_page()
        qconnect(self.finished, self._on_finished)

    # -- construction ----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._load_button = QPushButton("Load image…")
        qconnect(self._load_button.clicked, self._choose_image)
        toolbar.addWidget(self._load_button)
        toolbar.addStretch(1)
        self._status = QLabel("Load an image to begin.")
        self._status.setStyleSheet("color: #777;")
        toolbar.addWidget(self._status)
        layout.addLayout(toolbar)

        self.web = AnkiWebView(parent=self, title="randomized-occlusion-editor")
        self.web.set_bridge_command(self._bridge.handle, self)
        layout.addWidget(self.web, stretch=1)

        form = QFormLayout()
        self._header_edit = QLineEdit()
        self._header_edit.setPlaceholderText("Optional title shown above the image")
        form.addRow("Header:", self._header_edit)

        self._extra_edit = QPlainTextEdit()
        self._extra_edit.setPlaceholderText("Optional extra info shown on the answer side")
        self._extra_edit.setFixedHeight(56)
        form.addRow("Back extra:", self._extra_edit)

        self._deck_combo = QComboBox()
        self._populate_decks()
        form.addRow("Deck:", self._deck_combo)
        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        qconnect(self._buttons.accepted, self._save)
        qconnect(self._buttons.rejected, self.reject)
        layout.addWidget(self._buttons)
        self._update_save_enabled()

    def _populate_decks(self) -> None:
        names = sorted(d.name for d in self._mw.col.decks.all_names_and_ids())
        self._deck_combo.addItems(names)
        current = self._config.deck()
        index = self._deck_combo.findText(current)
        if index >= 0:
            self._deck_combo.setCurrentIndex(index)

    def _load_page(self) -> None:
        body = "\n".join(
            [
                f"<style>{read_web('editor/marker.css')}</style>",
                read_web("editor/marker.html"),
                f"<script>{read_web('editor/marker.js')}</script>",
            ]
        )
        self.web.stdHtml(body)

    # -- bridge callbacks ------------------------------------------------------

    def _on_web_ready(self) -> None:
        self._web_ready = True
        if self._image_path:
            self._push_image(self._image_path)

    def _on_count(self, count: int) -> None:
        self._marker_count = count
        self._update_status()
        self._update_save_enabled()

    # -- image handling --------------------------------------------------------

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose image", "", _IMAGE_FILTER
        )
        if not path:
            return
        self._image_path = path
        self._marker_count = 0
        if self._web_ready:
            self._push_image(path)
        self._update_status()
        self._update_save_enabled()

    def _push_image(self, path: str) -> None:
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            showWarning(f"Could not read the image:\n{exc}")
            return
        mime = mimetypes.guess_type(path)[0] or "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        self.web.eval(f"ROEditor.setImage({json.dumps(data_url)})")

    # -- saving ----------------------------------------------------------------

    def _save(self) -> None:
        if not self._image_path:
            showWarning("Load an image before adding a card.")
            return
        self.web.evalWithCallback("ROEditor.getMarkers()", self._on_markers)

    def _on_markers(self, markers: Any) -> None:
        if not self._image_path:  # image was cleared between Save and callback
            return
        if not isinstance(markers, list) or not markers:
            showWarning("Add at least one marker before saving.")
            return

        invalid = [i for i, m in enumerate(markers) if not str(m.get("label", "")).strip()]
        if invalid:
            self.web.eval(f"ROEditor.markInvalid({json.dumps(invalid)})")
            showWarning("Every marker needs a label.")
            return

        try:
            structures = StructureSet.from_unordered(
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
            return

        deck_name = self._deck_combo.currentText() or "Default"
        self._config.set_deck(deck_name)
        request = NoteRequest(
            image_path=self._image_path,
            structures=structures,
            deck_name=deck_name,
            header=self._header_edit.text().strip(),
            back_extra=self._extra_edit.toPlainText().strip(),
        )
        add_randomized_occlusion_note(
            parent=self,
            request=request,
            render_config=self._config.render_config(),
            on_success=lambda _changes: self._on_added(len(structures)),
        )

    def _on_added(self, card_count: int) -> None:
        tooltip(f"Added {card_count} card{'s' if card_count != 1 else ''}.")
        self.accept()

    # -- status / lifecycle ----------------------------------------------------

    def _update_status(self) -> None:
        if not self._image_path:
            self._status.setText("Load an image to begin.")
        else:
            self._status.setText(
                f"{self._marker_count} marker{'s' if self._marker_count != 1 else ''}"
                " placed — click the image to add more."
            )

    def _update_save_enabled(self) -> None:
        save = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        if save is not None:
            save.setEnabled(bool(self._image_path) and self._marker_count > 0)

    def _on_finished(self, _result: int) -> None:
        # AnkiWebView should be torn down explicitly or Anki can leak/crash on
        # close. cleanup() exists on modern AnkiWebView; guard for safety across
        # versions so a missing method can't raise out of this close handler.
        cleanup = getattr(self.web, "cleanup", None)
        if callable(cleanup):
            cleanup()
