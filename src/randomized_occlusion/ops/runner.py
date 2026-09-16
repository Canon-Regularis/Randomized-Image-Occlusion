"""Shared wiring for the note-mutating ``CollectionOp``s.

The add and edit ops differ only in how they resolve the image and how they write
the note. Everything around that (launching the op off the UI thread, the
fallible prelude that must precede any undo entry, and opening/merging that
entry) is identical, so it lives here once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..collection.note_factory import NoteContent, NoteFactory
from ..config.render_config import RenderConfig
from ..domain.card_options import CardOptions
from ..domain.structure_set import StructureSet
from ..notetype.factory import build_installer
from ..notetype.installer import InstallResult
from ..notetype.spec import NoteTypeSpec

__all__ = ["commit_with_undo", "prepare_content", "run_note_op"]


def run_note_op(
    *,
    parent: Any,
    op: Callable[[Any], Any],
    on_success: Callable[[Any], None] | None,
    on_failure: Callable[[Exception], None] | None = None,
) -> None:
    # Imported here rather than at module scope so this module, and the savers
    # and note ops that import it, can be imported without Anki present. That is
    # the only thing that made them untestable: `aqt` does not exist in the test
    # environment, so one module-level import put ~230 lines of save logic beyond
    # the reach of every test.
    from aqt.operations import CollectionOp

    operation = CollectionOp(parent=parent, op=op)
    if on_success is not None:
        operation = operation.success(on_success)
    if on_failure is not None:
        operation = operation.failure(on_failure)
    operation.run_in_background()


def prepare_content(
    col: Any,
    *,
    spec: NoteTypeSpec,
    render_config: RenderConfig,
    resolve_image: Callable[[Any], str],
    structures: StructureSet,
    options: CardOptions,
    header: str,
    back_extra: str,
    header_html: str | None = None,
    back_extra_html: str | None = None,
) -> NoteContent:
    """Build a note's field values: the fallible prelude both note ops share.

    Two steps here can fail on external state, and both MUST happen before
    :func:`commit_with_undo` opens a custom undo entry, or the failure would
    strand a half-open entry and corrupt Anki's undo queue:

    * ``ensure_installed`` may add or update the note type, a schema change that
      clears the undo queue outright (normally a no-op; bootstrap installs the
      note type at profile open); and
    * ``resolve_image`` may import a file the user has since moved or deleted.

    Callers keep their *own* fallible work (looking up the deck, loading the note)
    before ``commit_with_undo`` for the same reason; only the write is wrapped.
    """
    installer = build_installer(col, spec)
    if installer.ensure_installed(render_config) is InstallResult.FIELDS_MISSING:
        # Writing the note would put its content into fields the templates no
        # longer reference. Setting note[name] would raise a KeyError a moment
        # later anyway -- both ops do that before commit_with_undo, so the undo
        # queue was never at risk -- but a KeyError names nothing a user can act
        # on. This names the field that is gone and how to bring it back.
        missing = installer.missing_required_fields(
            col.models.by_name(spec.name) or {}
        )
        raise RuntimeError(
            f"the note type {spec.name!r} no longer has the field "
            f"{', '.join(repr(name) for name in missing)}. It was renamed or "
            "removed in Tools > Manage Note Types > Fields; restoring the "
            "original name brings the existing cards back, because their "
            "content is still there under the new name."
        )
    return NoteFactory(spec).build(
        image_filename=resolve_image(col),
        structures=structures,
        options=options,
        header=header,
        back_extra=back_extra,
        header_html=header_html,
        back_extra_html=back_extra_html,
    )


def commit_with_undo(col: Any, name: str, write: Callable[[], None]) -> Any:
    """Run ``write`` wrapped in a custom undo entry so the change collapses into
    one undo step, returning the ``OpChanges`` to hand back to ``CollectionOp``.

    The caller MUST have already done everything that can fail on external state
    (importing media, loading the note, a schema-changing install) BEFORE calling
    this: a failure between opening the entry and merging it would leave a
    half-open entry that corrupts Anki's undo queue. See :func:`prepare_content`.
    """
    undo_position = col.add_custom_undo_entry(name)
    write()
    return col.merge_undo_entries(undo_position)
