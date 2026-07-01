from __future__ import annotations

from randomized_occlusion.config.config_service import (
    ConfigService,
    InMemoryConfigProvider,
)
from randomized_occlusion.config.defaults import DEFAULT_CONFIG


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
