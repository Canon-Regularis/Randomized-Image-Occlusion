from __future__ import annotations

import base64

import pytest

from randomized_occlusion.domain.codec import decode_json_b64, encode_json_b64


def test_round_trips_nested_and_unicode():
    obj = {"a": 1, "b": [True, False, None, "café — 中文 ✓ Ω"], "c": {"x": 0.5}}
    assert decode_json_b64(encode_json_b64(obj)) == obj


def test_output_is_ascii_and_carries_no_injection_characters():
    # The whole point of the base64 wrapper: arbitrary label/config text can never
    # smuggle HTML, a </script>, or an Anki {{...}} token into the card template.
    encoded = encode_json_b64({"label": "</script><b>{{Deck}}</b> \"x\" 'y'"})
    assert encoded.isascii()
    for ch in "<>{}\"'":
        assert ch not in encoded, f"base64 output must not contain {ch!r}"
    assert decode_json_b64(encoded)["label"] == "</script><b>{{Deck}}</b> \"x\" 'y'"


def test_json_is_compact_with_no_incidental_whitespace():
    raw = base64.b64decode(encode_json_b64({"a": 1, "b": 2}).encode("ascii")).decode("utf-8")
    assert raw == '{"a":1,"b":2}'  # separators=(",", ":") — no spaces


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_encode_rejects_non_finite_numbers(bad: float):
    # allow_nan=False: never emit a bare NaN/Infinity token (which isn't valid JSON).
    with pytest.raises(ValueError):
        encode_json_b64({"n": bad})


def test_decode_rejects_non_base64_characters():
    # validate=True surfaces stray characters as an error instead of ignoring them
    # (note_reader relies on this being a ValueError subclass).
    with pytest.raises(ValueError):
        decode_json_b64("not valid base64 @@@")


def test_decode_rejects_valid_base64_that_is_not_json():
    not_json = base64.b64encode(b"hello, not json").decode("ascii")
    with pytest.raises(ValueError):
        decode_json_b64(not_json)


def test_decode_rejects_valid_base64_that_is_not_utf8():
    bad_utf8 = base64.b64encode(b"\xff\xfe\xfd").decode("ascii")
    with pytest.raises(ValueError):
        decode_json_b64(bad_utf8)
