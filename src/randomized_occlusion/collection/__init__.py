"""Adapters and factories bridging the domain model to Anki's collection."""

from __future__ import annotations

from .gateways import (
    AnkiMediaGateway,
    AnkiModelGateway,
    ModelGateway,
)
from .note_factory import NoteContent, NoteFactory

__all__ = [
    "AnkiMediaGateway",
    "AnkiModelGateway",
    "ModelGateway",
    "NoteContent",
    "NoteFactory",
]
