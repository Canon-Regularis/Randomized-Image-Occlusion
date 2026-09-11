from __future__ import annotations

import os
from datetime import datetime

import pytest

from randomized_occlusion.editor.paste_scratch import PARTIAL, PasteScratch


def _scratch(tmp_path, *, stamps=("20260908-134500",)):
    """A scratch area in `tmp_path`, with a scripted clock."""
    made = []
    times = list(stamps)

    def make_dir():
        directory = tmp_path / f"scratch-{len(made)}"
        directory.mkdir()
        made.append(str(directory))
        return str(directory)

    def now():
        return datetime.strptime(times.pop(0) if len(times) > 1 else times[0], "%Y%m%d-%H%M%S")

    return PasteScratch(make_dir=make_dir, now=now), made


def test_no_directory_until_first_write(tmp_path):
    scratch, made = _scratch(tmp_path)
    assert scratch.directory is None
    assert made == []


def test_directory_created_once(tmp_path):
    scratch, made = _scratch(tmp_path)
    scratch.write_bytes(b"one", ".png")
    scratch.write_bytes(b"two", ".png")
    scratch.write_bytes(b"three", ".gif")
    assert len(made) == 1


def test_write_bytes_returns_the_written_path(tmp_path):
    scratch, _ = _scratch(tmp_path)
    path = scratch.write_bytes(b"\x89PNG payload", ".png")

    assert os.path.basename(path) == "paste-20260908-134500-1.png"
    with open(path, "rb") as handle:
        assert handle.read() == b"\x89PNG payload"


def test_successful_write_leaves_no_partial(tmp_path):
    scratch, made = _scratch(tmp_path)
    scratch.write_bytes(b"payload", ".png")
    assert [n for n in os.listdir(made[0]) if n.endswith(PARTIAL)] == []


def test_failed_write_preserves_existing_file(tmp_path):
    # The whole reason the write is staged: the canvas goes on showing the
    # picture whose path we already handed out, so that file must still be it.
    scratch, made = _scratch(tmp_path)
    first = scratch.write_bytes(b"the good image", ".png")

    def explode(path: str) -> bool:
        # Fails part-way, as a full disk would: some bytes land, then it stops.
        with open(path, "wb") as handle:
            handle.write(b"half a p")
        raise OSError("disk full")

    with pytest.raises(OSError):
        scratch.write_via(explode, ".png")

    with open(first, "rb") as handle:
        assert handle.read() == b"the good image"
    assert [n for n in os.listdir(made[0]) if n.endswith(PARTIAL)] == []


def test_a_second_write_in_the_same_second_gets_its_own_file(tmp_path):
    # The stamp resolves only to the second, so these two used to share a name and
    # the second write replaced the bytes of the first. The dialog holds the path
    # of the image it is CURRENTLY showing, so a paste the user then declined had
    # already overwritten the picture on the canvas: it saved a note pairing one
    # image with markers placed on another.
    scratch, _ = _scratch(tmp_path)
    first = scratch.write_bytes(b"older", ".png")
    second = scratch.write_bytes(b"newer", ".png")

    assert first != second
    with open(first, "rb") as handle:
        assert handle.read() == b"older", "the earlier paste was overwritten"
    with open(second, "rb") as handle:
        assert handle.read() == b"newer"


def test_encoder_failure_raises_oserror(tmp_path):
    scratch, made = _scratch(tmp_path)
    with pytest.raises(OSError):
        scratch.write_via(lambda path: False, ".png")
    assert os.listdir(made[0]) == []


def test_partial_encode_is_not_renamed_into_place(tmp_path):
    # The encoder said it failed but still left bytes behind. Trusting the file
    # rather than the return value would hand the canvas a truncated image.
    scratch, made = _scratch(tmp_path)

    def half(path: str) -> bool:
        with open(path, "wb") as handle:
            handle.write(b"truncated PNG bytes")
        return False

    with pytest.raises(OSError):
        scratch.write_via(half, ".png")
    assert os.listdir(made[0]) == []


def test_write_via_stages_through_the_partial_path(tmp_path):
    scratch, _ = _scratch(tmp_path)
    seen = []

    def save(path: str) -> bool:
        seen.append(path)
        with open(path, "wb") as handle:
            handle.write(b"encoded")
        return True

    path = scratch.write_via(save, ".png")
    assert seen == [path + PARTIAL], "the encoder writes the staged file, not the final one"
    with open(path, "rb") as handle:
        assert handle.read() == b"encoded"


def test_unsupported_suffix_falls_back_to_png(tmp_path):
    scratch, _ = _scratch(tmp_path)
    path = scratch.write_bytes(b"payload", ".exe")
    assert path.endswith(".png")


def test_discard_removes_the_directory_and_is_idempotent(tmp_path):
    scratch, made = _scratch(tmp_path)
    scratch.write_bytes(b"payload", ".png")

    scratch.discard()
    assert not os.path.exists(made[0])
    assert scratch.directory is None
    scratch.discard()  # several exits race to be last; none may raise


def test_discard_without_a_write_is_a_noop(tmp_path):
    scratch, _ = _scratch(tmp_path)
    scratch.discard()


def test_write_after_discard_creates_a_new_directory(tmp_path):
    scratch, made = _scratch(tmp_path)
    scratch.write_bytes(b"payload", ".png")
    scratch.discard()

    path = scratch.write_bytes(b"payload", ".png")
    assert len(made) == 2
    assert os.path.exists(path)
