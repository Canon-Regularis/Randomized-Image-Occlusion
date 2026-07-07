"""Persistence strategies for the marking dialog.

The marking dialog gathers the same thing every time — a :class:`MarkupResult`
(structures, options, header/back text, and which image to use). *What happens
to it on Save* varies, so that is a Strategy:

* :class:`CreateNoteSaver` — add a brand-new note (the Tools menu and the
  Add-window **Occlusion** button both open this flow).
* :class:`UpdateNoteSaver` — rewrite an existing note (Browser edit flow).

Keeping this out of the dialog means the dialog has no idea how notes are stored,
and each flow is a small, single-responsibility object.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..config.config_service import ConfigService
from ..domain.card_options import CardOptions
from ..domain.structure_set import StructureSet
from ..notetype.spec import DEFAULT_SPEC, NoteTypeSpec
from ..ops.create_note import NoteRequest, add_randomized_occlusion_note
from ..ops.update_note import UpdateRequest, update_randomized_occlusion_note

__all__ = [
    "CreateNoteSaver",
    "MarkupResult",
    "NoteSaver",
    "UpdateNoteSaver",
]


@dataclass(frozen=True, slots=True)
class MarkupResult:
    """The validated output of a marking session, ready to be persisted."""

    structures: StructureSet
    options: CardOptions
    header: str
    back_extra: str
    # A freshly chosen file to import, or None to keep the existing image.
    new_image_path: str | None
    existing_image_filename: str | None
    # Only meaningful when the saver wants a deck (creation).
    deck_name: str | None


def _cards(count: int) -> str:
    return f"{count} card{'s' if count != 1 else ''}"


class NoteSaver(ABC):
    """Turns a :class:`MarkupResult` into a persisted note."""

    #: Whether the dialog should offer a deck picker (only creation does).
    wants_deck: bool = False

    def title(self) -> str:
        return "Randomized Image Occlusion"

    def load_button_label(self) -> str:
        return "Load image…"

    @abstractmethod
    def save(self, dialog: Any, result: MarkupResult) -> None:
        """Persist ``result``. Implementations close ``dialog`` when done via
        ``dialog.finish_saved(message)`` (possibly from an async callback)."""


class CreateNoteSaver(NoteSaver):
    """Adds a brand-new note via the undo-safe create op."""

    wants_deck = True

    def __init__(self, config: ConfigService, spec: NoteTypeSpec = DEFAULT_SPEC) -> None:
        self._config = config
        self._spec = spec

    def save(self, dialog: Any, result: MarkupResult) -> None:
        deck = result.deck_name or "Default"
        self._config.set_deck(deck)
        request = NoteRequest(
            image_path=result.new_image_path or "",
            structures=result.structures,
            deck_name=deck,
            options=result.options,
            header=result.header,
            back_extra=result.back_extra,
        )
        count = len(result.structures)
        add_randomized_occlusion_note(
            parent=dialog,
            request=request,
            render_config=self._config.render_config(),
            spec=self._spec,
            on_success=lambda _changes: dialog.finish_saved(f"Added {_cards(count)}."),
            on_failure=lambda exc: dialog.save_failed(f"Could not add the card:\n\n{exc}"),
        )


class UpdateNoteSaver(NoteSaver):
    """Rewrites an existing note via the undo-safe update op."""

    def __init__(
        self, config: ConfigService, note_id: int, spec: NoteTypeSpec = DEFAULT_SPEC
    ) -> None:
        self._config = config
        self._note_id = note_id
        self._spec = spec

    def title(self) -> str:
        return "Edit Randomized Image Occlusion"

    def load_button_label(self) -> str:
        return "Replace image…"

    def save(self, dialog: Any, result: MarkupResult) -> None:
        request = UpdateRequest(
            note_id=self._note_id,
            structures=result.structures,
            existing_image_filename=result.existing_image_filename or "",
            options=result.options,
            new_image_path=result.new_image_path,
            header=result.header,
            back_extra=result.back_extra,
        )
        update_randomized_occlusion_note(
            parent=dialog,
            request=request,
            render_config=self._config.render_config(),
            spec=self._spec,
            on_success=lambda _changes: dialog.finish_saved("Card updated."),
            on_failure=lambda exc: dialog.save_failed(f"Could not update the card:\n\n{exc}"),
        )
