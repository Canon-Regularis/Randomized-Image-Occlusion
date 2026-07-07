from __future__ import annotations

import pytest

from randomized_occlusion.collection.note_factory import NoteFactory
from randomized_occlusion.collection.note_reader import NoteReader, note_fields
from randomized_occlusion.domain.card_options import (
    CardMode,
    CardOptions,
    Direction,
    Interaction,
)
from randomized_occlusion.domain.codec import decode_json_b64, encode_json_b64
from randomized_occlusion.domain.geometry import NormalizedPoint
from randomized_occlusion.domain.structure import Structure
from randomized_occlusion.domain.structure_set import StructureSet
from randomized_occlusion.notetype.spec import DEFAULT_SPEC


def _structures() -> StructureSet:
    return StructureSet.from_unordered(
        [
            Structure(ordinal=1, target=NormalizedPoint(0.2, 0.3), label="Aorta"),
            Structure(ordinal=2, target=NormalizedPoint(0.6, 0.7), label="Vena cava"),
        ]
    )


def _roundtrip(
    options: CardOptions,
    *,
    image: str = "x.png",
    header: str = "",
    back_extra: str = "",
    structures: StructureSet | None = None,
):
    """Build a note with the factory, then read it back with the reader."""
    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename=image,
        structures=structures or _structures(),
        options=options,
        header=header,
        back_extra=back_extra,
    )
    return NoteReader(DEFAULT_SPEC).read(content.fields)


# -- note_fields: the one place that reaches into Anki's note-dict API ---------


class _FakeNote:
    """Duck-types just enough of an Anki note for ``note_fields``."""

    def __init__(self, fields: dict[str, str]) -> None:
        self._fields = fields

    def note_type(self) -> dict:
        return {"flds": [{"name": name} for name in self._fields]}

    def __getitem__(self, name: str) -> str:
        return self._fields[name]


def test_note_fields_reads_every_field_by_name():
    fields = {"Image": "<img src=x.png>", "Header": "Heart", "Ordinals": ""}
    assert note_fields(_FakeNote(fields)) == fields


# -- the core guarantee: reader is the exact inverse of the factory ------------


def test_structures_survive_the_round_trip_exactly():
    loaded = _roundtrip(CardOptions())
    assert loaded.structures == _structures()


def test_header_and_back_extra_survive_the_round_trip():
    loaded = _roundtrip(CardOptions(), header="Heart", back_extra="see Gray's")
    assert loaded.header == "Heart"
    assert loaded.back_extra == "see Gray's"


def test_image_filename_is_recovered_and_unescaped():
    loaded = _roundtrip(CardOptions(), image='a"b&c.png')
    assert loaded.image_filename == 'a"b&c.png'


def test_default_options_round_trip():
    loaded = _roundtrip(CardOptions())
    assert loaded.options == CardOptions(
        direction=Direction.FORWARD,
        interaction=Interaction.REVEAL,
        context_labels=False,
        mode=CardMode.MULTI,
    )


def test_type_interaction_round_trips():
    loaded = _roundtrip(CardOptions(interaction=Interaction.TYPE))
    assert loaded.options.interaction == Interaction.TYPE


def test_reverse_direction_round_trips():
    loaded = _roundtrip(CardOptions(direction=Direction.REVERSE))
    assert loaded.options.direction == Direction.REVERSE


def test_both_direction_round_trips_without_altering_the_structures():
    loaded = _roundtrip(CardOptions(direction=Direction.BOTH))
    assert loaded.options.direction == Direction.BOTH
    # The payload stores one entry per marker, so editing sees the original
    # structures unchanged regardless of direction.
    assert loaded.structures == _structures()


def test_context_labels_round_trip():
    loaded = _roundtrip(CardOptions(context_labels=True))
    assert loaded.options.context_labels is True


def test_single_mode_round_trips_its_interaction():
    # Single mode carries the interaction in the payload, so type-vs-reveal now
    # round-trips faithfully (it used to always read back as REVEAL).
    typed = _roundtrip(CardOptions(mode=CardMode.SINGLE, interaction=Interaction.TYPE))
    assert typed.options.mode == CardMode.SINGLE
    assert typed.options.interaction == Interaction.TYPE
    revealed = _roundtrip(CardOptions(mode=CardMode.SINGLE, interaction=Interaction.REVEAL))
    assert revealed.options.interaction == Interaction.REVEAL


# -- legacy and malformed data -------------------------------------------------


def test_reads_legacy_v1_bare_array_payload():
    # Notes created before per-note settings stored a bare structures array.
    v1_payload = encode_json_b64([s.to_dict() for s in _structures().ordered])
    fields = {
        "Image": '<img src="x.png">',
        "Structures": v1_payload,
        "Ordinals": "",
        "Header": "",
        "Back Extra": "",
        "TypeAnswer": "",
    }
    loaded = NoteReader(DEFAULT_SPEC).read(fields)
    assert loaded.structures == _structures()
    assert loaded.options == CardOptions()  # multi / forward / reveal / no context


def test_legacy_v2_single_without_interaction_reads_as_type():
    # A single note whose v2 payload predates the "interaction" key must read back
    # as TYPE (render.js defaults such notes to type), so a plain edit + save can't
    # silently flip it to reveal.
    payload = encode_json_b64(
        {
            "v": 2,
            "mode": "single",
            "direction": "forward",
            "structures": [s.to_dict() for s in _structures().ordered],
        }
    )
    loaded = NoteReader(DEFAULT_SPEC).read({"Structures": payload, "TypeAnswer": ""})
    assert loaded.options.mode == CardMode.SINGLE
    assert loaded.options.interaction == Interaction.TYPE


def test_legacy_v2_multi_without_interaction_uses_the_type_flag_field():
    # A legacy multi note without the payload key still derives type/reveal from
    # the TypeAnswer field, exactly as before the payload carried interaction.
    payload = encode_json_b64(
        {
            "v": 2,
            "mode": "multi",
            "direction": "forward",
            "structures": [s.to_dict() for s in _structures().ordered],
        }
    )
    typed = NoteReader(DEFAULT_SPEC).read({"Structures": payload, "TypeAnswer": "1"})
    assert typed.options.interaction == Interaction.TYPE
    revealed = NoteReader(DEFAULT_SPEC).read({"Structures": payload, "TypeAnswer": ""})
    assert revealed.options.interaction == Interaction.REVEAL


def test_legacy_payload_context_labels_falls_back_to_the_supplied_default():
    # A payload predating the contextLabels key (v1 array, or a v2 note from
    # before the key) has no stored value. render.js renders such notes using the
    # GLOBAL config, so the reader must mirror that via context_labels_default —
    # otherwise editing + saving would bake in a literal False and silently
    # suppress the context labels the note currently shows.
    v1_payload = encode_json_b64([s.to_dict() for s in _structures().ordered])
    v2_no_ctx = encode_json_b64(
        {
            "v": 2,
            "mode": "multi",
            "direction": "forward",
            "interaction": "reveal",
            "structures": [s.to_dict() for s in _structures().ordered],
        }
    )
    for payload in (v1_payload, v2_no_ctx):
        fields = {"Structures": payload, "TypeAnswer": ""}
        on = NoteReader(DEFAULT_SPEC).read(fields, context_labels_default=True)
        off = NoteReader(DEFAULT_SPEC).read(fields, context_labels_default=False)
        assert on.options.context_labels is True
        assert off.options.context_labels is False
    # Default is False when the caller supplies nothing (back-compat).
    assert NoteReader(DEFAULT_SPEC).read(
        {"Structures": v1_payload, "TypeAnswer": ""}
    ).options.context_labels is False


def test_explicit_context_labels_ignores_the_default():
    # A v2 payload that DID store the key must use the stored value, not the
    # fallback — so a user who turned context labels off keeps them off even if
    # the global config default is on.
    payload = encode_json_b64(
        {
            "v": 2,
            "mode": "multi",
            "direction": "forward",
            "interaction": "reveal",
            "contextLabels": False,
            "structures": [s.to_dict() for s in _structures().ordered],
        }
    )
    loaded = NoteReader(DEFAULT_SPEC).read(
        {"Structures": payload, "TypeAnswer": ""}, context_labels_default=True
    )
    assert loaded.options.context_labels is False


def test_missing_structures_field_raises():
    fields = {"Image": '<img src="x.png">', "Structures": ""}
    with pytest.raises(ValueError, match="no stored structures"):
        NoteReader(DEFAULT_SPEC).read(fields)


def test_malformed_payload_raises():
    fields = {"Image": "", "Structures": "not base64 @@@"}
    with pytest.raises(ValueError, match="could not be decoded"):
        NoteReader(DEFAULT_SPEC).read(fields)


def test_absent_image_is_empty_string_not_an_error():
    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename="x.png", structures=_structures()
    )
    fields = dict(content.fields)
    fields["Image"] = ""  # simulate a note whose image was cleared
    loaded = NoteReader(DEFAULT_SPEC).read(fields)
    assert loaded.image_filename == ""


# -- the underlying serialization primitives -----------------------------------


def test_codec_round_trips_arbitrary_json():
    obj = {"v": 2, "s": "café", "nums": [1, 2, 3], "flag": True}
    assert decode_json_b64(encode_json_b64(obj)) == obj


def test_structure_set_from_dicts_matches_from_json():
    dicts = [s.to_dict() for s in _structures().ordered]
    from_dicts = StructureSet.from_dicts(dicts)
    assert from_dicts == _structures()
