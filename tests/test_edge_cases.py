"""Edge cases and a stress case for the note pipeline.

Deliberately nasty, specific inputs (as opposed to the randomized coverage in
``test_fuzz``): boundary coordinates, hostile labels, extremes, and malformed
stored data.
"""

from __future__ import annotations

import re

import pytest

from randomized_occlusion.collection.note_factory import NoteFactory
from randomized_occlusion.collection.note_reader import NoteReader
from randomized_occlusion.domain.card_options import CardOptions, Direction
from randomized_occlusion.domain.codec import encode_json_b64
from randomized_occlusion.domain.geometry import NormalizedPoint
from randomized_occlusion.domain.structure import Structure
from randomized_occlusion.domain.structure_set import StructureSet
from randomized_occlusion.notetype.spec import DEFAULT_SPEC


def _one(label: str) -> StructureSet:
    return StructureSet.from_unordered(
        [Structure(ordinal=1, target=NormalizedPoint(0.5, 0.5), label=label)]
    )


def _roundtrip_labels(labels: list[str], options: CardOptions | None = None):
    structures = StructureSet.from_unordered(
        [
            Structure(ordinal=1, target=NormalizedPoint(0.1 * i, 0.1 * i), label=label)
            for i, label in enumerate(labels)
        ]
    )
    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename="x.png",
        structures=structures,
        options=options or CardOptions(),
    )
    return NoteReader(DEFAULT_SPEC).read(content.fields).structures, structures


# ---- hostile labels ----------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "{{c1::injected}}",
        "}}::{{",
        "a::b::c",
        "</script><script>alert(1)</script>",
        '"; DROP TABLE notes; --',
        "emoji 🧠🫀 and RTL ‮مرحبا",
        "line1\nline2\ttabbed",
        "   surrounded by spaces   ",
        "\\backslashes\\and/slashes/",
        "Ω→中文" * 3,
    ],
)
def test_hostile_labels_survive_the_roundtrip(label: str) -> None:
    loaded, original = _roundtrip_labels([label])
    assert loaded == original
    assert loaded.ordered[0].label == label


def test_very_long_label_roundtrips() -> None:
    label = "brachiocephalic " * 1000  # ~16k chars
    loaded, original = _roundtrip_labels([label])
    assert loaded == original
    assert loaded.ordered[0].label == label


def test_label_of_only_cloze_metacharacters_is_neutralised_in_cloze() -> None:
    field = _one("{{::}}").cloze_field(CardOptions(direction=Direction.FORWARD))
    answer = re.findall(r"\{\{c\d+::(.*?)\}\}", field, flags=re.DOTALL)[0]
    assert "{{" not in answer and "}}" not in answer and "::" not in answer
    assert answer.strip()  # never collapses to an empty cloze answer


# ---- coordinate boundaries ---------------------------------------------------


@pytest.mark.parametrize("value", [0.0, 1.0, 0.5])
def test_normalized_point_accepts_unit_interval(value: float) -> None:
    assert NormalizedPoint(value, value).to_dict() == {"x": value, "y": value}


@pytest.mark.parametrize("bad", [-1e-9, 1.0000001, 2.0, -5.0])
def test_normalized_point_rejects_out_of_range(bad: float) -> None:
    with pytest.raises(ValueError):
        NormalizedPoint(bad, 0.5)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_normalized_point_rejects_non_finite(bad: float) -> None:
    with pytest.raises(ValueError):
        NormalizedPoint(bad, 0.5)


# ---- structure-set invariants ------------------------------------------------


def test_structure_set_rejects_non_contiguous_ordinals() -> None:
    with pytest.raises(ValueError):
        StructureSet.from_dicts(
            [
                {"ord": 1, "x": 0.1, "y": 0.1, "label": "a"},
                {"ord": 3, "x": 0.2, "y": 0.2, "label": "b"},  # gap: no 2
            ]
        )


def test_structure_set_rejects_empty() -> None:
    with pytest.raises(ValueError):
        StructureSet.from_unordered([])


def test_single_structure_both_direction_makes_two_clozes() -> None:
    field = _one("Aorta").cloze_field(CardOptions(direction=Direction.BOTH))
    assert field == "{{c1::Aorta}}{{c2::Aorta}}"


# ---- stress ------------------------------------------------------------------


def test_five_hundred_structures_roundtrip() -> None:
    structures = StructureSet.from_unordered(
        [
            Structure(
                ordinal=1,
                target=NormalizedPoint(round((i % 100) / 100, 2), round((i // 100) / 100, 2)),
                label=f"structure-{i}",
            )
            for i in range(500)
        ]
    )
    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename="big.png",
        structures=structures,
        options=CardOptions(direction=Direction.BOTH),
    )
    # 500 markers, both directions -> 1000 generated cards.
    assert content.fields["Ordinals"].count("{{c") == 1000
    # The base64 payload never contains injection characters, however large.
    assert re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", content.fields["Structures"])
    loaded = NoteReader(DEFAULT_SPEC).read(content.fields)
    assert loaded.structures == structures


# ---- malformed stored data surfaces as an error ------------------------------


@pytest.mark.parametrize(
    "payload_obj",
    [
        {"v": 2},  # no structures key
        "just a string",
        42,
        {"v": 2, "structures": "not a list"},
    ],
)
def test_reader_rejects_structurally_invalid_payloads(payload_obj: object) -> None:
    fields = {
        "Image": '<img src="x.png">',
        "Structures": encode_json_b64(payload_obj),
        "Ordinals": "",
        "Header": "",
        "Back Extra": "",
        "TypeAnswer": "",
    }
    with pytest.raises(ValueError):
        NoteReader(DEFAULT_SPEC).read(fields)
