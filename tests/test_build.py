"""The packaging script is byte-reproducible.

``build.py`` lives at the repo root (not in the ``src`` package), so it is loaded
by path here. Two builds of the same source must be byte-identical regardless of
when they run or on which OS, so a shipped ``.ankiaddon`` can be verified against
its source.
"""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _load_build():
    spec = importlib.util.spec_from_file_location("_ro_build", _ROOT / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_build()


def test_build_is_byte_reproducible():
    first = build.build().read_bytes()
    second = build.build().read_bytes()
    assert first == second  # same source -> identical archive bytes


def test_every_zip_entry_uses_the_pinned_timestamp():
    # If any entry embedded its file's on-disk mtime, two clean checkouts of the
    # same commit would hash differently; every entry must use the fixed date.
    with zipfile.ZipFile(build.build()) as archive:
        infos = archive.infolist()
        assert infos, "archive is empty"
        for info in infos:
            assert info.date_time == build._FIXED_DATE, info.filename
