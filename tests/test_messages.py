from __future__ import annotations

from randomized_occlusion.editor.messages import count_phrase, replace_image_prompt


def test_count_phrase_is_singular_for_one():
    assert count_phrase(1, "marker") == "1 marker"
    assert count_phrase(1, "card") == "1 card"


def test_count_phrase_is_plural_otherwise():
    assert count_phrase(0, "marker") == "0 markers"
    assert count_phrase(2, "card") == "2 cards"
    assert count_phrase(17, "marker") == "17 markers"


def test_replace_prompt_is_none_without_markers():
    assert replace_image_prompt(0) is None
    assert replace_image_prompt(-1) is None


def test_replace_prompt_reports_the_marker_count():
    assert replace_image_prompt(1) == (
        "Replace the image? The 1 marker you have placed will be removed."
    )
    assert replace_image_prompt(3) == (
        "Replace the image? The 3 markers you have placed will be removed."
    )
