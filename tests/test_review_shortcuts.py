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
        "single_card_mode": lambda: True,
    }
    base.update(overrides)
    return base


def test_a_single_card_question_is_ours_to_handle():
    assert should_intercept(**_args()) is True


def test_the_payload_is_not_read_for_a_card_that_is_not_ours():
    # `single_card_mode` is a callable so that the cheap checks genuinely guard
    # it. As a value it was evaluated before the call, so every key press on
    # every card of every other note type paid to decode a payload it could not
    # use -- and any failure in that decode looked like an ordinary event rather
    # than a fault in one of our own notes.
    calls = []

    def probe() -> bool:
        calls.append(1)
        return True

    for override in ({"notetype_name": "Basic"}, {"main_state": "deckBrowser"},
                     {"reviewer_state": "answer"}):
        assert should_intercept(**_args(single_card_mode=probe, **override)) is False
    assert calls == [], "the payload was decoded for a card we do not handle"

    assert should_intercept(**_args(single_card_mode=probe)) is True
    assert calls == [1], "the payload was not decoded for one of our own cards"


@pytest.mark.parametrize(
    "override",
    [
        {"main_state": "deckBrowser"},
        {"main_state": "overview"},
        {"reviewer_state": "answer"},
        {"notetype_name": "Basic"},
        {"notetype_name": None},
        {"notetype_name": ""},
        {"single_card_mode": lambda: False},
    ],
)
def test_everything_else_belongs_to_anki(override: dict):
    # A wrong True is a key that stops working across the whole reviewer, so
    # every case that is not unmistakably ours has to fall through.
    assert should_intercept(**_args(**override)) is False


class _Web:
    """Models aqt's AnkiWebView.evalWithCallback: the page answers, then the
    callback runs. ``advanced`` is what the page's advance() returns.

    ``before_callback`` runs between the two, standing in for anything that can
    change the card while the eval is in flight -- auto-advance, a Browser edit.
    """

    def __init__(self, advanced: bool = True, before_callback: Any = None) -> None:
        self.evaluated: list[str] = []
        self._advanced = advanced
        self._before_callback = before_callback

    def evalWithCallback(self, script: str, cb: Any) -> None:  # Anki's spelling
        self.evaluated.append(script)
        if self._before_callback is not None:
            self._before_callback()
        if cb is not None:
            cb(self._advanced)


class _Reviewer:
    def __init__(self, card: Any, state: str = "question", advanced: bool = True,
                 before_callback: Any = None) -> None:
        self.card = card
        self.state = state
        self.web = _Web(advanced, before_callback)
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


#: Stand-ins for the objects bootstrap passes. `install` takes the spellings from
#: its caller and has no default, so every test has to name them.
_KEYS = (" ", "Return", "Enter")


def _install(mw: Any, *, single: bool = True, raises: bool = False, keys=_KEYS):
    hooks = _Hooks()

    def is_single(_note: Any) -> bool:
        if raises:
            raise RuntimeError("payload unreadable")
        return single

    install(hooks, mw, OURS, is_single, keys=keys)
    assert len(hooks.callbacks) == 1
    return hooks.callbacks[0]


def test_only_the_review_state_is_touched():
    mw = _MW(_Reviewer(_Card(_Note())))
    on_shortcuts = _install(mw)
    for state in ("deckBrowser", "overview", "profileManager"):
        shortcuts: list = []
        on_shortcuts(state, shortcuts)
        assert shortcuts == [], f"{state} shortcuts were rewritten"


def test_the_keys_the_caller_names_are_the_keys_appended():
    # bootstrap passes the objects Anki itself binds -- " " as a string but
    # Return and Enter as Qt.Key members -- because Anki dedupes through
    # {QKeySequence(key): fn} and a mismatched spelling would leave both
    # bindings alive, which Qt reports as an ambiguous shortcut. Asserting the
    # literal strings here pinned the wrong contract: it passed whether or not
    # the caller was spelling them the way Anki does.
    sentinels = (" ", object(), object())
    mw = _MW(_Reviewer(_Card(_Note())))
    on_shortcuts = _install(mw, keys=sentinels)
    existing = [("e", lambda: None)]
    shortcuts = list(existing)
    on_shortcuts("review", shortcuts)

    assert shortcuts[: len(existing)] == existing, "an existing binding was disturbed"
    assert [key for key, _ in shortcuts[len(existing) :]] == list(sentinels)


def test_the_caller_must_name_the_keys():
    # There is no default on purpose. Any default would have to be the string
    # spelling, and Anki binds Return and Enter as Qt.Key members -- a spelling
    # its QKeySequence dedupe may not treat as the same key, which leaves both
    # bindings alive and takes Return and Enter out of the reviewer for every
    # card. A caller that forgets should fail loudly here, not in the reviewer.
    with pytest.raises(TypeError):
        install(_Hooks(), _MW(_Reviewer(_Card(_Note()))), OURS, lambda _n: True)


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


def test_a_note_we_cannot_read_is_reported_once_and_only_once(capsys):
    # Reachable only for one of OUR notes -- should_intercept checks the note
    # type before the payload is touched -- so it means a payload we wrote will
    # not read back. Falling through in silence restores the very bug this
    # module exists to fix, with nothing to say why the cycle keys went dead on
    # that one note. Latched, because it recurs on every key press.
    reviewer = _Reviewer(_Card(_Note()))
    on_shortcuts = _install(_MW(reviewer), raises=True)
    shortcuts: list = []
    on_shortcuts("review", shortcuts)
    press = shortcuts[0][1]

    press()
    first = capsys.readouterr().out
    assert "Randomized Image Occlusion" in first, "the failure was swallowed in silence"
    assert "payload unreadable" in first, "the cause is not in the message"

    press()
    press()
    assert capsys.readouterr().out == "", "a line per keystroke would bury the first"


def test_a_callback_that_lands_after_the_card_moved_on_does_nothing():
    # Anki's auto-advance, or an edit in the Browser, can change the card
    # between the key press and the eval's callback. Acting on the stale
    # decision flips a card the learner never asked to flip.
    moved = _MW(None)

    def leave_review() -> None:
        moved.state = "deckBrowser"

    reviewer = _Reviewer(_Card(_Note()), advanced=False, before_callback=leave_review)
    moved.reviewer = reviewer
    _press(moved)

    assert len(reviewer.web.evaluated) == 1, "the page was never asked"
    assert reviewer.entered == 0, "a stale callback flipped a card that had moved on"


def test_an_unreadable_note_falls_through_rather_than_dying():
    # This runs on a Qt shortcut. An exception escaping here would leave Space
    # doing nothing at all for the rest of the session, on every card.
    reviewer = _Reviewer(_Card(_Note()))
    _press(_MW(reviewer), raises=True)
    assert reviewer.entered == 1, "a bad payload killed the key"
    assert reviewer.web.evaluated == []
