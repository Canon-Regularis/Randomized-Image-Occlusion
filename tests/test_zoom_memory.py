from __future__ import annotations

from randomized_occlusion.config.config_service import ConfigService, InMemoryConfigProvider
from randomized_occlusion.editor.zoom_memory import ZoomMemory


def _memory(stored=None):
    provider = InMemoryConfigProvider(stored or {})
    return ZoomMemory(ConfigService(provider)), provider


def test_opening_level_comes_from_config():
    memory, _ = _memory({"editor_zoom": 2.5})
    assert memory.opening_level == 2.5


def test_opening_level_defaults_to_fit():
    memory, _ = _memory()
    assert memory.opening_level == 1.0


def test_commit_without_change_writes_nothing():
    # If merely opening the editor materialised the key, that user's config
    # would be frozen against any later change to the default.
    memory, provider = _memory()
    memory.commit()
    assert provider.get() == {}


def test_commit_persists_the_recorded_level():
    memory, provider = _memory()
    memory.record(3.25)
    memory.commit()
    assert provider.get()["editor_zoom"] == 3.25


def test_commit_after_returning_to_the_opening_level_writes_nothing():
    memory, provider = _memory({"editor_zoom": 2.0})
    before = provider.get()
    memory.record(5.0)
    memory.record(2.0)  # the user thought better of it
    memory.commit()
    assert provider.get() == before


def test_commit_persists_only_the_last_recorded_level():
    memory, provider = _memory()
    for level in (1.5, 2.0, 4.0, 3.0):
        memory.record(level)
    memory.commit()
    assert provider.get()["editor_zoom"] == 3.0


def test_commit_clamps_before_writing():
    memory, provider = _memory()
    memory.record(500.0)
    memory.commit()
    assert provider.get()["editor_zoom"] == 8.0


def test_second_commit_writes_nothing():
    memory, provider = _memory()
    memory.record(2.0)
    memory.commit()
    provider.write({})  # anything written after the first commit is a second write
    memory.commit()
    assert provider.get() == {}


def test_commit_preserves_other_config_keys():
    memory, provider = _memory({"deck": "Anatomy"})
    memory.record(2.0)
    memory.commit()
    assert provider.get() == {"deck": "Anatomy", "editor_zoom": 2.0}


def test_commit_swallows_a_provider_error():
    # This runs from the dialog's close handler; raising would leave the dialog
    # half-torn-down.
    class Refuses:
        def editor_zoom(self):
            return 1.0

        def set_editor_zoom(self, zoom):
            raise RuntimeError("the profile went away")

    memory = ZoomMemory(Refuses())
    memory.record(4.0)
    memory.commit()
