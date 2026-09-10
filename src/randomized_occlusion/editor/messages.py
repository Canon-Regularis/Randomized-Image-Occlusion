"""User-facing wording that more than one part of the editor needs.

Qt-free, so the wording can be tested directly rather than only being seen when
a dialog happens to be open.
"""

from __future__ import annotations

__all__ = ["count_phrase", "replace_image_prompt"]


def count_phrase(count: int, noun: str) -> str:
    """``1 marker`` / ``2 markers``: the plural rule, written once."""
    return f"{count} {noun}{'' if count == 1 else 's'}"


def replace_image_prompt(marker_count: int) -> str | None:
    """What to ask before replacing the image, or ``None`` if nothing is lost.

    Replacing the picture clears every marker and the dialog has no undo, so a
    stray Ctrl+V would otherwise discard the whole labelling silently.
    """
    if marker_count <= 0:
        return None
    return (
        f"Replace the image? The {count_phrase(marker_count, 'marker')} "
        "you have placed will be removed."
    )
