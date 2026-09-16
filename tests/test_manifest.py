from __future__ import annotations

import json
from pathlib import Path

import randomized_occlusion
from randomized_occlusion._version import __version__


def _manifest() -> dict:
    path = Path(randomized_occlusion.__file__).parent / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_human_version_matches_version_module():
    # _version.py is the single source of truth; the manifest must not drift.
    # (build.py also re-stamps this, but keeping the source in sync means the
    # symlink dev install and the built artifact always agree.)
    assert _manifest()["human_version"] == __version__


def test_manifest_declares_the_required_fields():
    manifest = _manifest()
    assert manifest["package"] == "randomized_occlusion"
    assert manifest["name"] == "Randomized Image Occlusion"
    # Anki 23.10 introduced the modern add-on APIs this add-on relies on.
    assert manifest["min_point_version"] == 231000
    assert manifest["homepage"].startswith("https://")


def _addon_dir() -> Path:
    return Path(randomized_occlusion.__file__).parent


def test_config_md_uses_no_markdown_table():
    # Anki renders config.md with markdown.markdown(..., extensions=[md_in_html]),
    # and `tables` has never been a default-enabled extension -- so a table comes
    # out as one paragraph of literal pipes. That pane is the only in-app
    # reference for these keys, so it has to render.
    lines = (_addon_dir() / "config.md").read_text(encoding="utf-8").splitlines()
    offenders = [n for n, line in enumerate(lines, 1) if line.lstrip().startswith("|")]
    assert not offenders, (
        f"config.md has table rows on lines {offenders}; Anki renders them as "
        "literal pipes. Use a bulleted list instead."
    )


def test_every_config_key_is_documented():
    # A key the user can edit but cannot look up is a key they will set wrongly.
    directory = _addon_dir()
    keys = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    doc = (directory / "config.md").read_text(encoding="utf-8")
    missing = [key for key in keys if f"`{key}`" not in doc]
    assert not missing, f"config.json keys with no entry in config.md: {missing}"
