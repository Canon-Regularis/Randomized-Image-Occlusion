"""The fallible prelude every note-writing op runs before it opens an undo entry.

No Anki needed: ``ops/runner.py`` stopped importing ``CollectionOp`` at module
scope, and everything ``prepare_content`` touches duck-types a collection, so
the fakes from ``test_gateways.py`` stand in for one.
"""

from __future__ import annotations

import pytest

from randomized_occlusion.config.defaults import DEFAULT_CONFIG
from randomized_occlusion.config.render_config import RenderConfig
from randomized_occlusion.domain.card_options import CardOptions
from randomized_occlusion.domain.geometry import NormalizedPoint
from randomized_occlusion.domain.structure import Structure
from randomized_occlusion.domain.structure_set import StructureSet
from randomized_occlusion.notetype.spec import DEFAULT_SPEC
from randomized_occlusion.ops.runner import prepare_content

# tests/ is not a package; pytest puts the test directory on sys.path.
from test_gateways import FakeCollection, SpyModels


def _structures():
    return StructureSet.from_unordered(
        [Structure(ordinal=1, target=NormalizedPoint(0.2, 0.3), label="Aorta")]
    )


def _notetype(field_names):
    return {
        "name": DEFAULT_SPEC.name,
        "type": 1,
        "flds": [{"name": name} for name in field_names],
        "tmpls": [{"name": DEFAULT_SPEC.template_name, "qfmt": "", "afmt": ""}],
        "css": "",
        "sortf": 0,
    }


def _prepare(collection, **overrides):
    kwargs = {
        "col": collection,
        "spec": DEFAULT_SPEC,
        "render_config": RenderConfig.from_mapping(DEFAULT_CONFIG),
        "resolve_image": lambda _col: "x.png",
        "structures": _structures(),
        "options": CardOptions(),
        "header": "Heart",
        "back_extra": "",
    }
    kwargs.update(overrides)
    return prepare_content(**kwargs)


def test_content_is_built_for_a_healthy_collection():
    # The install has to happen here, not later: it is a schema change, and a
    # schema change clears the undo queue. Running it inside the undo entry the
    # caller opens next would discard that entry.
    collection = FakeCollection()

    content = _prepare(collection)

    assert [n['name'] for n in collection.models.added] == [DEFAULT_SPEC.name]
    assert content.notetype_name == DEFAULT_SPEC.name
    assert content.fields[DEFAULT_SPEC.image_field] == '<img src="x.png">'


def test_a_renamed_field_is_refused_with_the_name_of_the_field():
    # Both ops assign note[name] before commit_with_undo, so a KeyError would
    # already have landed outside the undo entry: nothing here is protecting the
    # undo queue. What it buys is a message that names the field and the screen
    # to fix it on, where a KeyError names nothing a user can act on.
    renamed = [
        "Payload" if name == DEFAULT_SPEC.structures_field else name
        for name in DEFAULT_SPEC.fields
    ]
    models = SpyModels({DEFAULT_SPEC.name: _notetype(renamed)})

    with pytest.raises(RuntimeError) as caught:
        _prepare(FakeCollection(models))

    message = str(caught.value)
    assert DEFAULT_SPEC.structures_field in message, "name the field that is gone"
    # Naming every required field would pass the assertion above without
    # telling anyone anything, which is what it did until this line was added.
    # repr(), not a bare substring: the note type is called "Randomized Image
    # Occlusion", so a plain 'Image' in message matches its own name.
    still_there = [
        name
        for name in DEFAULT_SPEC.required_fields
        if name != DEFAULT_SPEC.structures_field and repr(name) in message
    ]
    assert not still_there, f"named fields that are present: {still_there}"
    assert "Manage Note Types" in message, "and where to put it back"
    assert models.updated == [], "and write nothing on the way out"


def test_an_ordinary_install_is_not_mistaken_for_a_renamed_one():
    models = SpyModels({DEFAULT_SPEC.name: _notetype(DEFAULT_SPEC.fields)})

    assert _prepare(FakeCollection(models)).notetype_name == DEFAULT_SPEC.name
