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
from randomized_occlusion.domain.structure_set import MAX_ORDINAL, StructureSet


def _s(ordinal, label, x=0.5, y=0.5):
    return Structure(ordinal=ordinal, target=NormalizedPoint(x, y), label=label)


def _decode_payload(b64):
    return json.loads(base64.b64decode(b64).decode("utf-8"))


def _decode_structures(b64):
    return StructureSet.from_json(json.dumps(_decode_payload(b64)["structures"]))


def test_requires_at_least_one_structure():
    with pytest.raises(ValueError):
        StructureSet(structures=())


def test_accepts_ordinal_gaps():
    # A gap is what an edit that deleted a structure leaves behind, and it is
    # what KEEPS every surviving card testing the structure it always tested.
    # Renumbering the survivors instead moved each later card's review history
    # onto a different structure.
    kept = StructureSet(structures=(_s(1, "a"), _s(3, "c")))
    assert [s.ordinal for s in kept.ordered] == [1, 3]
    assert kept.cloze_field(CardOptions()) == "{{c1::a}}{{c3::c}}"


def test_rejects_ordinals_outside_ankis_range():
    # A cloze number past a 32-bit ordinal cannot address a card at all, and
    # with contiguity gone this is what stops a hand-edited payload asking.
    # 500 is Anki's own ceiling: it clamps any higher cloze number to 500, so
    # two structures past it would generate the SAME card and the rest would
    # render "No cloze 500 found". Verified against anki 26.09.2 -- c499 gives
    # card ord 498, but c501 and c2000 both give 499.
    assert MAX_ORDINAL == 500
    for bad in (0, -1, MAX_ORDINAL + 1):
        with pytest.raises(ValueError):
            StructureSet(structures=(_s(bad, "a"),))
    assert StructureSet(structures=(_s(MAX_ORDINAL, "a"),)).ordered[0].ordinal == (
        MAX_ORDINAL
    )


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


def test_a_label_cannot_inject_markup_into_the_card():
    # The Ordinals field is rendered as HTML, immediately before the <script>
    # tags carrying the payload. An unescaped "<style>" made the tokeniser
    # swallow everything up to the next closing tag, so #ro-data never became an
    # element and EVERY OTHER card of the note drew a bare image -- no prompt, no
    # arrow, no answer, and no error anywhere.
    for hostile in ("<style>", "</div>", "<script>alert(1)</script>", "<!--"):
        field = StructureSet.from_unordered([_s(1, hostile)]).cloze_field(CardOptions())
        assert "<" not in field and ">" not in field, (
            f"{hostile!r} reached the card as markup: {field!r}"
        )


def test_an_ampersand_in_a_label_is_escaped_once():
    # `&` has to be escaped FIRST or the entities the escape itself introduces
    # would be escaped in turn, and the learner would be graded against
    # "&amp;lt;" rather than "<".
    field = StructureSet.from_unordered([_s(1, "S&P <500>")]).cloze_field(CardOptions())
    assert field == "{{c1::S&amp;P &lt;500&gt;}}"


def test_a_label_ending_in_a_brace_keeps_its_last_character():
    # "gene {TP53}" + the wrapper's own "}}" gives "...TP53}}}", and Anki reads
    # the FIRST two as the closing delimiter: the answer became "gene {TP53" and
    # the native type box marked the displayed answer wrong, forever. A numeric
    # entity keeps them apart; rslib decodes it before comparing.
    field = StructureSet.from_unordered([_s(1, "gene {TP53}")]).cloze_field(CardOptions())
    assert field == "{{c1::gene {TP53&#125;}}"
    assert not field.endswith("}}}"), "the answer still runs into the delimiter"


def test_deleting_a_structure_leaves_every_other_card_where_it_was():
    # The whole point. An ordinal IS an Anki card -- its due date, its interval,
    # its lapses -- and col.update_note rewrites the field without touching the
    # card rows. Renumbering the survivors therefore handed card 2's six months
    # of review to what used to be structure 3, silently, with nothing visible
    # in the UI. Plain Anki does not do this: deleting {{c2::...}} by hand
    # leaves c1/c3/c4/c5 exactly as they were.
    names = ["Aorta", "Pulmonary trunk", "SVC", "IVC", "Left atrium"]
    before = StructureSet.from_unordered([_s(1, n) for n in names])
    assert before.cloze_field(CardOptions()) == (
        "{{c1::Aorta}}{{c2::Pulmonary trunk}}{{c3::SVC}}{{c4::IVC}}{{c5::Left atrium}}"
    )

    # The editor hands back the survivors, each still carrying its own ordinal.
    survivors = [(s.ordinal, s) for s in before.ordered if s.label != "Pulmonary trunk"]
    after = StructureSet.keeping_ordinals(survivors)

    assert after.cloze_field(CardOptions()) == (
        "{{c1::Aorta}}{{c3::SVC}}{{c4::IVC}}{{c5::Left atrium}}"
    )
    kept = {s.ordinal: s.label for s in after.ordered}
    for structure in before.ordered:
        if structure.label == "Pulmonary trunk":
            assert structure.ordinal not in kept, "the freed ordinal was reused"
        else:
            assert kept[structure.ordinal] == structure.label, (
                f"c{structure.ordinal} now tests {kept[structure.ordinal]!r}, "
                f"not {structure.label!r}"
            )


@pytest.mark.parametrize("deleted", ["a", "b", "c"])
def test_a_structure_added_after_a_deletion_never_reuses_the_freed_ordinal(deleted: str):
    # Reusing it would hand the new structure the deleted one's card, and with
    # it a review history that belongs to something else entirely.
    #
    # Every position is exercised, because deleting the HIGHEST one is the case
    # `max(surviving) + 1` gets wrong: that maximum drops back the moment the
    # top structure goes, so the freed number is handed straight out again.
    before = StructureSet.from_unordered([_s(1, "a"), _s(1, "b"), _s(1, "c")])
    freed = {s.ordinal for s in before.ordered if s.label == deleted}
    survivors = [(s.ordinal, s) for s in before.ordered if s.label != deleted]
    with_new = StructureSet.keeping_ordinals(
        [*survivors, (None, _s(1, "d"))], next_ordinal=before.next_ordinal
    )

    new_ordinal = next(s.ordinal for s in with_new.ordered if s.label == "d")
    assert new_ordinal not in freed, (
        f"deleting {deleted!r} freed c{freed} and the new structure took it"
    )
    for structure in before.ordered:
        if structure.label == deleted:
            continue
        kept = {s.ordinal: s.label for s in with_new.ordered}
        assert kept[structure.ordinal] == structure.label


def test_too_many_structures_is_refused_with_a_message_a_user_can_act_on():
    # An older version of this add-on had no upper bound, so a note with 600
    # structures could be saved. Enumerating them produced a ~3,000-character
    # dialog that named neither the limit's reason nor any remedy -- and since
    # this editor is the only thing that could REMOVE structures, such a note
    # was unrecoverable through the UI.
    many = [_s(i, f"s{i}") for i in range(1, MAX_ORDINAL + 101)]
    with pytest.raises(ValueError) as caught:
        StructureSet(structures=tuple(many))

    message = str(caught.value)
    assert len(message) < 300, f"{len(message)}-character dialog: {message[:120]}..."
    assert str(len(many)) in message, "does not say how many structures there are"
    assert str(MAX_ORDINAL) in message, "does not say what the limit is"
    assert "editor" in message, "does not say what to do about it"


def test_a_long_ordinal_list_is_summarised_rather_than_enumerated():
    dupes = [_s(1, "a")] + [_s(i, f"s{i}") for i in range(1, 60)]
    with pytest.raises(ValueError) as caught:
        StructureSet(structures=tuple(dupes))
    message = str(caught.value)
    assert "more]" in message, f"the whole list was printed: {message[:120]}..."
    assert len(message) < 200, len(message)


def test_a_high_water_mark_past_the_ceiling_is_clamped_not_obeyed():
    # Reachable by corruption, or legitimately by ~499 add-then-delete cycles on
    # one note, since the mark only ever goes up. Left alone it is read, written
    # straight back, and then refuses every new structure for ever -- on a note
    # that may hold only two.
    poisoned = StructureSet(structures=(_s(1, "a"), _s(2, "b")), next_ordinal=9999)
    assert poisoned.next_ordinal == 3, "the nonsense mark was carried"

    grown = StructureSet.keeping_ordinals(
        [*[(s.ordinal, s) for s in poisoned.ordered], (None, _s(1, "new"))],
        next_ordinal=poisoned.next_ordinal,
    )
    assert [s.ordinal for s in grown.ordered] == [1, 2, 3]
    assert grown.ordered[-1].label == "new"


def test_the_high_water_mark_survives_a_save_and_reload():
    # It rides in the payload, because the survivors alone cannot express it:
    # after deleting the top structure they look exactly like a note that never
    # had one.
    from randomized_occlusion.domain.codec import decode_json_b64

    before = StructureSet.from_unordered([_s(1, "a"), _s(1, "b"), _s(1, "c")])
    survivors = [(s.ordinal, s) for s in before.ordered if s.label != "c"]
    after = StructureSet.keeping_ordinals(survivors, next_ordinal=before.next_ordinal)
    assert after.next_ordinal == 4, "the mark dropped back with the deletion"

    payload = decode_json_b64(after.to_payload_base64(CardOptions()))
    assert payload["nextOrd"] == 4
    reloaded = StructureSet.from_dicts(
        payload["structures"], next_ordinal=payload["nextOrd"]
    )
    added = StructureSet.keeping_ordinals(
        [*[(s.ordinal, s) for s in reloaded.ordered], (None, _s(1, "d"))],
        next_ordinal=reloaded.next_ordinal,
    )
    assert next(s.ordinal for s in added.ordered if s.label == "d") == 4


def test_a_legacy_note_without_a_mark_starts_after_its_highest_ordinal():
    # Nothing has been deleted from it yet, so its maximum IS the high-water
    # mark and no ordinal is at risk of being reused.
    legacy = StructureSet.from_dicts(
        [
            {"ord": 1, "x": 0.1, "y": 0.1, "label": "a"},
            {"ord": 5, "x": 0.2, "y": 0.2, "label": "b"},
        ]
    )
    assert legacy.next_ordinal == 6


def test_keeping_ordinals_numbers_a_brand_new_note_from_one():
    fresh = StructureSet.keeping_ordinals([(None, _s(1, "a")), (None, _s(1, "b"))])
    assert [s.ordinal for s in fresh.ordered] == [1, 2]


def test_keeping_ordinals_rejects_two_structures_claiming_one_card():
    with pytest.raises(ValueError):
        StructureSet.keeping_ordinals([(2, _s(1, "a")), (2, _s(1, "b"))])


def test_cloze_field_is_the_same_for_every_direction():
    # Every direction (forward / reverse / both) generates one card per
    # structure. Direction is applied by the RENDERER (a fresh random pick each
    # review for "both", issue #5), not by the cloze grammar. Pin that.
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


def test_ordered_sorts_by_ordinal_not_by_insertion():
    out_of_order = StructureSet(
        structures=(_s(2, "second"), _s(3, "third"), _s(1, "first"))
    )
    assert [s.ordinal for s in out_of_order.ordered] == [1, 2, 3]
    assert [s.label for s in out_of_order.ordered] == ["first", "second", "third"]


def test_the_payload_declares_version_2():
    # The reviewer branches on `v` to tell a v2 envelope from a v1 bare array.
    # A wrong version sends every note down the legacy path.
    structures = StructureSet(structures=(_s(1, "one"), _s(2, "two")))
    assert _decode_payload(structures.to_payload_base64(CardOptions()))["v"] == 2


def test_a_mark_one_past_the_ceiling_is_not_mistaken_for_a_full_note():
    # MAX_ORDINAL + 1 is the legitimate "nothing left to hand out" mark for a
    # note that really is full, which is why the clamp cannot simply reject it.
    # An off-by-one therefore kept it on a note with room to spare, and that
    # note then refused every new structure for good -- exactly the failure the
    # clamp exists to prevent, alive for one value.
    roomy = StructureSet(
        structures=(_s(1, "a"), _s(2, "b")), next_ordinal=MAX_ORDINAL + 1
    )
    assert roomy.next_ordinal == 3, "a two-structure note was told it was full"

    full = StructureSet(
        structures=tuple(_s(n, f"s{n}") for n in range(1, MAX_ORDINAL + 1)),
        next_ordinal=MAX_ORDINAL + 1,
    )
    assert full.next_ordinal == MAX_ORDINAL + 1, "a full note may keep its mark"
