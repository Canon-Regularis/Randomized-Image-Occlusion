"""The wiring that builds the note type's assembler and installer.

This module had no test and no mutation target, which is worse than it sounds:
it is the one place that loads the reviewer JavaScript into the note type, so
emptying ``read_web("review/render.js")`` here would install a note type whose
cards carry no renderer at all -- every card a bare image with no occlusion --
and the entire suite stayed green.

No Anki needed: ``gateways.py`` imports nothing from ``aqt``, and
``AnkiModelGateway`` only duck-types ``collection.models``, so the fakes already
written for ``test_gateways.py`` stand in for a collection.
"""

from __future__ import annotations

from dataclasses import replace

from randomized_occlusion.config.render_config import RenderConfig
from randomized_occlusion.notetype.factory import build_assembler, build_installer
from randomized_occlusion.notetype.spec import DEFAULT_SPEC

# tests/ is not a package, so this is a plain module import; pytest puts the
# test directory on sys.path.
from test_gateways import FakeCollection, SpyModels


def _rc() -> RenderConfig:
    return RenderConfig.from_mapping({})


#: A spec whose every name differs from DEFAULT_SPEC's, so a call that quietly
#: falls back to the default is visible rather than coincidentally right.
_CUSTOM = replace(
    DEFAULT_SPEC,
    name="Custom Occlusion",
    template_name="Custom Card",
    fields=("Pic", "Payload", "Ords", "Title", "Extra", "TypeFlag"),
    image_field="Pic",
    structures_field="Payload",
    cloze_field="Ords",
    header_field="Title",
    back_extra_field="Extra",
    type_flag_field="TypeFlag",
    sort_field="Title",
    collapsed_fields=("Pic", "Payload"),
)


def test_the_assembler_carries_the_bundled_reviewer_js():
    # Named internals of render.js, not markup like "ro-overlay": the <svg> and
    # its id are static template HTML and survive an EMPTY script perfectly well,
    # so asserting on them would pass for a note type carrying no renderer.
    front = build_assembler().assemble(_rc()).front
    for token in ("makeRng", "placeCenters", "boxBorderToward"):
        assert token in front, (
            f"the assembled front does not contain {token!r} from render.js; a "
            "note type installed from this would render every card as a plain "
            "image with no occlusion"
        )


def test_the_assembler_is_built_for_the_spec_it_is_given():
    front = build_assembler(_CUSTOM).assemble(_rc()).front
    assert "{{Pic}}" in front
    assert "{{" + DEFAULT_SPEC.image_field + "}}" not in front


def test_build_assembler_defaults_to_the_canonical_spec():
    front = build_assembler().assemble(_rc()).front
    assert "{{" + DEFAULT_SPEC.image_field + "}}" in front


def test_the_installer_is_bound_to_the_given_collection():
    models = SpyModels()
    build_installer(FakeCollection(models)).ensure_installed(_rc())
    assert len(models.added) == 1, "the note type was not created on this collection"
    assert models.added[0]["name"] == DEFAULT_SPEC.name


def test_the_installer_and_its_assembler_share_one_spec():
    # A mismatch here is the nastiest failure available in this file: the note
    # type would be created with one set of field names while its templates
    # referenced another, so every card would render empty fields.
    models = SpyModels()
    build_installer(FakeCollection(models), _CUSTOM).ensure_installed(_rc())
    created = models.added[0]

    assert created["name"] == _CUSTOM.name
    assert [f["name"] for f in created["flds"]] == list(_CUSTOM.fields)
    assert created["sortf"] == _CUSTOM.sort_index
    assert created["tmpls"][0]["name"] == _CUSTOM.template_name
    assert "{{Pic}}" in created["tmpls"][0]["qfmt"], (
        "the templates were assembled for a different spec than the note type"
    )
