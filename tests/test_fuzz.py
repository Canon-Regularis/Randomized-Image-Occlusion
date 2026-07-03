"""Property/fuzz tests: hammer the core invariants with randomized inputs.

Randomness is seeded (``random.Random(seed)``) so every failure is reproducible
from the ``seed`` shown in the parametrization — no flakiness, but broad coverage
of label/option/coordinate combinations a hand-written case would miss.
"""

from __future__ import annotations

import random
import re
import string

import pytest

from randomized_occlusion.collection.note_factory import NoteFactory
from randomized_occlusion.collection.note_reader import NoteReader
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

# A deliberately nasty alphabet: cloze metacharacters, HTML, quotes, JSON
# specials, whitespace, and non-ASCII — everything that could break escaping,
# the base64/JSON payload, or the cloze field.
_LABEL_CHARS = (
    string.ascii_letters
    + string.digits
    + " -_/().,;:{}[]&<>\"'`\n\t=+*|"
    + "áéíóúüñÇ中文日本語✓Ω→"
)
# Filenames avoid control chars (not realistic) but keep HTML-escape triggers.
_FILENAME_CHARS = string.ascii_letters + string.digits + " &\"'()-_."


def _nonblank(rng: random.Random, alphabet: str, max_len: int) -> str:
    while True:
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, max_len)))
        if text.strip():
            return text


def _random_structures(rng: random.Random, count: int | None = None) -> StructureSet:
    count = count if count is not None else rng.randint(1, 12)
    items = [
        Structure(
            ordinal=1,  # reassigned by from_unordered
            target=NormalizedPoint(round(rng.random(), 6), round(rng.random(), 6)),
            label=_nonblank(rng, _LABEL_CHARS, 40),
        )
        for _ in range(count)
    ]
    return StructureSet.from_unordered(items)


def _random_options(rng: random.Random) -> CardOptions:
    return CardOptions(
        direction=rng.choice(list(Direction)),
        interaction=rng.choice(list(Interaction)),
        context_labels=rng.choice([True, False]),
        mode=rng.choice(list(CardMode)),
    )


# ---- the headline invariant: build -> read is lossless -----------------------


@pytest.mark.parametrize("seed", range(60))
def test_factory_reader_roundtrip(seed: int) -> None:
    rng = random.Random(seed)
    structures = _random_structures(rng)
    options = _random_options(rng)
    image = _nonblank(rng, _FILENAME_CHARS, 20) + ".png"
    header = rng.choice(["", _nonblank(rng, _LABEL_CHARS, 30)])
    back = rng.choice(["", _nonblank(rng, _LABEL_CHARS, 30)])

    content = NoteFactory(DEFAULT_SPEC).build(
        image_filename=image,
        structures=structures,
        options=options,
        header=header,
        back_extra=back,
    )
    loaded = NoteReader(DEFAULT_SPEC).read(content.fields)

    assert loaded.structures == structures
    assert loaded.image_filename == image
    assert loaded.header == header
    assert loaded.back_extra == back
    assert loaded.options.direction == options.direction
    assert loaded.options.mode == options.mode
    assert loaded.options.context_labels == options.context_labels
    assert loaded.options.interaction == options.interaction


# ---- the wire format round-trips and never leaks injection characters --------


@pytest.mark.parametrize("seed", range(40))
def test_payload_roundtrips_and_is_pure_base64(seed: int) -> None:
    rng = random.Random(1000 + seed)
    structures = _random_structures(rng)
    options = _random_options(rng)

    encoded = structures.to_payload_base64(options)
    # Pure base64 => no '<', '{', quotes etc. can escape the <script> element.
    assert re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", encoded)

    payload = decode_json_b64(encoded)
    assert payload["mode"] == options.mode.value
    assert payload["direction"] == options.direction.value
    assert payload["contextLabels"] == options.context_labels
    assert StructureSet.from_dicts(payload["structures"]) == structures


@pytest.mark.parametrize("seed", range(40))
def test_codec_roundtrip(seed: int) -> None:
    rng = random.Random(2000 + seed)
    obj = _random_json(rng, depth=3)
    assert decode_json_b64(encode_json_b64(obj)) == obj


# ---- the cloze field: right count, ordinals, and metacharacters neutralised --


@pytest.mark.parametrize("seed", range(40))
def test_cloze_field_count_and_ordinals(seed: int) -> None:
    rng = random.Random(3000 + seed)
    structures = _random_structures(rng)
    n = len(structures)

    assert structures.cloze_field(CardOptions(mode=CardMode.SINGLE)) == "{{c1::.}}"

    forward = structures.cloze_field(CardOptions(direction=Direction.FORWARD))
    both = structures.cloze_field(CardOptions(direction=Direction.BOTH))
    # Labels are escaped so "{{c" only ever marks a real cloze start. Every
    # direction emits one card per structure (direction is a render-time choice).
    assert forward.count("{{c") == n
    assert both == forward
    assert f"{{{{c{n}::" in forward


@pytest.mark.parametrize("seed", range(40))
def test_cloze_answers_never_contain_raw_metacharacters(seed: int) -> None:
    rng = random.Random(4000 + seed)
    structures = _random_structures(rng)
    field = structures.cloze_field(CardOptions(direction=Direction.FORWARD))
    # Strip the real cloze wrappers, then no cloze metacharacters may remain in
    # what's left (the labels), or Anki would mis-parse the field.
    answers = re.findall(r"\{\{c\d+::(.*?)\}\}", field, flags=re.DOTALL)
    assert len(answers) == len(structures)
    for answer in answers:
        assert "{{" not in answer
        assert "}}" not in answer
        assert "::" not in answer


def _random_json(rng: random.Random, depth: int):
    """A finite (no NaN/Infinity) JSON-serialisable value."""
    if depth <= 0:
        return rng.choice(
            [
                rng.randint(-1000, 1000),
                round(rng.uniform(-1e6, 1e6), 4),
                _nonblank(rng, _LABEL_CHARS, 20),
                rng.choice([True, False]),
                None,
            ]
        )
    kind = rng.choice(["scalar", "list", "dict"])
    if kind == "scalar":
        return _random_json(rng, 0)
    if kind == "list":
        return [_random_json(rng, depth - 1) for _ in range(rng.randint(0, 4))]
    return {
        _nonblank(rng, string.ascii_letters, 8): _random_json(rng, depth - 1)
        for _ in range(rng.randint(0, 4))
    }
