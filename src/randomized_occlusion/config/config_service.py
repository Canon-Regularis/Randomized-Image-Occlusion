"""Reading and writing the add-on's configuration.

``ConfigService`` depends on a :class:`ConfigProvider` abstraction rather than on
Anki's ``addonManager`` directly, so it can be exercised with an in-memory
provider in tests. The service always returns a *complete* config by merging the
persisted values over :data:`DEFAULT_CONFIG`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Protocol

from ..domain.card_options import CardOptions
from .defaults import DEFAULT_CONFIG
from .render_config import RenderConfig

# The canvas clamps to the same range (see MIN_ZOOM/MAX_ZOOM in marker.js);
# these mirror it so a hand-edited config can never ask for a level the
# editor would silently refuse.
#: Distinguishes "the defaults say nothing about this key" from "the default
#: happens to be None", so an unrecognised key is never dropped as a duplicate.
_UNSET = object()

MIN_EDITOR_ZOOM = 1.0
MAX_EDITOR_ZOOM = 8.0
DEFAULT_EDITOR_ZOOM = 1.0

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
    """A provider backed by a plain dict, used in tests and headless contexts."""

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
        self._write_delta("deck", deck_name)

    def editor_zoom(self) -> float:
        """The zoom the marking canvas opens at, as a multiple of the fitted size.

        Total, like :meth:`RenderConfig.from_mapping`: a hand-edited config with
        a string, a NaN or an absurd number must not stop the editor opening, so
        anything unusable falls back to the fitted view.
        """
        return self._clamp_zoom(self.load().get("editor_zoom", DEFAULT_EDITOR_ZOOM))

    def set_editor_zoom(self, zoom: float) -> None:
        self._write_delta("editor_zoom", self._clamp_zoom(zoom))

    @staticmethod
    def _clamp_zoom(zoom: float) -> float:
        try:
            value = float(zoom)
        except (TypeError, ValueError):
            return DEFAULT_EDITOR_ZOOM
        if not math.isfinite(value):
            return DEFAULT_EDITOR_ZOOM
        return max(MIN_EDITOR_ZOOM, min(MAX_EDITOR_ZOOM, value))

    def _write_delta(self, key: str, value: Any) -> None:
        """Persist ``key``, and nothing that merely repeats a default.

        Writing back everything the provider hands over would bake today's
        DEFAULT_CONFIG into the user's saved config, so a later change to a
        default would never reach them. That is not hypothetical: Anki's
        ``getConfig()`` returns config.json's defaults already merged with the
        user's own values, so :class:`AnkiConfigProvider` always yields the full
        key set and a single write would freeze every key at once. Filtering here
        makes the behaviour the same whichever provider is in use.

        The trade-off is that Anki records no distinction between a key the user
        set to today's default and one they never set, so a value equal to the
        default is dropped and will move if that default later changes. That
        applies to ``key`` itself: setting something back to the shipped default
        removes it rather than pinning it. Keys the defaults say nothing about are
        always kept, since nothing here can tell what they mean.
        """
        stored = self._provider.get()
        config = dict(stored) if stored else {}
        config[key] = value
        self._provider.write(
            {
                name: setting
                for name, setting in config.items()
                if DEFAULT_CONFIG.get(name, _UNSET) != setting
            }
        )
