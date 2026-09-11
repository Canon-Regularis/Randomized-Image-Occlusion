"""What the marking dialog's Save actually persists, and what it reports.

These 106 lines had no test at all: ``ops/runner.py`` imported ``CollectionOp``
at module scope, so importing the savers needed Anki and nothing here could run.
That import is now made lazily inside the one function that uses it, which is the
whole reason this file can exist.

The doubles below record what the saver asked for rather than re-implementing it,
so a test asserts what reaches Anki instead of reading back its own literals.
"""

from __future__ import annotations

import pytest

from randomized_occlusion.config.config_service import ConfigService, InMemoryConfigProvider
from randomized_occlusion.domain.card_options import CardMode, CardOptions, Direction
from randomized_occlusion.domain.geometry import NormalizedPoint
from randomized_occlusion.domain.structure import Structure
from randomized_occlusion.domain.structure_set import StructureSet
from randomized_occlusion.editor.savers import CreateNoteSaver, MarkupResult, UpdateNoteSaver

MAIN_WINDOW = object()


class SpyDialog:
    """Records the outcome the saver reports back to the dialog."""

    def __init__(self, progress_parent=MAIN_WINDOW):
        self.saved: list[str] = []
        self.failed: list[str] = []
        #: What MarkerDialog exposes so the op does not parent Anki's progress
        #: dialog to a widget that deletes itself on close.
        self.progress_parent = progress_parent

    def finish_saved(self, message: str) -> None:
        self.saved.append(message)

    def save_failed(self, message: str) -> None:
        self.failed.append(message)


def _structures(count: int) -> StructureSet:
    return StructureSet.from_unordered(
        [
            Structure(ordinal=i, target=NormalizedPoint(0.1 * i, 0.2), label=f"L{i}")
            for i in range(1, count + 1)
        ]
    )


def _result(count: int = 3, **overrides) -> MarkupResult:
    fields = {
        "structures": _structures(count),
        "options": CardOptions(),
        "header": "",
        "back_extra": "",
        "new_image_path": "C:/pictures/heart.png",
        "existing_image_filename": None,
        "deck_name": None,
    }
    fields.update(overrides)
    return MarkupResult(**fields)


def _service(**config) -> ConfigService:
    return ConfigService(InMemoryConfigProvider(dict(config)))


@pytest.fixture
def captured(monkeypatch):
    """Intercept the op each saver launches, and return its recorded kwargs."""
    calls: list[dict] = []
    import randomized_occlusion.editor.savers as savers

    def record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(savers, "add_randomized_occlusion_note", record)
    monkeypatch.setattr(savers, "update_randomized_occlusion_note", record)
    return calls


# ---------------------------------------------------------------- card count


@pytest.mark.parametrize(
    ("mode", "structures", "expected"),
    [
        (CardMode.MULTI, 1, "Added 1 card."),
        (CardMode.MULTI, 5, "Added 5 cards."),
        # The one that was wrong: single mode collapses to a single cloze
        # ordinal, so five structures are one card however many were marked.
        (CardMode.SINGLE, 5, "Added 1 card."),
        (CardMode.SINGLE, 1, "Added 1 card."),
    ],
)
def test_the_reported_card_count_matches_what_anki_will_generate(
    captured, mode, structures, expected
):
    dialog = SpyDialog()
    result = _result(structures, options=CardOptions(mode=mode))
    CreateNoteSaver(_service()).save(dialog, result)

    captured[0]["on_success"](object())
    assert dialog.saved == [expected]

    # The message has to agree with the cloze field, which is what Anki counts.
    ordinals = result.structures.cloze_field(result.options).count("{{c")
    assert expected == f"Added {ordinals} card{'' if ordinals == 1 else 's'}."


# ------------------------------------------------- the progress dialog's parent


def test_the_operation_is_parented_away_from_the_dialog(captured):
    # Anki makes its progress dialog a Qt CHILD of whatever a CollectionOp is
    # given (aqt: run_in_background -> taskman.with_progress(parent=...) ->
    # progress.start(parent=...) -> ProgressDialog(parent)). MarkerDialog calls
    # deleteLater() on itself when it closes, which destroys its children, so
    # saving and then closing the editor would destroy Anki's progress dialog
    # while the operation was still running.
    dialog = SpyDialog()
    CreateNoteSaver(_service()).save(dialog, _result())
    assert captured[0]["parent"] is MAIN_WINDOW
    assert captured[0]["parent"] is not dialog


def test_updating_is_parented_away_from_the_dialog_too(captured):
    dialog = SpyDialog()
    UpdateNoteSaver(_service(), note_id=1).save(dialog, _result())
    assert captured[0]["parent"] is MAIN_WINDOW


def test_a_dialog_offering_no_parent_still_works(captured):
    # The fallback keeps this an improvement rather than a new requirement on
    # every caller.
    class Bare(SpyDialog):
        pass

    dialog = Bare()
    del dialog.progress_parent
    CreateNoteSaver(_service()).save(dialog, _result())
    assert captured[0]["parent"] is dialog


# ---------------------------------------------------------------- create flow


def test_creating_remembers_the_chosen_deck(captured):
    CreateNoteSaver(_service()).save(SpyDialog(), _result(deck_name="Biology"))
    assert captured[0]["request"].deck_name == "Biology"


def test_creating_without_a_deck_picker_falls_back_to_default(captured):
    service = _service()
    CreateNoteSaver(service).save(SpyDialog(), _result(deck_name=None))
    assert captured[0]["request"].deck_name == "Default"


def test_the_chosen_deck_is_persisted_for_next_time(captured):
    service = _service()
    CreateNoteSaver(service).save(SpyDialog(), _result(deck_name="Biology"))
    assert service.deck() == "Biology"


def test_creating_passes_the_marked_content_through(captured):
    result = _result(4, header="Heart", back_extra="notes")
    CreateNoteSaver(_service()).save(SpyDialog(), result)
    request = captured[0]["request"]
    assert request.structures is result.structures
    assert request.header == "Heart"
    assert request.back_extra == "notes"
    assert request.image_path == "C:/pictures/heart.png"


def test_creating_reports_a_failure_to_the_dialog(captured):
    dialog = SpyDialog()
    CreateNoteSaver(_service()).save(dialog, _result())
    captured[0]["on_failure"](RuntimeError("disk full"))
    assert dialog.saved == []
    assert len(dialog.failed) == 1
    assert "disk full" in dialog.failed[0]


def test_the_note_options_reach_the_request_unchanged(captured):
    options = CardOptions(direction=Direction.REVERSE, mode=CardMode.SINGLE)
    CreateNoteSaver(_service()).save(SpyDialog(), _result(options=options))
    assert captured[0]["request"].options == options


# ---------------------------------------------------------------- update flow


def test_updating_reports_success_without_a_count(captured):
    # Deliberately asymmetric with the create flow, which names a number. An edit
    # can add and remove cards at once, so a single figure would be more likely
    # to mislead than to inform.
    dialog = SpyDialog()
    UpdateNoteSaver(_service(), note_id=7).save(dialog, _result(2))
    captured[0]["on_success"](object())
    assert dialog.saved == ["Card updated."]


def test_updating_reports_a_failure_to_the_dialog(captured):
    dialog = SpyDialog()
    UpdateNoteSaver(_service(), note_id=7).save(dialog, _result())
    captured[0]["on_failure"](RuntimeError("note is gone"))
    assert dialog.saved == []
    assert "note is gone" in dialog.failed[0]


def test_updating_targets_the_note_it_was_opened_for(captured):
    UpdateNoteSaver(_service(), note_id=99).save(SpyDialog(), _result())
    assert captured[0]["request"].note_id == 99


def test_updating_keeps_the_existing_image_when_none_was_chosen(captured):
    UpdateNoteSaver(_service(), note_id=1).save(
        SpyDialog(),
        _result(new_image_path=None, existing_image_filename="stored.png"),
    )
    request = captured[0]["request"]
    assert request.new_image_path is None
    assert request.existing_image_filename == "stored.png"


def test_updating_carries_a_newly_chosen_image(captured):
    # The other half of the rule above: when the user replaced the picture, the
    # new path has to reach the op, or the edit would silently keep the old image
    # while the markers describe the new one.
    UpdateNoteSaver(_service(), note_id=1).save(
        SpyDialog(),
        _result(new_image_path="C:/pictures/lung.png", existing_image_filename="old.png"),
    )
    request = captured[0]["request"]
    assert request.new_image_path == "C:/pictures/lung.png"
    assert request.existing_image_filename == "old.png"


def test_updating_does_not_write_the_deck(captured):
    # Editing an existing note must not move it, nor change the default deck the
    # NEXT new note lands in.
    service = _service(deck="Chemistry")
    UpdateNoteSaver(service, note_id=1).save(SpyDialog(), _result(deck_name="Biology"))
    assert service.deck() == "Chemistry"
