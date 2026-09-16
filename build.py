#!/usr/bin/env python3
"""Package the add-on into a distributable ``.ankiaddon`` zip.

An ``.ankiaddon`` file is a plain zip whose *root* contains ``__init__.py`` (no
wrapping folder). This script zips the contents of ``src/randomized_occlusion/``
into ``dist/randomized_occlusion.ankiaddon``, skipping caches and dev artefacts.

Usage:
    python build.py
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE_DIR = ROOT / "src" / "randomized_occlusion"
DIST_DIR = ROOT / "dist"
OUTPUT = DIST_DIR / "randomized_occlusion.ankiaddon"

# Files/dirs that must never ship inside the add-on.
EXCLUDED_NAMES = {"__pycache__", "meta.json", ".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}

# The add-on's per-profile scratch directory. Anki writes into it at runtime and
# .gitignore keeps that out of `git status`, so a developer building from a
# symlinked install would otherwise ship their own profile state without ever
# seeing it. The directory still has to exist in the archive, so its marker file
# ships and nothing else beneath it does.
USER_FILES_DIR = "user_files"
USER_FILES_KEEP = ".gitkeep"

# A fixed timestamp and file metadata for every zip entry, so building the same
# source twice (on any machine/OS) yields a byte-identical .ankiaddon. Without
# this, each entry would embed its file's on-disk mtime (and the host OS), and
# two clean checkouts of the same commit would hash differently. 1980-01-01 is
# the earliest the zip format can represent.
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)
_UNIX_RW_R_R = 0o644 << 16  # regular file, rw-r--r--, stable across platforms


def _included(relative: Path) -> bool:
    """Whether the package file at ``relative`` belongs in the archive.

    Takes the path RELATIVE to the package, so the decision cannot turn on
    where the checkout happens to live -- a repo under a directory named
    ``__pycache__`` would otherwise produce an empty archive.
    """
    if any(part in EXCLUDED_NAMES for part in relative.parts):
        return False
    if relative.parts[0] == USER_FILES_DIR:
        return relative.parts == (USER_FILES_DIR, USER_FILES_KEEP)
    return relative.suffix not in EXCLUDED_SUFFIXES


def _entry(arcname: str) -> zipfile.ZipInfo:
    """A ZipInfo with pinned metadata so the archive is byte-reproducible."""
    info = zipfile.ZipInfo(arcname, date_time=_FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix, fixed regardless of the build host's OS
    info.external_attr = _UNIX_RW_R_R
    return info


def _read_version() -> str:
    """The single source of truth for the version, read without importing aqt.

    ``_version.py`` is standalone, so exec-ing it in an isolated namespace avoids
    importing the package (whose ``__init__`` would try to reach Anki).
    """
    namespace: dict[str, object] = {}
    exec((PACKAGE_DIR / "_version.py").read_text(encoding="utf-8"), namespace)
    return str(namespace["__version__"])


def _manifest_bytes(path: Path, version: str) -> bytes:
    """The manifest with ``human_version`` stamped from ``_version.py``.

    Stamping at build time means the shipped ``.ankiaddon`` can never advertise a
    version that has drifted from the source of truth.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    data["human_version"] = version
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def _display(output: Path) -> str:
    """``output`` relative to the repo, or in full when it lies outside it."""
    try:
        return str(output.relative_to(ROOT))
    except ValueError:
        return str(output)


def build(output: Path = OUTPUT) -> Path:
    """Write the add-on to ``output`` and return that path.

    ``output`` is a parameter so the tests can build into a temp directory. They
    build about twenty times, and the mutation harness builds from a deliberately
    broken ``build.py``; writing to ``dist/`` would leave the shipping artefact as
    whatever the last mutant produced.
    """
    if not PACKAGE_DIR.is_dir():
        raise SystemExit(f"package directory not found: {PACKAGE_DIR}")

    version = _read_version()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    count = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKAGE_DIR.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(PACKAGE_DIR)
            if not _included(relative):
                continue
            arcname = relative.as_posix()
            data = (
                _manifest_bytes(path, version)
                if arcname == "manifest.json"
                else path.read_bytes()
            )
            archive.writestr(_entry(arcname), data)
            count += 1

    print(f"Wrote {_display(output)} v{version} ({count} files)")
    return output


if __name__ == "__main__":
    build()
