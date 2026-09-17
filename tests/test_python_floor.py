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

Six modules cannot be imported at all without ``aqt``, which CI never installs,
so the guard above SKIPS them -- exactly the six that carry the Qt code, and the
ones most likely to acquire new syntax, since they are where the UI work happens.
The checks below therefore read them as source
instead: a parse pinned to the floor, the ``dataclass`` arguments a parse cannot
see, and the future import that makes ``X | Y`` annotations legal there. Weaker
than executing them, and the only thing available without Anki.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import randomized_occlusion

_PACKAGE = "randomized_occlusion"
_ROOT = Path(randomized_occlusion.__file__).parent

#: The oldest Python the add-on claims to run on, as ``ast.parse`` wants it.
_FLOOR = (3, 9)

#: ``dataclass`` parameters introduced after the floor. They are keyword
#: ARGUMENTS, not syntax, so a parse accepts them at any ``feature_version`` and
#: only executing the class body raises. That is precisely how ``slots=True``
#: shipped in 13 modules and made the add-on unloadable on its own minimum.
_DATACLASS_SINCE_310 = frozenset({"slots", "kw_only", "match_args", "weakref_slot"})

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


def _module_files() -> list[tuple[str, Path]]:
    """Every module in the shipped package, as (dotted name, file)."""
    found = []
    for path in sorted(_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(_ROOT).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        found.append((".".join([_PACKAGE, *parts]), path))
    return found


def _module_names() -> list[str]:
    """Every module in the shipped package, as a dotted name."""
    return [name for name, _path in _module_files()]


def _late_dataclass_arguments(tree: ast.AST) -> list[str]:
    """``dataclass`` keywords in ``tree`` that postdate the floor."""
    late = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "dataclass":
            continue
        for keyword in node.keywords:
            if keyword.arg in _DATACLASS_SINCE_310:
                late.append(f"{keyword.arg} (line {node.lineno})")
    return late


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


@pytest.mark.parametrize("name,path", _module_files(), ids=_module_names())
def test_module_source_is_legal_on_the_declared_floor(name: str, path: Path) -> None:
    """The check for the six modules ``_import`` can only skip.

    Run over every module, not just those six: an interpreter newer than the
    floor is where this suite usually runs, and there the import above proves
    nothing about 3.9 for ANY module.
    """
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path), feature_version=_FLOOR)
    except SyntaxError as exc:  # pragma: no cover - only on a real violation
        pytest.fail(f"{name} uses syntax newer than Python {_FLOOR}: {exc}")

    late = _late_dataclass_arguments(tree)
    assert not late, (
        f"{name} passes {late} to dataclass; those postdate Python {_FLOOR} and "
        "raise TypeError at import, so the add-on would not load at all"
    )

    # ``X | Y`` in an annotation is valid SYNTAX on 3.9 but is evaluated at
    # definition time without this import, which is a TypeError there. Every
    # module in the package has it today; losing it is silent on 3.10+.
    futures = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
    }
    assert "annotations" in futures, (
        f"{name} is missing `from __future__ import annotations`, so any "
        f"`X | Y` annotation in it is evaluated on Python {_FLOOR} and raises"
    )


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
