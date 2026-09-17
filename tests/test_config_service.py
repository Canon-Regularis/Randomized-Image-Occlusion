from __future__ import annotations

import json
import re
from pathlib import Path

import randomized_occlusion
from randomized_occlusion.config.config_service import (
    MAX_EDITOR_ZOOM,
    MIN_EDITOR_ZOOM,
    ConfigService,
    InMemoryConfigProvider,
)
from randomized_occlusion.config.defaults import DEFAULT_CONFIG
from randomized_occlusion.config.render_config import RenderConfig
from randomized_occlusion.resources import read_web


def test_default_config_matches_shipped_config_json():
    # DEFAULT_CONFIG (used headlessly / in tests) mirrors config.json by hand, so
    # a test must lock the two together or they silently drift out of sync.
    path = Path(randomized_occlusion.__file__).parent / "config.json"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == DEFAULT_CONFIG


def test_load_merges_over_defaults():
    service = ConfigService(InMemoryConfigProvider({"deck": "Anatomy"}))
    config = service.load()
    assert config["deck"] == "Anatomy"
    assert config["prompt_text"] == DEFAULT_CONFIG["prompt_text"]


def test_load_with_empty_provider_returns_defaults():
    service = ConfigService(InMemoryConfigProvider())
    assert service.load() == DEFAULT_CONFIG


def test_set_deck_persists_and_preserves_other_keys():
    provider = InMemoryConfigProvider({"accent_color": "#000000"})
    service = ConfigService(provider)
    service.set_deck("Biology")
    assert service.deck() == "Biology"
    assert service.load()["accent_color"] == "#000000"


def test_set_deck_persists_only_the_delta_not_frozen_defaults():
    # set_deck must store only the changed keys, so keys the user never set keep
    # tracking DEFAULT_CONFIG. If it wrote the full merged config, a later change
    # to a default would never reach the user (their frozen copy would win).
    provider = InMemoryConfigProvider()
    ConfigService(provider).set_deck("Biology")
    assert provider.get() == {"deck": "Biology"}  # only the delta was persisted


def test_a_provider_that_returns_the_defaults_does_not_freeze_them():
    # This is the shape Anki actually hands back: getConfig() returns config.json
    # merged with the user's own values, so the full key set arrives every time.
    # Seeding the fake with an empty dict, as the test above does, is the one
    # case where writing everything back would look correct.
    provider = InMemoryConfigProvider(dict(DEFAULT_CONFIG))
    ConfigService(provider).set_deck("Biology")
    assert provider.get() == {"deck": "Biology"}


def test_a_value_the_user_changed_survives_a_write_to_another_key():
    provider = InMemoryConfigProvider({**DEFAULT_CONFIG, "accent_color": "#abcdef"})
    ConfigService(provider).set_editor_zoom(2.0)
    assert provider.get() == {"accent_color": "#abcdef", "editor_zoom": 2.0}


def test_writing_a_key_back_to_its_default_stops_pinning_it():
    # Not a special case of the key being written: pinning it would freeze that
    # one key at today's default, which is the whole failure this filtering
    # exists to prevent. The effective value is the default either way.
    provider = InMemoryConfigProvider({"deck": "Biology"})
    service = ConfigService(provider)
    service.set_deck(DEFAULT_CONFIG["deck"])
    assert provider.get() == {}
    assert service.deck() == DEFAULT_CONFIG["deck"]


def test_an_unrecognised_key_is_never_dropped():
    # A key the defaults say nothing about may belong to a newer version of the
    # add-on running on the same profile; discarding it would lose that setting.
    #
    # Its value is None on purpose. The filter asks whether the key's value
    # differs from its default, and a missing default has to be represented by
    # something no real value can equal. With None as that marker this key would
    # compare equal to its own absent default and be silently dropped, so this is
    # what makes the sentinel load-bearing rather than decorative.
    provider = InMemoryConfigProvider({"from_a_future_version": None})
    ConfigService(provider).set_deck("Biology")
    assert provider.get() == {"from_a_future_version": None, "deck": "Biology"}


def test_render_config_is_built_from_effective_config():
    service = ConfigService(InMemoryConfigProvider({"min_arrow_fraction": 0.4}))
    assert service.render_config().min_arrow_fraction == 0.4


def test_editor_defaults_come_from_config():
    from randomized_occlusion.domain.card_options import CardMode, Direction

    service = ConfigService(
        InMemoryConfigProvider({"card_mode": "single", "direction": "both"})
    )
    defaults = service.editor_defaults()
    assert defaults.mode is CardMode.SINGLE
    assert defaults.direction is Direction.BOTH


def test_editor_zoom_defaults_to_the_fitted_view():
    assert ConfigService(InMemoryConfigProvider()).editor_zoom() == 1.0


def test_a_hand_edited_zoom_is_clamped_when_it_is_read():
    # config.json is user-editable, so an absurd level must be tamed on the way
    # in, not only when the editor writes one back.
    assert ConfigService(InMemoryConfigProvider({"editor_zoom": 500})).editor_zoom() == 8.0
    assert ConfigService(InMemoryConfigProvider({"editor_zoom": -4})).editor_zoom() == 1.0


def test_a_nonsense_zoom_is_refused_on_the_way_out_too():
    # Every one of these clamps to the default, and a value equal to the default
    # is not persisted at all. What matters is that nothing unusable reaches the
    # store and the canvas still opens at a sane level.
    for junk in (float("nan"), float("inf"), None, "wide", [1]):
        provider = InMemoryConfigProvider()
        service = ConfigService(provider)
        service.set_editor_zoom(junk)
        assert "editor_zoom" not in provider.get(), junk
        assert service.editor_zoom() == 1.0, junk


def test_an_out_of_range_zoom_is_clamped_on_the_way_out():
    # A level that clamps to something OTHER than the default, so the clamped
    # value is genuinely written and the clamp is observable in the store rather
    # than only on the way back out.
    provider = InMemoryConfigProvider()
    ConfigService(provider).set_editor_zoom(99)
    assert provider.get() == {"editor_zoom": MAX_EDITOR_ZOOM}


def test_editor_zoom_round_trips():
    service = ConfigService(InMemoryConfigProvider())
    service.set_editor_zoom(3.25)
    assert service.editor_zoom() == 3.25


def test_editor_zoom_is_clamped_to_the_range_the_canvas_supports():
    service = ConfigService(InMemoryConfigProvider())
    service.set_editor_zoom(500)
    assert service.editor_zoom() == 8.0
    service.set_editor_zoom(0.01)
    assert service.editor_zoom() == 1.0


def test_hand_edited_editor_zoom_falls_back_instead_of_raising():
    # Reading config is total: a hand-edited value must not stop the editor
    # opening, however silly it is. The huge integers are not academic -- JSON
    # carries them happily and float() raises OverflowError, not ValueError, so
    # they escaped the original except clause and the dialog could never be
    # opened again.
    for stored in ("wide", None, float("nan"), float("inf"), [1], 10**400, -(10**400)):
        service = ConfigService(InMemoryConfigProvider({"editor_zoom": stored}))
        assert service.editor_zoom() == 1.0, f"editor_zoom={stored!r} did not fall back"


def test_setting_editor_zoom_writes_only_the_delta():
    # Same contract as set_deck: writing the merged config would bake today's
    # defaults into the user's file and freeze them there.
    provider = InMemoryConfigProvider()
    ConfigService(provider).set_editor_zoom(2.0)
    assert provider.get() == {"editor_zoom": 2.0}


def test_the_zoom_range_matches_the_canvas():
    # config_service and marker.js each declare the range, in different
    # languages, and a comment asserts they agree. Two files that must move
    # together need a test that fails when only one of them does.
    marker_js = read_web("editor/marker.js")
    declared = dict(re.findall(r"var (MIN_ZOOM|MAX_ZOOM) = ([\d.]+);", marker_js))
    assert declared, "could not find the zoom range in marker.js"
    assert float(declared["MIN_ZOOM"]) == MIN_EDITOR_ZOOM
    assert float(declared["MAX_ZOOM"]) == MAX_EDITOR_ZOOM


#: ``render.js``'s own copy of the behaviour defaults, as source text. Anchored
#: on the exact declaration, so a rename fails loudly rather than silently
#: matching nothing.
_JS_DEFAULTS_RE = re.compile(r"\n  var DEFAULT_CONFIG = \{\n(.*?)\n  \};\n", re.DOTALL)


def _render_js_defaults() -> dict:
    source = read_web("review/render.js")
    match = _JS_DEFAULTS_RE.search(source)
    assert match, "render.js no longer declares DEFAULT_CONFIG where this test reads it"
    body = re.sub(r"//.*", "", match.group(1))
    return {
        key: json.loads(raw.strip())
        for key, raw in re.findall(r"(\w+):\s*([^,]+),", body)
    }


def test_the_reviewers_fallback_config_matches_the_shipped_defaults():
    # The fourth copy of these values, and the only one nothing checked. It is
    # what a card renders with when its #ro-config blob is missing -- a note type
    # installed by an older version, or a template a user stripped -- which is
    # the one path no other test covers. Drift here shows up as cards that behave
    # differently from every setting on the config screen.
    expected = RenderConfig.from_mapping(DEFAULT_CONFIG).behaviour()
    assert _render_js_defaults() == expected
