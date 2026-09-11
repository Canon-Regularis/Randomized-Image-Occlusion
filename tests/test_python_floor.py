"""Every shipped module imports on the oldest Python the add-on claims to run on.

Anki bundles its own interpreter, and it shipped Python 3.9.18 from 23.10 (this
add-on's ``min_point_version``) until 25.07, the first release on 3.13. Anything
newer than 3.9 in the shipped package therefore breaks the add-on on every Anki
in between, at *load* time: ``__init__`` imports ``bootstrap``, which reaches
``config_service`` and ``notetype.factory``.

That is not hypothetical. ``@dataclass(slots=True)`` is 3.10+, was used in 13
modules, and made the add-on unloadable on its own declared minimum for the
project's whole history. Nothing caught it: the CI matrix started at 3.10, and
``slots`` is a runtime keyword argument, so parsing the file at any
``feature_version`` accepts it.

So this file imports every module rather than parsing it. Executing the module
body is what runs the class definitions, and that is where a construct newer than
the floor actually raises. Run on 3.9 (the CI ``check`` job) it is the guard; run
on a newer interpreter it still pins which modules belong to the Qt layer.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import randomized_occlusion

_PACKAGE = "randomized_occlusion"
_ROOT = Path(randomized_occlusion.__file__).parent

#: Import failures naming one of these are the Qt layer, not a floor violation.
_ANKI_ROOTS = frozenset({"aqt", "anki", "PyQt6"})

#: The modules that cannot be imported without Anki present, directly or through
#: something they import. Pinned as an exact set, not a count: a module that
#: joins it has moved logic into the Qt layer, where no test can reach it, and a
#: module that leaves it is newly testable and should be given tests.
_NEEDS_ANKI = frozenset(
    {
        f"{_PACKAGE}.bootstrap",
        f"{_PACKAGE}.editor.browser_integration",
        f"{_PACKAGE}.editor.dialog",
        f"{_PACKAGE}.editor.dialog_host",
        f"{_PACKAGE}.editor.editor_integration",
        f"{_PACKAGE}.editor.launcher",
    }
)


def _module_names() -> list[str]:
    """Every module in the shipped package, as a dotted name."""
    names = []
    for path in sorted(_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(_ROOT).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        names.append(".".join([_PACKAGE, *parts]))
    return names


def _import(name: str) -> str | None:
    """Import ``name``. Returns the Anki package that stopped it, or ``None``.

    Anything that is not a missing Anki package propagates: that is the failure
    this file exists to surface.
    """
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        root = (exc.name or "").split(".")[0]
        if root in _ANKI_ROOTS:
            return root
        raise
    return None


@pytest.mark.parametrize("name", _module_names())
def test_module_imports_on_the_declared_floor(name: str) -> None:
    missing = _import(name)
    if missing is not None:
        pytest.skip(f"{name} is part of the Qt layer (needs {missing})")


def test_the_package_is_not_empty() -> None:
    # Guards the two tests below against a discovery bug quietly finding nothing.
    assert len(_module_names()) > 30


def test_only_the_qt_layer_needs_anki() -> None:
    # The skip above is the one way a module can avoid being imported, so the set
    # of modules taking it is pinned here. Letting it grow silently would let a
    # module opt out of the floor check by acquiring an `aqt` import.
    blocked = {name for name in _module_names() if _import(name) is not None}
    assert blocked == set(_NEEDS_ANKI), (
        "the set of modules that need Anki to import has changed; if logic moved "
        "into the Qt layer it can no longer be tested, and if a module left the "
        "set it should be given tests"
    )
