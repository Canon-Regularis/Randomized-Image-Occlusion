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
        template = self._assembler.assemble(render_config)

        existing = self._gateway.find(self._spec.name)
        if existing is None:
            self._gateway.create_cloze_notetype(
                name=self._spec.name,
                fields=self._spec.fields,
                sort_index=self._spec.sort_index,
                template_name=self._spec.template_name,
                front=template.front,
                back=template.back,
                css=template.css,
                collapsed_fields=self._spec.collapsed_fields,
            )
            return InstallResult.CREATED

        # Migrate (all mutate ``existing`` in place):
        #   * add any fields introduced by newer versions;
        #   * collapse the machine fields so the Add window stays clean; this is
        #     idempotent, so an existing install gets it once and then no-ops.
        fields_changed = self._gateway.ensure_fields(existing, self._spec.fields)
        collapse_changed = self._gateway.collapse_fields(
            existing, self._spec.collapsed_fields
        )
        sort_changed = self._ensure_sort_field(existing)
        templates_stale = (
            extract_fingerprint(existing.get("css", "")) != template.fingerprint
        )

        if fields_changed or collapse_changed or sort_changed or templates_stale:
            # update_templates persists the whole dict, including the mutations
            # above (added fields and collapse state). When only the collapse
            # state changed, the freshly assembled strings are byte-identical to
            # what's stored (same fingerprint), so re-assigning them is merely
            # part of persisting the field mutation: one persistence path.
            self._gateway.update_templates(
                existing, front=template.front, back=template.back, css=template.css
            )
            return InstallResult.UPDATED

        return InstallResult.UNCHANGED

    def _ensure_sort_field(self, notetype: dict) -> bool:
        """Point ``sortf`` at the spec's sort field. True if it had to move.

        ``sortf`` is an *index* into the field list, and ``ensure_fields``
        appends, so a field that had been removed comes back at the end rather
        than in its old slot. The stored index then refers to whatever moved into
        that slot, and the browser sorts on the wrong field with nothing to say
        so.

        Located by name, not by ``spec.sort_index``: after such a migration the
        field really is somewhere else, so re-asserting the declared index would
        point at the wrong field just as surely as leaving it alone.

        Checked on every run rather than only when the field list changed, so an
        install already carrying a stale index is repaired instead of staying
        that way. The cost is that a sort field chosen by hand in Anki is put
        back, and that a *renamed* sort field is abandoned in favour of the empty
        one ``ensure_fields`` re-adds, leaving the Browse column blank. Renaming
        it already breaks the add-on, which addresses fields by name, so that
        note type needs repairing either way.
        """
        names = [field.get("name") for field in notetype.get("flds", [])]
        if self._spec.sort_field not in names:
            return False  # ensure_fields adds it; nothing sensible to point at
        wanted = names.index(self._spec.sort_field)
        if notetype.get("sortf") == wanted:
            return False
        notetype["sortf"] = wanted
        return True
