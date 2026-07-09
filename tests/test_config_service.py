from __future__ import annotations

import json
from pathlib import Path

import randomized_occlusion
from randomized_occlusion.config.config_service import (
    ConfigService,
    InMemoryConfigProvider,
)
from randomized_occlusion.config.defaults import DEFAULT_CONFIG


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
