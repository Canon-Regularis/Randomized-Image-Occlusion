from __future__ import annotations

import base64
import json

import pytest

from randomized_occlusion.domain.card_options import (
    CardMode,
    CardOptions,
    Direction,
    Interaction,
)
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


def test_cloze_field_is_the_same_for_every_direction():
    # Every direction (forward / reverse / both) generates one card per
    # structure; direction is applied by the RENDERER — a fresh random pick each
    # review for "both" (issue #5) — not by the cloze grammar. Pin that.
    s = StructureSet.from_unordered([_s(1, "a"), _s(1, "b")])
    forward = s.cloze_field(CardOptions(direction=Direction.FORWARD))
    assert forward == "{{c1::a}}{{c2::b}}"
    assert s.cloze_field(CardOptions(direction=Direction.REVERSE)) == forward
    assert s.cloze_field(CardOptions(direction=Direction.BOTH)) == forward


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
        s.to_payload_base64(
            CardOptions(
                direction=Direction.REVERSE,
                mode=CardMode.SINGLE,
                interaction=Interaction.TYPE,
            )
        )
    )
    assert payload["direction"] == "reverse"
    assert payload["mode"] == "single"
    assert payload["interaction"] == "type"
    assert payload["structures"][0] == {"ord": 1, "x": 0.1, "y": 0.2, "label": "a"}


def test_payload_serialises_enums_as_plain_strings():
    # Byte-parity guardrail: StrEnum must not leak "Direction.FORWARD" into JSON.
    s = StructureSet.from_unordered([_s(1, "a")])
    for direction in Direction:
        for mode in CardMode:
            for interaction in Interaction:
                raw = base64.b64decode(
                    s.to_payload_base64(
                        CardOptions(direction=direction, mode=mode, interaction=interaction)
                    )
                ).decode("utf-8")
                assert f'"direction":"{direction.value}"' in raw
                assert f'"mode":"{mode.value}"' in raw
                assert f'"interaction":"{interaction.value}"' in raw
                assert (
                    "Direction." not in raw
                    and "CardMode." not in raw
                    and "Interaction." not in raw
                )


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
