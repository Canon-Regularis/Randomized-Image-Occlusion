"""Randomized Image Occlusion: an Anki add-on.

Standard image occlusion hides a label at a *fixed* spot, so learners tend to
memorise "the box in the top-left is the aorta" by position rather than truly
identifying the structure. This add-on instead places a prompt box at a
*randomised* location on every review and draws a leader-line arrow from it to
the structure's fixed location, forcing you to follow the arrow and identify
what it actually points at.

This module is the add-on entry point. To keep the package importable without
Anki present (so the domain/logic layers can be unit tested), all Anki wiring is
deferred to :mod:`bootstrap` and only runs when ``aqt`` is available.
"""

from __future__ import annotations

from ._version import __version__

__all__ = ["__version__"]

try:
    from aqt import mw as _mw
except ImportError:  # pragma: no cover - exercised only outside Anki (tests)
    _mw = None

if _mw is not None:  # pragma: no cover - exercised only inside Anki
    from . import bootstrap

    bootstrap.setup(__name__)
