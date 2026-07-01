"""Construction helpers for the note type's assembler and installer.

Both the profile-load hook (``bootstrap``) and the create-note op need a
:class:`NoteTypeInstaller` wired with the same recipe (this spec + this
renderer JS). Centralising that construction here removes the duplication and
gives one place to change how the note type is assembled.
"""

from __future__ import annotations

from typing import Any

from ..collection.gateways import AnkiModelGateway
from ..resources import read_web
from .installer import NoteTypeInstaller
from .spec import DEFAULT_SPEC, NoteTypeSpec
from .templates import TemplateAssembler

__all__ = ["build_assembler", "build_installer"]


def build_assembler(spec: NoteTypeSpec = DEFAULT_SPEC) -> TemplateAssembler:
    """A :class:`TemplateAssembler` loaded with the bundled reviewer JS."""
    return TemplateAssembler(spec, read_web("review/render.js"))


def build_installer(
    collection: Any, spec: NoteTypeSpec = DEFAULT_SPEC
) -> NoteTypeInstaller:
    """A :class:`NoteTypeInstaller` bound to ``collection``'s models."""
    return NoteTypeInstaller(AnkiModelGateway(collection), build_assembler(spec), spec)
