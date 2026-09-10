"""The packaging script is byte-reproducible, and the archive is installable.

``build.py`` lives at the repo root (not in the ``src`` package), so it is loaded
by path here. Two builds of the same source must be byte-identical regardless of
when they run or on which OS, so a shipped ``.ankiaddon`` can be verified against
its source.
"""
from __future__ import annotations

import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load_build():
    spec = importlib.util.spec_from_file_location("_ro_build", _ROOT / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_build()


@pytest.fixture
def out(tmp_path: Path) -> Path:
    """Where a test builds to.

    Never ``dist/``. This file builds around twenty times per run, and the
    mutation harness runs it against a deliberately broken ``build.py``, which
    would leave the shipping artefact as whatever the last mutant produced.
    """
    return tmp_path / "randomized_occlusion.ankiaddon"


def _infos(out: Path) -> list[zipfile.ZipInfo]:
    """Every entry in a freshly built archive, in the order it was written.

    A list, not a dict keyed by filename: a dict silently collapses duplicates,
    which is exactly what ``test_rebuild_replaces_rather_than_appends`` looks for,
    and it hides a repeat that breaks the sort order.
    """
    with zipfile.ZipFile(build.build(out)) as archive:
        return archive.infolist()


def _names(out: Path) -> list[str]:
    return [info.filename for info in _infos(out)]


def test_build_is_byte_reproducible(out: Path):
    first = build.build(out).read_bytes()
    second = build.build(out).read_bytes()
    assert first == second  # same source -> identical archive bytes


def test_entries_use_the_pinned_timestamp(out: Path):
    # If any entry embedded its file's on-disk mtime, two clean checkouts of the
    # same commit would hash differently; every entry must use the fixed date.
    infos = _infos(out)
    assert infos, "archive is empty"
    for info in infos:
        # A literal, not build._FIXED_DATE: comparing the archive against the
        # constant that produced it passes whatever that constant is.
        assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename


# ---- the .ankiaddon contract ------------------------------------------------
#
# Anki requires __init__.py at the archive root, refuses to install caches, and
# reads human_version from the manifest. None of that was asserted; two builds
# agreeing says nothing about whether either is installable.


def test_init_py_is_at_the_archive_root(out: Path):
    # An .ankiaddon is a zip whose ROOT holds __init__.py. Nested under a folder,
    # Anki rejects it.
    assert "__init__.py" in _names(out)


def test_entry_names_are_posix_and_root_relative(out: Path):
    # as_posix() is load-bearing on Windows: an entry named with backslashes is
    # not a subdirectory to an unzipper, it is one file with a strange name, so
    # the add-on would extract flat and fail to import.
    for name in _names(out):
        assert "\\" not in name, name
        assert not name.startswith("/"), name
        assert ".." not in name.split("/"), name


def test_archive_excludes_caches_and_local_state(out: Path):
    for name in _names(out):
        parts = name.split("/")
        assert "__pycache__" not in parts, name
        assert "meta.json" not in parts, name
        assert not name.endswith((".pyc", ".pyo")), name


def test_archive_ships_user_files(out: Path):
    assert any(n.startswith("user_files/") for n in _names(out))


def test_entries_are_written_in_sorted_order(out: Path):
    # Order is part of byte-reproducibility: the same tree must serialise the
    # same way whatever order the filesystem happens to walk it in. The sort is
    # by path components, not by the joined string ("." sorts before "/"), so
    # compare against PurePosixPath ordering rather than plain string ordering.
    from pathlib import PurePosixPath

    names = _names(out)
    assert names == [str(p) for p in sorted(PurePosixPath(n) for n in names)]


def test_entry_metadata_is_platform_independent(out: Path):
    # date_time alone is not enough: create_system and external_attr embed the
    # building OS and its umask, so a Windows build and a Linux build of the same
    # commit would differ without these.
    for info in _infos(out):
        assert info.compress_type == zipfile.ZIP_DEFLATED, info.filename
        assert info.create_system == 3, f"{info.filename} was stamped with a non-Unix host"
        assert info.external_attr == (0o644 << 16), info.filename


def _declared_version() -> str:
    """The version parsed straight out of _version.py.

    Not build._read_version(): comparing the archive against the function that
    stamped it agrees with itself whatever either one returns, so neither
    dropping the stamp nor breaking the read would fail.
    """
    text = (build.PACKAGE_DIR / "_version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    assert match is not None, "_version.py no longer declares __version__"
    return match.group(1)


def test_shipped_manifest_carries_the_declared_version(out: Path):
    with zipfile.ZipFile(build.build(out)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["human_version"] == _declared_version()


def test_shipped_manifest_keeps_its_other_keys(out: Path):
    with zipfile.ZipFile(build.build(out)) as archive:
        shipped = json.loads(archive.read("manifest.json"))
    on_disk = json.loads((build.PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert shipped["package"] == on_disk["package"]
    assert shipped["min_point_version"] == on_disk["min_point_version"]


def test_rebuild_replaces_rather_than_appends(out: Path):
    # Counted as a list. len() of a dict keyed by filename is the number of
    # DISTINCT names, which cannot change however many times each is appended.
    first = _names(out)
    second = _names(out)
    assert second == first
    assert len(second) == len(set(second)), "an entry was written twice"


def test_included_rejects_caches_and_bytecode():
    # The two exclusion rules mask each other when checked through the archive:
    # every file inside __pycache__ is also a .pyc, so emptying either set alone
    # changes nothing. The predicate is where the contract actually lives.
    #
    # Absolute paths, because that is what build() passes: _included checks every
    # part, so a checkout living under a directory called __pycache__ would
    # exclude the whole tree, and a test on relative paths could never see it.
    package = build.PACKAGE_DIR

    assert build._included(package / "editor" / "dialog.py")
    assert build._included(package / "web" / "editor" / "marker.js")

    assert not build._included(package / "__pycache__" / "x.py")
    assert not build._included(package / "meta.json")
    assert not build._included(package / ".DS_Store")
    assert not build._included(package / "editor" / "dialog.pyc")
    assert not build._included(package / "editor" / "dialog.pyo")


def test_read_version_matches_version_py():
    # Parsed here rather than compared against build._read_version()'s own
    # result, which would agree with itself whatever it returned.
    declared = _declared_version()
    assert build._read_version() == declared
    assert declared.count(".") == 2, declared


def test_manifest_bytes_stamps_the_given_version():
    stamped = json.loads(build._manifest_bytes(build.PACKAGE_DIR / "manifest.json", "9.9.9"))
    assert stamped["human_version"] == "9.9.9"
    assert stamped["package"], "the rest of the manifest survives the stamp"


def test_build_writes_where_it_is_told(tmp_path: Path):
    # The output path is a parameter so a test run never touches dist/. If that
    # regressed to a hard-coded OUTPUT, every test here would go back to
    # rewriting the shipping artefact, and a mutation campaign would leave a
    # deliberately broken build there.
    #
    # The real artefact is watched directly. Asserting that some other directory
    # was not created would pass whatever build() wrote, since it only ever
    # writes one file.
    before = build.OUTPUT.stat().st_mtime_ns if build.OUTPUT.exists() else None

    target = tmp_path / "nested" / "custom.ankiaddon"
    assert build.build(target) == target
    assert target.is_file()

    after = build.OUTPUT.stat().st_mtime_ns if build.OUTPUT.exists() else None
    assert after == before, "building elsewhere still wrote to dist/"

