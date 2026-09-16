"""Give a single-card cycle the keys Anki would otherwise take from it.

Anki binds Space, Return and Enter as ``QShortcut``s on the MAIN WINDOW
(``aqt/main.py``'s ``applyShortcuts``), so they never reach a focused button
inside the card's web view and no amount of ``stopPropagation`` in ``render.js``
can hold on to them. In single-card mode that means one Space press flips
straight to the answer key and abandons the cycle the learner was halfway
through.

``state_shortcuts_will_change`` is the documented way out: ``_normalize_shortcuts``
keeps the LAST binding for a key, "so add-ons will override standard shortcuts if
they append to the shortcut list". This module appends exactly three, and every
one of them falls through to Anki's own handler unless the card in front of the
learner is one of ours AND is a single-card note AND is still on its question
side. The decision is :func:`should_intercept`, which is pure so it can be tested
without Anki present; everything else here is the Qt plumbing around it.

This is desktop-only by nature. AnkiDroid and AnkiMobile run the same card with
no add-on at all, so the cycle there is driven by tapping, and Enter (which
``render.js`` handles itself) works everywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["install", "should_intercept"]


def should_intercept(
    *,
    main_state: str,
    reviewer_state: str,
    notetype_name: str | None,
    our_notetype_name: str,
    single_card_mode: Callable[[], bool],
) -> bool:
    """Whether this key press belongs to a single-card cycle rather than to Anki.

    Deliberately conservative: every unknown becomes ``False``, because the cost
    of a wrong ``True`` is a key that no longer works anywhere in the reviewer,
    while the cost of a wrong ``False`` is merely the behaviour we already had.

    ``single_card_mode`` is a CALLABLE, not a value. It decodes the note's
    payload, and as a value Python evaluated it before the call -- so the two
    cheap checks below guarded nothing and every key press on every card of
    every other note type paid for a read it could not use. As a callable the
    order in the text is the order in fact, and a failure inside it can only
    ever concern one of our own notes.
    """
    if main_state != "review" or reviewer_state != "question":
        return False
    if not notetype_name or notetype_name != our_notetype_name:
        return False
    return single_card_mode()


def install(
    gui_hooks: Any,
    mw: Any,
    our_notetype_name: str,
    is_single_card: Callable[[Any], bool],
    *,
    keys: tuple[Any, ...],
) -> None:
    """Register the override. ``is_single_card`` reads a note, and may raise.

    ``keys`` is required, and has no default on purpose. Anki binds `" "` as a
    string but Return and Enter as `Qt.Key` members, and our binding replaces
    its own only if `QKeySequence` treats the two spellings as one key. The
    caller passes the objects Anki itself binds, which removes that question
    rather than relying on the answer -- so a default here could only be the
    spelling that might leave BOTH bindings alive and take Return and Enter out
    of the reviewer entirely. This module imports no aqt (that is why its tests
    run at all), so the constants come from the caller.
    """
    # Latched: the failure below can recur on every key press, and a console
    # line per keystroke would bury the first one.
    reported = [False]

    def handler() -> None:
        reviewer = mw.reviewer
        if reviewer is None:
            # Nothing to intercept for and nothing to hand the key back to.
            return
        # Qt calls this with the main window focused, so anything that goes wrong
        # must end in Anki's own behaviour rather than a dead key.
        try:
            card = reviewer.card
            note = card.note() if card is not None else None
            notetype = note.note_type() if note is not None else None
            intercept = should_intercept(
                main_state=mw.state,
                reviewer_state=reviewer.state,
                notetype_name=(notetype or {}).get("name"),
                our_notetype_name=our_notetype_name,
                single_card_mode=lambda: is_single_card(note),
            )
        except Exception as exc:
            # Usually one of OUR notes: should_intercept checks the note type
            # before calling is_single_card, so the common cause is a payload we
            # wrote that will not read back. The try covers the reviewer reads
            # above it too, so a card or note that cannot be loaded at all lands
            # here as well. Either way, falling through in silence would restore
            # the very bug this module exists to fix with nothing to say why the
            # cycle keys stopped working.
            if not reported[0]:
                reported[0] = True
                print(
                    "[Randomized Image Occlusion] could not read a note while "
                    f"handling a reviewer key; falling back to Anki: {exc!r}"
                )
            intercept = False
        if not intercept:
            reviewer.onEnterKey()
            return
        # advance() reports whether there was a cycle to advance, and the
        # answer is only knowable in the page -- a FINISHED cycle has none, and
        # its Space must reach Anki or the card can never be answered. So the
        # result is read back and the fall-through happens in the callback.
        # aqt's own reviewer uses evalWithCallback the same way for
        # getTypedAnswer(), and it drops late callbacks after teardown.
        def resume(advanced: Any) -> None:
            if advanced:
                return
            # The reviewer can be gone by the time this lands (the profile
            # closed, or the learner left the reviewer), so re-check before
            # acting on a decision taken before the round trip. Note the limit:
            # if Anki's auto-advance moved to ANOTHER card, both conditions
            # still hold and the key reaches that card instead.
            if mw.state == "review" and mw.reviewer is not None:
                mw.reviewer.onEnterKey()

        mw.reviewer.web.evalWithCallback(
            "(window.RandomizedOcclusion && window.RandomizedOcclusion.advance)"
            " ? window.RandomizedOcclusion.advance() : false;",
            resume,
        )

    def on_shortcuts(state: str, shortcuts: list[tuple[Any, Callable[[], None]]]) -> None:
        if state != "review":
            return
        # Appended, so `_normalize_shortcuts` keeps ours; everything else Anki
        # binds is untouched.
        shortcuts.extend((key, handler) for key in keys)

    gui_hooks.state_shortcuts_will_change.append(on_shortcuts)
