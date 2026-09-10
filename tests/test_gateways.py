"""The adapters over Anki's collection APIs.

These are the only place the add-on touches ``col.models`` and ``col.media``, and
they had no tests: ``test_installer.py`` exercises the installer against a fake
gateway that re-implements this logic, so its assertions read back the fake's own
literals rather than anything here.

The doubles below record calls instead of reimplementing them, so a test can
assert what was handed to Anki.
"""

from __future__ import annotations

import pytest

from randomized_occlusion.collection.gateways import AnkiMediaGateway, AnkiModelGateway


class SpyModels:
    """Records what the gateway asks ``col.models`` to do."""

    def __init__(self, existing=None):
        self.existing = existing or {}
        self.added: list[dict] = []
        self.updated: list[dict] = []

    def by_name(self, name):
        return self.existing.get(name)

    def new(self, name):
        return {"name": name, "flds": [], "tmpls": []}

    def new_field(self, name):
        return {"name": name}

    def add_field(self, notetype, field):
        notetype["flds"].append(field)

    def new_template(self, name):
        return {"name": name}

    def add_template(self, notetype, template):
        notetype["tmpls"].append(template)

    def add_dict(self, notetype):
        self.added.append(notetype)

    def update_dict(self, notetype):
        self.updated.append(notetype)


class SpyMedia:
    def __init__(self, returns="stored.png"):
        self.returns = returns
        self.calls: list[str] = []

    def add_file(self, path):
        self.calls.append(path)
        return self.returns


class FakeCollection:
    def __init__(self, models=None, media=None):
        self.models = models or SpyModels()
        self.media = media or SpyMedia()


#: Deliberately unlike anything the add-on ships, and unlike each other, so a
#: test that overrides one of them cannot pass on the default by accident.
_DEFAULTS = {
    "name": "Randomized Occlusion",
    "fields": ("Image", "Structures", "Header"),
    "sort_index": 2,
    "template_name": "Occlusion",
    "front": "FRONT",
    "back": "BACK",
    "css": "CSS",
    "collapsed_fields": (),
}


def _create(gateway, **overrides):
    for key, value in overrides.items():
        assert key in _DEFAULTS, f"{key} is not a create_cloze_notetype argument"
        assert value != _DEFAULTS[key], (
            f"overriding {key} with its own default varies nothing; either pass a "
            "different value or drop the override"
        )
    gateway.create_cloze_notetype(**{**_DEFAULTS, **overrides})


# ---------------------------------------------------------------- lookups


def test_find_returns_the_note_type_by_name():
    models = SpyModels({"Randomized Occlusion": {"id": 7}})
    assert AnkiModelGateway(FakeCollection(models)).find("Randomized Occlusion") == {"id": 7}


def test_find_returns_none_when_absent():
    assert AnkiModelGateway(FakeCollection(SpyModels())).find("Missing") is None


# ---------------------------------------------------------------- creation


def test_created_note_type_is_a_cloze():
    models = SpyModels()
    _create(AnkiModelGateway(FakeCollection(models)))
    # Kind 1 is cloze. A standard note type (kind 0) still generates cards, but
    # one per template rather than one per cloze deletion, so every marker on a
    # note would collapse into a single card.
    assert models.added[0]["type"] == 1


def test_created_note_type_is_persisted_once():
    models = SpyModels()
    _create(AnkiModelGateway(FakeCollection(models)))
    assert len(models.added) == 1
    assert models.updated == []


def test_created_note_type_keeps_the_field_order():
    # Not in alphabetical order, so a gateway that sorted the fields (or reversed
    # them) would be caught. Anki addresses fields by position, so a reorder
    # silently rewrites what every existing note means.
    models = SpyModels()
    _create(AnkiModelGateway(FakeCollection(models)), fields=("Zeta", "Alpha", "Mu"))
    assert [f["name"] for f in models.added[0]["flds"]] == ["Zeta", "Alpha", "Mu"]


def test_created_note_type_stores_the_sort_index():
    models = SpyModels()
    _create(AnkiModelGateway(FakeCollection(models)), sort_index=1)
    assert models.added[0]["sortf"] == 1


def test_front_and_back_are_not_swapped_on_create():
    models = SpyModels()
    _create(AnkiModelGateway(FakeCollection(models)), front="Q", back="A")
    template = models.added[0]["tmpls"][0]
    assert template["qfmt"] == "Q"
    assert template["afmt"] == "A"


def test_created_template_takes_its_name_and_css():
    models = SpyModels()
    _create(AnkiModelGateway(FakeCollection(models)), template_name="Card 1", css="BODY{}")
    assert models.added[0]["tmpls"][0]["name"] == "Card 1"
    assert models.added[0]["css"] == "BODY{}"


def test_only_the_named_fields_are_collapsed():
    models = SpyModels()
    _create(
        AnkiModelGateway(FakeCollection(models)),
        collapsed_fields=("Image", "Structures"),
    )
    collapsed = {f["name"]: f.get("collapsed", False) for f in models.added[0]["flds"]}
    assert collapsed == {"Image": True, "Structures": True, "Header": False}


# ---------------------------------------------------------------- updates


def test_update_rewrites_both_templates_and_the_css():
    models = SpyModels()
    notetype = {"tmpls": [{"qfmt": "old q", "afmt": "old a"}], "css": "old"}
    AnkiModelGateway(FakeCollection(models)).update_templates(
        notetype, front="new q", back="new a", css="new css"
    )
    assert notetype["tmpls"][0]["qfmt"] == "new q"
    assert notetype["tmpls"][0]["afmt"] == "new a"
    assert notetype["css"] == "new css"


def test_update_is_persisted():
    models = SpyModels()
    notetype = {"tmpls": [{}], "css": ""}
    AnkiModelGateway(FakeCollection(models)).update_templates(
        notetype, front="q", back="a", css="c"
    )
    assert models.updated == [notetype]


def test_update_touches_only_the_first_template():
    models = SpyModels()
    second = {"qfmt": "leave", "afmt": "alone"}
    notetype = {"tmpls": [{"qfmt": "", "afmt": ""}, second], "css": ""}
    AnkiModelGateway(FakeCollection(models)).update_templates(
        notetype, front="q", back="a", css="c"
    )
    assert second == {"qfmt": "leave", "afmt": "alone"}


# ---------------------------------------------------------------- fields


def test_ensure_fields_adds_only_what_is_missing():
    models = SpyModels()
    notetype = {"flds": [{"name": "Image"}]}
    changed = AnkiModelGateway(FakeCollection(models)).ensure_fields(
        notetype, ("Image", "Structures")
    )
    assert changed is True
    assert [f["name"] for f in notetype["flds"]] == ["Image", "Structures"]


def test_ensure_fields_reports_no_change_when_all_present():
    models = SpyModels()
    notetype = {"flds": [{"name": "Image"}, {"name": "Structures"}]}
    changed = AnkiModelGateway(FakeCollection(models)).ensure_fields(
        notetype, ("Image", "Structures")
    )
    assert changed is False
    assert len(notetype["flds"]) == 2


def test_collapse_fields_marks_the_named_fields():
    notetype = {"flds": [{"name": "Image"}, {"name": "Header"}]}
    changed = AnkiModelGateway(FakeCollection()).collapse_fields(notetype, ("Image",))
    assert changed is True
    assert notetype["flds"][0]["collapsed"] is True
    # `.get`, not `not in`: real Anki field dicts are schema-11 JSON from the
    # backend, where `collapsed` is always present and defaults to false. This
    # fixture is minimal, so asserting absence would pass here and mean nothing
    # about a real collection.
    assert notetype["flds"][1].get("collapsed", False) is False


def test_collapse_fields_is_idempotent():
    notetype = {"flds": [{"name": "Image", "collapsed": True}]}
    assert AnkiModelGateway(FakeCollection()).collapse_fields(notetype, ("Image",)) is False


# ---------------------------------------------------------------- media


def test_add_image_returns_the_stored_basename():
    # add_file may rename on a content clash, so the caller must use what comes
    # back rather than the path it passed in.
    media = SpyMedia(returns="renamed-abc123.png")
    gateway = AnkiMediaGateway(FakeCollection(media=media))
    assert gateway.add_image("C:/pictures/heart.png") == "renamed-abc123.png"


def test_add_image_passes_the_path_through():
    media = SpyMedia()
    AnkiMediaGateway(FakeCollection(media=media)).add_image("C:/pictures/heart.png")
    assert media.calls == ["C:/pictures/heart.png"]


def test_gateways_do_not_import_anki():
    # Loaded straight from its file, not as `randomized_occlusion.collection.
    # gateways`: importing it by name runs the package __init__, which does
    # `from aqt import mw` inside a try/except. With aqt absent that swallows the
    # error and the check passes whatever gateways.py does; with aqt installed
    # (pyproject ships an `anki` extra for exactly that) the check fails and
    # blames this module for an import it does not make.
    #
    # In a subprocess, because by the time this file runs the module is long
    # since imported and sys.modules describes the whole session.
    import subprocess
    import sys
    from pathlib import Path

    module = Path(__file__).resolve().parent.parent / "src" / "randomized_occlusion"
    module = module / "collection" / "gateways.py"
    probe = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('probe', {str(module)!r})\n"
        "spec.loader.exec_module(importlib.util.module_from_spec(spec))\n"
        "leaked = sorted(n for n in sys.modules if n.split('.')[0] in ('anki', 'aqt'))\n"
        "assert not leaked, 'gateways.py pulled in ' + ', '.join(leaked)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("missing", ["models", "media"])
def test_missing_collection_attribute_raises(missing):
    class Partial:
        pass

    collection = Partial()
    # The other attribute is present, so the error can only be about the one
    # named, and the message is asserted, or this would pass for an AttributeError
    # raised by anything at all.
    setattr(collection, "media" if missing == "models" else "models", object())
    factory = AnkiModelGateway if missing == "models" else AnkiMediaGateway
    with pytest.raises(AttributeError, match=missing):
        factory(collection)
