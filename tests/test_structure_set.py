from __future__ import annotations

import base64
import json

import pytest

from randomized_occlusion.domain.card_options import CardMode, CardOptions, Direction
from randomized_occlusion.domain.geometry import NormalizedPoint
from randomized_occlusion.domain.structure import Structure
from randomized_occlusion.domain.structure_set import StructureSet


def _s(ordinal, label, x=0.5, y=0.5):
    return Structure(ordinal=ordinal, target=NormalizedPoint(x, y), label=label)


def _decode_payload(b64):
    return json.loads(base64.b64decode(b64).decode("utf-8"))


def _decode_structures(b64):
    return StructureSet.from_json(json.dumps(_decode_payload(b64)["structures"]))


def test_requires_at_least_one_structure():
    with pytest.raises(ValueError):
        StructureSet(structures=())


def test_rejects_ordinal_gaps():
    with pytest.raises(ValueError):
        StructureSet(structures=(_s(1, "a"), _s(3, "c")))


def test_rejects_duplicate_ordinals():
    with pytest.raises(ValueError):
        StructureSet(structures=(_s(1, "a"), _s(1, "b")))


def test_from_unordered_assigns_contiguous_ordinals():
    s = StructureSet.from_unordered([_s(99, "a"), _s(7, "b"), _s(3, "c")])
    assert [x.ordinal for x in s.ordered] == [1, 2, 3]
    assert [x.label for x in s.ordered] == ["a", "b", "c"]


def test_cloze_field_uses_labels_as_answers():
    s = StructureSet.from_unordered([_s(1, "Aorta"), _s(1, "Vena cava")])
    assert s.cloze_field(CardOptions()) == "{{c1::Aorta}}{{c2::Vena cava}}"


def test_cloze_field_escapes_metacharacters():
    s = StructureSet.from_unordered([_s(1, "a::b}}c")])
    assert s.cloze_field(CardOptions()) == "{{c1::a:b}c}}"


def test_cloze_field_both_direction_doubles_ordinals():
    s = StructureSet.from_unordered([_s(1, "a"), _s(1, "b")])
    both = s.cloze_field(CardOptions(direction=Direction.BOTH))
    assert both == "{{c1::a}}{{c2::a}}{{c3::b}}{{c4::b}}"


def test_cloze_field_reverse_matches_forward():
    # Reverse cards use the same clozes as forward (direction is applied by the
    # renderer, not the cloze grammar); pin that intentional equivalence.
    s = StructureSet.from_unordered([_s(1, "a"), _s(1, "b")])
    assert s.cloze_field(CardOptions(direction=Direction.REVERSE)) == s.cloze_field(
        CardOptions(direction=Direction.FORWARD)
    )


def test_single_mode_emits_exactly_one_cloze():
    s = StructureSet.from_unordered([_s(1, "a"), _s(1, "b"), _s(1, "c")])
    assert s.cloze_field(CardOptions(mode=CardMode.SINGLE)) == "{{c1::.}}"
    # ...even under "both", single mode collapses to one card.
    assert (
        s.cloze_field(CardOptions(direction=Direction.BOTH, mode=CardMode.SINGLE))
        == "{{c1::.}}"
    )


def test_payload_carries_options_and_structures():
    s = StructureSet.from_unordered([_s(1, "a", x=0.1, y=0.2)])
    payload = _decode_payload(
        s.to_payload_base64(CardOptions(direction=Direction.REVERSE, mode=CardMode.SINGLE))
    )
    assert payload["direction"] == "reverse"
    assert payload["mode"] == "single"
    assert payload["structures"][0] == {"ord": 1, "x": 0.1, "y": 0.2, "label": "a"}


def test_payload_serialises_enums_as_plain_strings():
    # Byte-parity guardrail: StrEnum must not leak "Direction.FORWARD" into JSON.
    s = StructureSet.from_unordered([_s(1, "a")])
    for direction in Direction:
        for mode in CardMode:
            raw = base64.b64decode(
                s.to_payload_base64(CardOptions(direction=direction, mode=mode))
            ).decode("utf-8")
            assert f'"direction":"{direction.value}"' in raw
            assert f'"mode":"{mode.value}"' in raw
            assert "Direction." not in raw and "CardMode." not in raw


def test_payload_roundtrip_preserves_unicode_labels():
    original = StructureSet.from_unordered(
        [_s(1, "Aorta"), _s(2, "Schlüsselbein"), _s(3, "上腕骨")]
    )
    assert _decode_structures(original.to_payload_base64(CardOptions())) == original


def test_payload_is_ascii_and_html_safe():
    s = StructureSet.from_unordered([_s(1, "<script>alert(1)</script>")])
    payload = s.to_payload_base64(CardOptions())
    assert payload.isascii()
    assert "<" not in payload and ">" not in payload
    assert _decode_structures(payload) == s
