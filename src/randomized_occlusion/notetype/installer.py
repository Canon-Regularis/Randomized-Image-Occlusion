"""Idempotent installation/upgrade of the note type."""

from __future__ import annotations

import enum

from ..collection.gateways import ModelGateway
from ..config.render_config import RenderConfig
from .spec import NoteTypeSpec
from .templates import TemplateAssembler, extract_fingerprint

__all__ = ["InstallResult", "NoteTypeInstaller"]


class InstallResult(enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


class NoteTypeInstaller:
    """Ensures the note type exists and is current.

    The decision logic (create vs. update vs. leave alone) lives here and is
    fully testable against a fake :class:`ModelGateway`; the actual mutation of
    Anki's note-type dicts is delegated to the gateway.
    """

    def __init__(
        self,
        gateway: ModelGateway,
        assembler: TemplateAssembler,
        spec: NoteTypeSpec,
    ) -> None:
        self._gateway = gateway
        self._assembler = assembler
        self._spec = spec

    def ensure_installed(self, render_config: RenderConfig) -> InstallResult:
        front = self._assembler.front(render_config)
        back = self._assembler.back()
        css = self._assembler.css(render_config)
        fingerprint = self._assembler.fingerprint(render_config)

        existing = self._gateway.find(self._spec.name)
        if existing is None:
            self._gateway.create_cloze_notetype(
                name=self._spec.name,
                fields=self._spec.fields,
                sort_index=self._spec.sort_index,
                template_name=self._spec.template_name,
                front=front,
                back=back,
                css=css,
            )
            return InstallResult.CREATED

        # Migrate: add any fields introduced by newer versions (mutates in place).
        fields_changed = self._gateway.ensure_fields(existing, self._spec.fields)
        templates_stale = extract_fingerprint(existing.get("css", "")) != fingerprint

        if fields_changed or templates_stale:
            # update_templates persists the whole dict, including added fields.
            self._gateway.update_templates(
                existing, front=front, back=back, css=css
            )
            return InstallResult.UPDATED

        return InstallResult.UNCHANGED
