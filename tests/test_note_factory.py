from __future__ import annotations

import base64
import json

from randomized_occlusion.collection.note_factory import NoteFactory
from randomized_occlusion.domain.card_options import (
    CardMode,
    CardOptions,
    Direction,
    Interaction,
)
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


def _build(**kwargs):
    kwargs.setdefault("image_filename", "x.png")
    kwargs.setdefault("structures", _structures())
    return NoteFactory(DEFAULT_SPEC).build(**kwargs)


def _payload(content):
    return json.loads(base64.b64decode(content.fields["Structures"]).decode("utf-8"))


def test_build_populates_all_fields():
    content = _build(header="Heart", back_extra="see Gray's")
    assert content.notetype_name == DEFAULT_SPEC.name
    assert set(content.fields) == set(DEFAULT_SPEC.fields)
    assert content.fields["Header"] == "Heart"
    assert content.fields["Back Extra"] == "see Gray's"
    assert content.fields["Ordinals"] == "{{c1::Aorta}}{{c2::Vena cava}}"


def test_header_and_back_extra_pass_through_unmodified():
    content = _build(header="<b>H</b> & more", back_extra="line 1\nline 2")
    assert content.fields["Header"] == "<b>H</b> & more"
    assert content.fields["Back Extra"] == "line 1\nline 2"


def test_image_field_is_an_img_tag_with_escaped_filename():
    html = _build(image_filename='a"b&c.png').fields["Image"]
    assert html.startswith("<img src=") and html.endswith(">")
    assert "&quot;" in html and "&amp;" in html


def test_structures_field_is_a_self_describing_payload():
    structures = _structures()
    content = _build(structures=structures, options=CardOptions(direction=Direction.BOTH))
    payload = _payload(content)
    assert payload["direction"] == "both"
    assert StructureSet.from_json(json.dumps(payload["structures"])) == structures


def test_both_direction_doubles_the_cloze_ordinals():
    content = _build(options=CardOptions(direction=Direction.BOTH))
    assert (
        content.fields["Ordinals"]
        == "{{c1::Aorta}}{{c2::Aorta}}{{c3::Vena cava}}{{c4::Vena cava}}"
    )


def test_reverse_direction_is_stored_in_the_payload():
    content = _build(options=CardOptions(direction=Direction.REVERSE))
    assert _payload(content)["direction"] == "reverse"


def test_type_interaction_sets_the_type_answer_flag():
    assert _build().fields["TypeAnswer"] == ""
    typed = _build(options=CardOptions(interaction=Interaction.TYPE))
    assert typed.fields["TypeAnswer"] == "1"


def test_single_mode_makes_one_card_and_disables_native_type():
    content = _build(
        options=CardOptions(mode=CardMode.SINGLE, interaction=Interaction.TYPE)
    )
    assert content.fields["Ordinals"] == "{{c1::.}}"
    assert content.fields["TypeAnswer"] == ""  # single uses its own JS typer
    assert _payload(content)["mode"] == "single"


def test_context_labels_flag_is_stored_in_the_payload():
    content = _build(options=CardOptions(context_labels=True))
    assert _payload(content)["contextLabels"] is True
