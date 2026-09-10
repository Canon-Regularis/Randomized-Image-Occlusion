"""The mutation catalogue still matches the code it claims to mutate.

Running the campaign itself takes about half a minute; these checks take
milliseconds and catch the failure mode that actually happens; the source moves
on and an anchor silently stops matching, so a mutation that used to prove
something now proves nothing. ``mutate.py`` reports that as ``ANCHOR MISSING``,
but only if somebody runs it. This makes the ordinary suite notice.

``mutate.py`` lives at the repo root (not in the ``src`` package), so it is
loaded by path, the same way ``test_build.py`` loads the packaging script.

The harness self-check (a no-op mutation must survive, or every result for that
target is a false kill) lives in ``mutate.py`` and runs before each campaign. It
is not repeated here: it costs a subprocess per target, and it only matters when
a campaign is actually being run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load_mutate():
    spec = importlib.util.spec_from_file_location("_ro_mutate", _ROOT / "mutate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before executing: @dataclass resolves annotations through
    # sys.modules, and fails on a module that is not there yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_mutate = _load_mutate()
_MUTATIONS = _mutate.MUTATIONS


def _source_of(target) -> str:
    # Anchors are written with LF; the tree may be checked out with CRLF.
    return (_ROOT / target.source).read_text(encoding="utf-8").replace("\r\n", "\n")


def _listing(offenders: list[str]) -> str:
    bullet = chr(10) + "  - "
    return bullet + bullet.join(offenders)


def test_anchors_match_their_source():
    missing = [
        f"{m.label}  ({m.target.source})"
        for m in _MUTATIONS
        if m.before not in _source_of(m.target)
    ]
    assert not missing, (
        "these mutations no longer match the code they claim to break; update the "
        f"anchors in mutate.py, or drop them if the behaviour is gone:{_listing(missing)}"
    )


def test_mutations_change_something():
    inert = [m.label for m in _MUTATIONS if m.before == m.after]
    assert not inert, f"these mutations replace code with itself:{_listing(inert)}"


def test_anchors_are_unambiguous():
    # str.replace(..., 1) takes the first match, so a repeated anchor mutates
    # whichever copy comes first, and quietly stops testing the one that was
    # meant. This has caught three mislabelled entries already.
    ambiguous = [
        f"{m.label}  ({_source_of(m.target).count(m.before)}x in {m.target.source})"
        for m in _MUTATIONS
        if _source_of(m.target).count(m.before) != 1
    ]
    assert not ambiguous, (
        f"these anchors do not identify one place; make them specific:{_listing(ambiguous)}"
    )


def test_labels_are_unique():
    labels = [m.label for m in _MUTATIONS]
    duplicates = {label for label in labels if labels.count(label) > 1}
    assert not duplicates, f"the filter and the report identify mutations by label: {duplicates}"


def test_declared_survivors_have_a_reason():
    for mutation in _MUTATIONS:
        if mutation.survives:
            assert mutation.why.strip(), (
                f"{mutation.label!r} is marked as knowingly untested; say why, so the "
                "next reader can judge whether it still holds."
            )


def test_targets_reference_existing_files():
    for target in {m.target for m in _MUTATIONS}:
        assert (_ROOT / target.source).is_file(), target.source
        assert target.tests, f"{target.source} names no suite"
        for suite in target.tests:
            assert (_ROOT / suite).is_file(), suite


def test_every_declared_target_has_a_mutation():
    # Enumerated from the module's own Target constants, not from _MUTATIONS: a
    # target set derived from the mutations trivially has a mutation for each of
    # its members, so the check could never fail. What is worth catching is a
    # declared target whose last mutation was deleted rather than updated.
    declared = {
        name: value
        for name, value in vars(_mutate).items()
        if isinstance(value, _mutate.Target)
    }
    assert declared, "no Target constants found; has mutate.py been restructured?"
    covered = {m.target for m in _MUTATIONS}
    orphans = sorted(name for name, target in declared.items() if target not in covered)
    assert not orphans, (
        "these targets are declared but nothing mutates them, so nothing they "
        f"claim to cover is being checked:{_listing(orphans)}"
    )


def test_every_mutant_parses():
    # A mutant with a syntax error fails every test in its suite for a reason
    # that has nothing to do with coverage, and the runner scores that as a kill.
    # Two entries did exactly that, both by deleting the consequent of an `if`.
    #
    # Checking the JavaScript half needs node, which the Python suite does not
    # otherwise require, so this is skipped rather than failed where node is
    # absent. `python mutate.py` runs the same check and does need node.
    import shutil

    if shutil.which(_mutate._node()) is None:
        pytest.skip("node is not installed; mutate.py's own run covers this")
    unparsable = [f"{label}: {error}" for label, error in _mutate.precheck(_MUTATIONS)]
    assert not unparsable, (
        "these mutants are not valid code, so killing them proves nothing; "
        f"rewrite them to stay syntactically whole:{_listing(unparsable)}"
    )

