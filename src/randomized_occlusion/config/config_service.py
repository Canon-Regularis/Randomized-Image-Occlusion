"""Reading and writing the add-on's configuration.

``ConfigService`` depends on a :class:`ConfigProvider` abstraction rather than on
Anki's ``addonManager`` directly, so it can be exercised with an in-memory
provider in tests. The service always returns a *complete* config by merging the
persisted values over :data:`DEFAULT_CONFIG`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ..domain.card_options import CardOptions
from .defaults import DEFAULT_CONFIG
from .render_config import RenderConfig

__all__ = [
    "AnkiConfigProvider",
    "ConfigProvider",
    "ConfigService",
    "InMemoryConfigProvider",
]


class ConfigProvider(Protocol):
    """Persistence backend for the raw config dict."""

    def get(self) -> Mapping[str, Any] | None: ...

    def write(self, config: Mapping[str, Any]) -> None: ...


class InMemoryConfigProvider:
    """A provider backed by a plain dict — used in tests and headless contexts."""

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial) if initial else {}

    def get(self) -> Mapping[str, Any] | None:
        return dict(self._data)

    def write(self, config: Mapping[str, Any]) -> None:
        self._data = dict(config)


class AnkiConfigProvider:
    """A provider backed by Anki's per-add-on config store."""

    def __init__(self, addon_manager: Any, module_name: str) -> None:
        self._manager = addon_manager
        self._module = module_name

    def get(self) -> Mapping[str, Any] | None:
        return self._manager.getConfig(self._module)

    def write(self, config: Mapping[str, Any]) -> None:
        self._manager.writeConfig(self._module, dict(config))


class ConfigService:
    def __init__(self, provider: ConfigProvider) -> None:
        self._provider = provider

    def load(self) -> dict[str, Any]:
        """The effective config: persisted values merged over the defaults."""
        merged = dict(DEFAULT_CONFIG)
        stored = self._provider.get()
        if stored:
            merged.update(stored)
        return merged

    def render_config(self) -> RenderConfig:
        return RenderConfig.from_mapping(self.load())

    def editor_defaults(self) -> CardOptions:
        """The per-note options the editor dialog pre-selects."""
        return CardOptions.from_config(self.load())

    def deck(self) -> str:
        return str(self.load().get("deck", DEFAULT_CONFIG["deck"]))

    def set_deck(self, deck_name: str) -> None:
        config = self.load()
        config["deck"] = deck_name
        self._provider.write(config)
