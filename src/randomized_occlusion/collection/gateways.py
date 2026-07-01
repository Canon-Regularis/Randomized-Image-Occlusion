"""Thin adapters (gateways) over Anki's collection APIs.

These exist to invert the dependency between our logic and Anki: the installer
and ops depend on the small ``Protocol`` interfaces declared here, not on
``col.models`` / ``col.media`` directly. That keeps the logic unit-testable with
in-memory fakes (Liskov-substitutable for the real gateways) and confines all
knowledge of Anki's mutable-dict note-type API to one place.

Only the ``Anki*`` implementations touch Anki; importing this module does not
import ``anki``/``aqt``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "AnkiMediaGateway",
    "AnkiModelGateway",
    "MediaGateway",
    "ModelGateway",
    "NotetypeDict",
]

# A note type is represented by Anki as a plain mutable dict.
NotetypeDict = dict[str, Any]


@runtime_checkable
class ModelGateway(Protocol):
    """Create/find/update note types."""

    def find(self, name: str) -> NotetypeDict | None: ...

    def create_cloze_notetype(
        self,
        *,
        name: str,
        fields: tuple[str, ...],
        sort_index: int,
        template_name: str,
        front: str,
        back: str,
        css: str,
    ) -> None: ...

    def update_templates(
        self, notetype: NotetypeDict, *, front: str, back: str, css: str
    ) -> None: ...

    def ensure_fields(
        self, notetype: NotetypeDict, field_names: tuple[str, ...]
    ) -> bool:
        """Add any missing fields to ``notetype`` in place; return whether it
        changed (the caller persists)."""
        ...


@runtime_checkable
class MediaGateway(Protocol):
    """Copy images into the collection's media store."""

    def add_image(self, path: str) -> str:
        """Return the (possibly renamed) basename the image is stored under."""
        ...


# --------------------------------------------------------------------------- #
# Anki-backed implementations                                                  #
# --------------------------------------------------------------------------- #


class AnkiModelGateway:
    """``ModelGateway`` backed by ``col.models`` (the ``ModelManager``)."""

    def __init__(self, collection: Any) -> None:
        self._models = collection.models

    def find(self, name: str) -> NotetypeDict | None:
        return self._models.by_name(name)

    def create_cloze_notetype(
        self,
        *,
        name: str,
        fields: tuple[str, ...],
        sort_index: int,
        template_name: str,
        front: str,
        back: str,
        css: str,
    ) -> None:
        models = self._models
        notetype = models.new(name)
        notetype["type"] = 1  # 1 == cloze (see proto NotetypeKind; no Py const)
        for field_name in fields:
            models.add_field(notetype, models.new_field(field_name))
        template = models.new_template(template_name)
        template["qfmt"] = front
        template["afmt"] = back
        models.add_template(notetype, template)
        notetype["css"] = css
        notetype["sortf"] = sort_index
        models.add_dict(notetype)

    def update_templates(
        self, notetype: NotetypeDict, *, front: str, back: str, css: str
    ) -> None:
        template = notetype["tmpls"][0]
        template["qfmt"] = front
        template["afmt"] = back
        notetype["css"] = css
        self._models.update_dict(notetype)

    def ensure_fields(
        self, notetype: NotetypeDict, field_names: tuple[str, ...]
    ) -> bool:
        existing = {field["name"] for field in notetype["flds"]}
        changed = False
        for name in field_names:
            if name not in existing:
                self._models.add_field(notetype, self._models.new_field(name))
                changed = True
        return changed


class AnkiMediaGateway:
    """``MediaGateway`` backed by ``col.media``."""

    def __init__(self, collection: Any) -> None:
        self._media = collection.media

    def add_image(self, path: str) -> str:
        return self._media.add_file(path)
