"""The reviewer key override: it must be nearly always inert."""

from __future__ import annotations

from typing import Any

import pytest

from randomized_occlusion.notetype.spec import DEFAULT_SPEC
from randomized_occlusion.review_shortcuts import install, should_intercept

OURS = DEFAULT_SPEC.name


def _args(**overrides: Any) -> dict:
    base = {
        "main_state": "review",
        "reviewer_state": "question",
        "notetype_name": OURS,
        "our_notetype_name": OURS,
        "single_card_mode": True,
    }
    base.update(overrides)
    return base


def test_a_single_card_question_is_ours_to_handle():
    assert should_intercept(**_args()) is True


@pytest.mark.parametrize(
    "override",
    [
        {"main_state": "deckBrowser"},
        {"main_state": "overview"},
        {"reviewer_state": "answer"},
        {"notetype_name": "Basic"},
        {"notetype_name": None},
        {"notetype_name": ""},
        {"single_card_mode": False},
    ],
)
def test_everything_else_belongs_to_anki(override: dict):
    # A wrong True is a key that stops working across the whole reviewer, so
    # every case that is not unmistakably ours has to fall through.
    assert should_intercept(**_args(**override)) is False


class _Web:
    """Models aqt's AnkiWebView.evalWithCallback: the page answers, then the
    callback runs. ``advanced`` is what the page's advance() returns."""

    def __init__(self, advanced: bool = True) -> None:
        self.evaluated: list[str] = []
        self._advanced = advanced

    def evalWithCallback(self, script: str, cb: Any) -> None:  # Anki's spelling
        self.evaluated.append(script)
        if cb is not None:
            cb(self._advanced)


class _Reviewer:
    def __init__(self, card: Any, state: str = "question", advanced: bool = True) -> None:
        self.card = card
        self.state = state
        self.web = _Web(advanced)
        self.entered = 0

    def onEnterKey(self) -> None:  # Anki's own spelling
        self.entered += 1


class _MW:
    def __init__(self, reviewer: Any, state: str = "review") -> None:
        self.reviewer = reviewer
        self.state = state


class _Hooks:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    class _Hook:
        def __init__(self, outer: Any) -> None:
            self._outer = outer

        def append(self, cb: Any) -> None:
            self._outer.callbacks.append(cb)

    @property
    def state_shortcuts_will_change(self) -> Any:
        return self._Hook(self)


class _Note:
    def __init__(self, name: str = OURS) -> None:
        self._name = name

    def note_type(self) -> dict:
        return {"name": self._name}


class _Card:
    def __init__(self, note: Any) -> None:
        self._note = note

    def note(self) -> Any:
        return self._note


def _install(mw: Any, *, single: bool = True, raises: bool = False):
    hooks = _Hooks()

    def is_single(_note: Any) -> bool:
        if raises:
            raise RuntimeError("payload unreadable")
        return single

    install(hooks, mw, OURS, is_single)
    assert len(hooks.callbacks) == 1
    return hooks.callbacks[0]


def test_only_the_review_state_is_touched():
    mw = _MW(_Reviewer(_Card(_Note())))
    on_shortcuts = _install(mw)
    for state in ("deckBrowser", "overview", "profileManager"):
        shortcuts: list = []
        on_shortcuts(state, shortcuts)
        assert shortcuts == [], f"{state} shortcuts were rewritten"


def test_exactly_the_three_keys_anki_binds_are_appended():
    mw = _MW(_Reviewer(_Card(_Note())))
    on_shortcuts = _install(mw)
    existing = [("e", lambda: None)]
    shortcuts = list(existing)
    on_shortcuts("review", shortcuts)

    assert shortcuts[: len(existing)] == existing, "an existing binding was disturbed"
    assert [key for key, _ in shortcuts[len(existing) :]] == [" ", "Return", "Enter"]


def _press(mw: Any, **kwargs: Any) -> None:
    on_shortcuts = _install(mw, **kwargs)
    shortcuts: list = []
    on_shortcuts("review", shortcuts)
    shortcuts[0][1]()  # the Space handler


def test_a_single_card_question_advances_the_cycle():
    reviewer = _Reviewer(_Card(_Note()))
    _press(_MW(reviewer))
    assert reviewer.entered == 0, "Anki's handler ran as well as ours"
    assert len(reviewer.web.evaluated) == 1
    assert "RandomizedOcclusion.advance" in reviewer.web.evaluated[0]


def test_a_finished_cycle_hands_the_key_back_to_anki():
    # advance() returns false once the cycle is done -- there is nothing left to
    # press. Discarding that answer left Space, Return and Enter dead on the last
    # step, so the card could not be answered from the keyboard at all.
    reviewer = _Reviewer(_Card(_Note()), advanced=False)
    _press(_MW(reviewer))
    assert len(reviewer.web.evaluated) == 1, "the page was never asked"
    assert reviewer.entered == 1, "the key was swallowed by a finished cycle"


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: _MW(_Reviewer(_Card(_Note("Basic")))), id="another-notetype"),
        pytest.param(lambda: _MW(_Reviewer(_Card(_Note()), state="answer")), id="answer-side"),
        pytest.param(lambda: _MW(_Reviewer(_Card(_Note())), state="overview"), id="not-reviewing"),
        pytest.param(lambda: _MW(_Reviewer(None)), id="no-card"),
    ],
)
def test_every_other_card_still_gets_anki_s_own_handler(build):
    mw = build()
    _press(mw)
    assert mw.reviewer.entered == 1, "the key was swallowed"
    assert mw.reviewer.web.evaluated == []


def test_a_multi_card_note_is_left_alone():
    reviewer = _Reviewer(_Card(_Note()))
    _press(_MW(reviewer), single=False)
    assert reviewer.entered == 1
    assert reviewer.web.evaluated == []


def test_an_unreadable_note_falls_through_rather_than_dying():
    # This runs on a Qt shortcut. An exception escaping here would leave Space
    # doing nothing at all for the rest of the session, on every card.
    reviewer = _Reviewer(_Card(_Note()))
    _press(_MW(reviewer), raises=True)
    assert reviewer.entered == 1, "a bad payload killed the key"
    assert reviewer.web.evaluated == []
