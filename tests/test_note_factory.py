from __future__ import annotations

from randomized_occlusion.collection.note_factory import NoteFactory
from randomized_occlusion.domain.geometry import NormalizedPoint
from randomized_occlusion.domain.structure import Structure
from randomized_occlusion.domain.structure_set import StructureSet
from randomized_occlusion.notetype.spec import DEFAULT_SPEC


def _structures():
    return StructureSet.from_unordered(
        [
            Structure(ordinal=1, target=NormalizedPoint(0.2, 0.3), label="Aorta"),
            Structure(ordinal=2, target=NormalizedPoint(0.6, 0.7), label="Vena cava"),
        ]
    )


def test_build_populates_all_fields():
    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename="heart.png",
        structures=_structures(),
        deck_name="Anatomy",
        header="Heart",
        back_extra="see Gray's",
    )
    assert content.notetype_name == DEFAULT_SPEC.name
    assert content.deck_name == "Anatomy"
    assert set(content.fields) == set(DEFAULT_SPEC.fields)
    assert content.fields["Header"] == "Heart"
    assert content.fields["Back Extra"] == "see Gray's"
    assert content.fields["Ordinals"] == "{{c1::Aorta}}{{c2::Vena cava}}"


def test_image_field_is_an_img_tag_with_escaped_filename():
    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename='a"b&c.png',
        structures=_structures(),
        deck_name="d",
    )
    html = content.fields["Image"]
    assert html.startswith("<img src=") and html.endswith(">")
    assert "&quot;" in html and "&amp;" in html


def test_structures_field_is_a_self_describing_payload():
    import base64
    import json

    structures = _structures()
    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename="x.png", structures=structures, deck_name="d", direction="both"
    )
    payload = json.loads(base64.b64decode(content.fields["Structures"]).decode("utf-8"))
    assert payload["direction"] == "both"
    restored = StructureSet.from_json(json.dumps(payload["structures"]))
    assert restored == structures


def test_both_direction_doubles_the_cloze_ordinals():
    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename="x.png", structures=_structures(), deck_name="d", direction="both"
    )
    assert (
        content.fields["Ordinals"]
        == "{{c1::Aorta}}{{c2::Aorta}}{{c3::Vena cava}}{{c4::Vena cava}}"
    )
