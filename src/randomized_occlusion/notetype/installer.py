"""Idempotent installation/upgrade of the note type."""

from __future__ import annotations

import enum

from ..collection.gateways import ModelGateway
from ..config.render_config import RenderConfig
from .spec import NoteTypeSpec
from .templates import TemplateAssembler, extract_fingerprint, fingerprint_of

__all__ = ["InstallResult", "NoteTypeInstaller"]


class InstallResult(enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    #: The stored template is not the one we last wrote, so it was left alone.
    CUSTOMISED = "customised"
    #: A field the note type was created with is gone; nothing was written.
    FIELDS_MISSING = "fields-missing"


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

        if self.missing_required_fields(existing):
            # A field the note type was CREATED with is gone, so this cannot be
            # an old install waiting to be migrated. It was renamed or deleted
            # in Anki, and the migration below would append an empty field of
            # that name -- which the templates then render, blanking it on every
            # note while the real content sits in the renamed field, referenced
            # by nothing. Renaming it back restores everything, so the useful
            # thing to do is write nothing and say so.
            return InstallResult.FIELDS_MISSING

        # Migrate (all mutate ``existing`` in place):
        #   * add any fields introduced by newer versions;
        #   * collapse the machine fields so the Add window stays clean; this is
        #     idempotent, so an existing install gets it once and then no-ops.
        fields_changed = self._gateway.ensure_fields(existing, self._spec.fields)
        collapse_changed = self._gateway.collapse_fields(
            existing, self._spec.collapsed_fields
        )
        sort_changed = self._ensure_sort_field(existing)
        stored_css = existing.get("css", "")
        templates_stale = extract_fingerprint(stored_css) != template.fingerprint

        if self._is_customised(existing, stored_css):
            # Somebody has edited the card template or its CSS in Anki's Card
            # Types screen. Rewriting it would destroy that silently -- no
            # warning, no backup, no undo entry -- so the strings are left
            # exactly as they are and the caller is told why. The field and
            # collapse migrations above still have to be persisted, which is
            # what passing the STORED strings back does.
            if fields_changed or collapse_changed or sort_changed:
                first = (existing.get("tmpls") or [{}])[0]
                self._gateway.update_templates(
                    existing,
                    front=first.get("qfmt", ""),
                    back=first.get("afmt", ""),
                    css=stored_css,
                )
            return InstallResult.CUSTOMISED

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

    def missing_required_fields(self, notetype: dict) -> tuple[str, ...]:
        """Which of the spec's required fields this note type no longer has."""
        names = {field.get("name") for field in notetype.get("flds", [])}
        return tuple(name for name in self._spec.required_fields if name not in names)

    def _is_customised(self, notetype: dict, stored_css: str) -> bool:
        """Whether the stored template differs from the one we last wrote.

        The fingerprint in the CSS is a hash of the three strings that shipped
        with it, so re-hashing what is actually stored and comparing settles it
        without keeping a second copy anywhere.

        A note type with no marker at all predates the fingerprint, or had its
        CSS replaced wholesale; treated as NOT customised, because refusing to
        update every such install would strand them on an old renderer for good.
        """
        marker = extract_fingerprint(stored_css)
        if marker is None:
            return False
        first = (notetype.get("tmpls") or [{}])[0]
        return (
            fingerprint_of(first.get("qfmt", ""), first.get("afmt", ""), stored_css)
            != marker
        )

    def _ensure_sort_field(self, notetype: dict) -> bool:
        """Point ``sortf`` at the spec's sort field. True if it had to move.

        ``sortf`` is an *index* into the field list, so anything that moves a
        field leaves it pointing at whatever slid into that slot, and the browser
        sorts on the wrong field with nothing to say so. Repositioning fields in
        Anki does exactly that, as does appending a field an older install lacks.

        Located by name, not by ``spec.sort_index``: after such a move the field
        really is somewhere else, so re-asserting the declared index would point
        at the wrong field just as surely as leaving it alone.

        Checked on every run rather than only when the field list changed, so an
        install already carrying a stale index is repaired instead of staying
        that way. The cost is that a sort field chosen by hand in Anki is put
        back on the next profile open. A *renamed* sort field is not this
        function's problem: ``ensure_installed`` refuses the whole note type
        before reaching here, because appending the empty replacement is what
        would blank the Browse column.
        """
        names = [field.get("name") for field in notetype.get("flds", [])]
        if self._spec.sort_field not in names:
            return False  # ensure_fields adds it; nothing sensible to point at
        wanted = names.index(self._spec.sort_field)
        if notetype.get("sortf") == wanted:
            return False
        notetype["sortf"] = wanted
        return True
