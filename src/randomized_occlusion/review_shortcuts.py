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

#: The keys Anki binds to "show answer / answer card" in the reviewer.
_KEYS = (" ", "Return", "Enter")


def should_intercept(
    *,
    main_state: str,
    reviewer_state: str,
    notetype_name: str | None,
    our_notetype_name: str,
    single_card_mode: bool,
) -> bool:
    """Whether this key press belongs to a single-card cycle rather than to Anki.

    Deliberately conservative: every unknown becomes ``False``, because the cost
    of a wrong ``True`` is a key that no longer works anywhere in the reviewer,
    while the cost of a wrong ``False`` is merely the behaviour we already had.
    """
    if main_state != "review" or reviewer_state != "question":
        return False
    if not notetype_name or notetype_name != our_notetype_name:
        return False
    return single_card_mode


def install(
    gui_hooks: Any,
    mw: Any,
    our_notetype_name: str,
    is_single_card: Callable[[Any], bool],
) -> None:
    """Register the override. ``is_single_card`` reads a note, and may raise."""

    def handler() -> None:
        # Qt calls this with the main window focused, so anything that goes wrong
        # must end in Anki's own behaviour rather than a dead key.
        try:
            reviewer = mw.reviewer
            card = reviewer.card if reviewer is not None else None
            note = card.note() if card is not None else None
            notetype = note.note_type() if note is not None else None
            intercept = should_intercept(
                main_state=mw.state,
                reviewer_state=reviewer.state,
                notetype_name=(notetype or {}).get("name"),
                our_notetype_name=our_notetype_name,
                single_card_mode=is_single_card(note),
            )
        except Exception:
            intercept = False
        if not intercept:
            mw.reviewer.onEnterKey()
            return
        # advance() reports whether there was a cycle to advance, and the
        # answer is only knowable in the page -- a FINISHED cycle has none, and
        # its Space must reach Anki or the card can never be answered. So the
        # result is read back and the fall-through happens in the callback.
        # aqt's own reviewer uses evalWithCallback the same way for
        # getTypedAnswer(), and it drops late callbacks after teardown.
        def resume(advanced: Any) -> None:
            if not advanced:
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
        shortcuts.extend((key, handler) for key in _KEYS)

    gui_hooks.state_shortcuts_will_change.append(on_shortcuts)
