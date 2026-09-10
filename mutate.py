#!/usr/bin/env python3
"""Mutation testing for this repository.

Coverage shows that a line executed. It does not show that any assertion
depends on the result. This script replaces one expression at a time and
reports whether the suite fails.

* a mutant that is **killed** is behaviour some assertion genuinely pins;
* a mutant that **survives** is behaviour nothing is checking.

Nothing is ever written into the working tree. The JavaScript half intercepts
``fs.readFileSync`` and the Python half hooks the import machinery, so each
mutant exists only inside the throwaway process that runs it. The one target that
writes anything, ``build.py``, is given a temporary path by its tests.

A kill only means something if the suite failed for the reason claimed, so two
things are checked before any campaign: that every mutant parses (a syntax error
fails a whole suite at load, and would otherwise be recorded as a kill), and that
a no-op mutation survives on each target (catching a suite that is already red,
or a runner that never reached the file).

Usage:
    python mutate.py                 # the whole catalogue
    python mutate.py --list          # what is in it, without running anything
    python mutate.py isOverImage     # only mutations whose label matches

Exit status is non-zero when the catalogue and reality disagree, in any of four
ways; see :class:`Mutation` and :data:`NOT_APPLIED`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# Targets                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Target:
    """A source file, and the suites that are supposed to be guarding it."""

    source: str
    #: One or more test files. render.js is guarded by five.
    tests: tuple[str, ...]

    @property
    def is_js(self) -> bool:
        return self.source.endswith(".js")


MARKER = Target("src/randomized_occlusion/web/editor/marker.js", ("tests/js/marker.test.js",))
# The reviewer is guarded by five suites; a mutation has to face all of them.
RENDER = Target(
    "src/randomized_occlusion/web/review/render.js",
    (
        "tests/js/render.test.js",
        "tests/js/render_integration.test.js",
        "tests/js/single_cycler.test.js",
        "tests/js/precision.test.js",
        "tests/js/invariants.test.js",
    ),
)
CLIPBOARD = Target("src/randomized_occlusion/editor/clipboard_image.py", ("tests/test_clipboard_image.py",))
CONFIG = Target("src/randomized_occlusion/config/config_service.py", ("tests/test_config_service.py",))
SCRATCH = Target("src/randomized_occlusion/editor/paste_scratch.py", ("tests/test_paste_scratch.py",))
ZOOM = Target("src/randomized_occlusion/editor/zoom_memory.py", ("tests/test_zoom_memory.py",))
MESSAGES = Target("src/randomized_occlusion/editor/messages.py", ("tests/test_messages.py",))
BRIDGE = Target("src/randomized_occlusion/editor/bridge.py", ("tests/test_bridge.py",))

# The pre-existing core. These were already well tested; the entries below lock
# that in so it cannot regress unnoticed.
GEOMETRY = Target("src/randomized_occlusion/domain/geometry.py", ("tests/test_geometry.py",))
STRUCTURE = Target("src/randomized_occlusion/domain/structure.py", ("tests/test_structure.py",))
CODEC = Target("src/randomized_occlusion/domain/codec.py", ("tests/test_codec.py",))
OPTIONS = Target("src/randomized_occlusion/domain/card_options.py", ("tests/test_card_options.py",))
STRUCTSET = Target("src/randomized_occlusion/domain/structure_set.py", ("tests/test_structure_set.py", "tests/test_edge_cases.py"))
RENDERCFG = Target("src/randomized_occlusion/config/render_config.py", ("tests/test_render_config.py", "tests/test_templates.py"))
DEFAULTS = Target("src/randomized_occlusion/config/defaults.py", ("tests/test_config_service.py", "tests/test_render_config.py"))
READER = Target("src/randomized_occlusion/collection/note_reader.py", ("tests/test_note_reader.py",))
FACTORY = Target("src/randomized_occlusion/collection/note_factory.py", ("tests/test_note_factory.py", "tests/test_edge_cases.py"))
INSTALLER = Target("src/randomized_occlusion/notetype/installer.py", ("tests/test_installer.py",))
SPEC = Target("src/randomized_occlusion/notetype/spec.py", ("tests/test_installer.py", "tests/test_manifest.py"))
TEMPLATES = Target("src/randomized_occlusion/notetype/templates.py", ("tests/test_templates.py",))
RESOURCES = Target("src/randomized_occlusion/resources.py", ("tests/test_templates.py",))
GATEWAYS = Target("src/randomized_occlusion/collection/gateways.py", ("tests/test_gateways.py",))
BUILD = Target("build.py", ("tests/test_build.py",))


@dataclass(frozen=True, slots=True)
class Mutation:
    """One deliberate break, and what is expected to come of it.

    ``survives=True`` marks a mutation we do *not* expect any test to catch, and
    ``why`` has to say why that is acceptable; invariably that the code is
    defensive and no user-visible behaviour turns on it. Listing them here rather
    than deleting them keeps the claim honest: if one is ever killed, the run
    fails and asks for this entry to be removed, because the behaviour has become
    observable and should stay tested.
    """

    target: Target
    label: str
    before: str
    after: str
    survives: bool = False
    why: str = ""


def _m(target: Target, label: str, before: str, after: str = "") -> Mutation:
    return Mutation(target, label, before, after)


MUTATIONS: list[Mutation] = [
    # ---------------------------------------------------- canvas: pure geometry
    _m(MARKER, "clampZoom rejects junk", 'if (typeof z !== "number" || !isFinite(z)) return MIN_ZOOM;'),
    _m(MARKER, "clampZoom range", "return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));", "return z;"),
    _m(MARKER, "clampZoom is wired into zoomTo", "    next = clampZoom(next);"),
    _m(MARKER, "clampZoom is wired into setZoom", "zoom = clampZoom(Number(value));", "zoom = Number(value) || 1;"),
    _m(MARKER, "clampPan layout offset",
       "var bounded = Math.max(viewport - layout - content, Math.min(-layout, value));",
       "var bounded = Math.max(viewport - content, Math.min(0, value));"),
    _m(MARKER, "clampPan negative zero", "return bounded === 0 ? 0 : bounded;", "return bounded;"),
    _m(MARKER, "clampPan centre branch", "return (viewport - content) / 2 - layout;", "return 0;"),
    _m(MARKER, "zoomAt sign",
       "return currentPan + offset * (1 - nextZoom / currentZoom);",
       "return currentPan - offset * (1 - nextZoom / currentZoom);"),
    _m(MARKER, "wheel line mode", "if (mode === 1) return delta * WHEEL_LINE_PX;"),
    _m(MARKER, "wheel page mode", "if (mode === 2) return delta * WHEEL_PAGE_PX;"),
    _m(MARKER, "nudgeStep shift", "return bigStep ? 10 : 1;", "return 1;"),

    # ------------------------------------------------------------ canvas: view
    _m(MARKER, "layoutSize measures sub-pixel",
       "return { width: rect.width / appliedZoom, height: rect.height / appliedZoom };",
       "return { width: img.offsetWidth, height: img.offsetHeight };"),
    _m(MARKER, "appliedZoom tracks the DOM", "appliedZoom = zoom;"),
    _m(MARKER, "centrePan layout offset",
       "      (stage.clientWidth - base.width * zoom) / 2 - img.offsetLeft,",
       "      (stage.clientWidth - base.width * zoom) / 2,"),
    _m(MARKER, "Fit re-centres", "    zoom = MIN_ZOOM;\n    centrePan();", "    zoom = MIN_ZOOM;"),
    _m(MARKER, "Fit is reported", "    centrePan();\n    notifyZoom();", "    centrePan();"),
    _m(MARKER, "zoom-in disabled at max", 'setDisabled(el("ed-zoom-in"), atMax);', 'setDisabled(el("ed-zoom-in"), false);'),
    _m(MARKER, "zoom readout text", 'level.textContent = Math.round(zoom * 100) + "%";', 'level.textContent = "";'),
    _m(MARKER, "revealMarker pans", "if (dx || dy) setPan(panX + dx, panY + dy);"),

    # ------------------------------------------------------- canvas: rendering
    _m(MARKER, "overlay is the coordinate origin", "    var ox = rect.left - base.left;", "    var ox = rect.left;"),
    _m(MARKER, "dots numbered from 1", "text.textContent = String(index + 1);", "text.textContent = String(index);"),
    _m(MARKER, "rows numbered from 1", "num.textContent = String(index + 1);", "num.textContent = String(index);"),
    _m(MARKER, "prefilled labels shown", 'input.value = marker.label || "";', 'input.value = "";'),
    _m(MARKER, "empty placeholder row", 'placeholder.className = "ed-empty-row";', 'placeholder.className = "x";'),
    _m(MARKER, "typing updates the label", "markers[index].label = input.value;", 'markers[index].label = "";'),
    _m(MARKER, "typing clears the invalid flag", 'input.classList.remove("ed-invalid");'),
    # Replaced rather than deleted: the anchor is the consequent of `if (input)`,
    # so an empty `after` leaves a bare `if` and a SyntaxError, which fails every
    # test in the suite and scores as a kill.
    _m(MARKER, "markInvalid flags the row", 'input.classList.add("ed-invalid");', "void 0;"),

    # ----------------------------------------------------- canvas: interaction
    Mutation(MARKER, "isOverImage clips to the visible area",
             "clientX >= Math.max(r.left, s.left) &&", "clientX >= r.left &&",
             survives=True,
             why="Its only caller uses the answer to arm the click latch, and every click is "
                 "preceded by a pointerdown that clears the latch anyway. Kept as the honest "
                 "predicate for the question it asks."),
    _m(MARKER, "pointToNormalized clamps",
       "      x: clamp01((clientX - rect.left) / rect.width),",
       "      x: (clientX - rect.left) / rect.width,"),
    _m(MARKER, "marker press ignores non-primary", "if (event.button != null && event.button !== 0) return;"),
    _m(MARKER, "marker press defers to Space", "if (spaceHeld) return;"),
    Mutation(MARKER, "marker press stops propagating",
             "      event.preventDefault();\n      event.stopPropagation();",
             "      event.preventDefault();",
             survives=True,
             why="onStagePointerDown ignores a bare primary press, so nothing observable "
                 "follows today. Kept because it is what stops a marker drag also starting a "
                 "pan if that ever changes."),
    _m(MARKER, "stale latch cleared on a new press",
       "    suppressNextImageClick = false;\n    if (drag !== null || pan !== null) return;",
       "    if (drag !== null || pan !== null) return;"),
    _m(MARKER, "pan arms the latch",
       "    if (overImage) suppressNextImageClick = true;\n    renderCrosshair();",
       "    renderCrosshair();"),
    _m(MARKER, "middle button pans", "button === 1 ||"),
    _m(MARKER, "right button pans", "button === 2 ||"),
    _m(MARKER, "Space arms the primary button", "(button === 0 && spaceHeld)", "false"),
    _m(MARKER, "endPan unhooks pointermove", 'window.removeEventListener("pointermove", onPanMove);'),
    _m(MARKER, "cancelDrag unhooks pointermove", 'window.removeEventListener("pointermove", onDragMove);'),
    _m(MARKER, "contextmenu suppressed",
       "  function onContextMenu(event) {\n    // Right-drag pans, so the menu would fire on every pan release.\n    event.preventDefault();",
       "  function onContextMenu(event) {"),
    _m(MARKER, "wheel swallowed before the guard",
       "    event.preventDefault();\n    if (!imageReady() || drag !== null || pan !== null) return;",
       "    if (!imageReady() || drag !== null || pan !== null) return;\n    event.preventDefault();"),
    _m(MARKER, "wheel ignored mid-gesture", "    if (!imageReady() || drag !== null || pan !== null) return;", "    if (!imageReady()) return;"),
    _m(MARKER, "window ctrl+wheel guard", "    if (event.ctrlKey || event.metaKey) event.preventDefault();"),

    # -------------------------------------------------------- canvas: keyboard
    _m(MARKER, "keys ignored in a label field", "if (isTextField(document.activeElement)) return;"),
    _m(MARKER, "modified keys left alone", "if (event.ctrlKey || event.metaKey || event.altKey) return;"),
    _m(MARKER, "IME composition deferred to", "if (event.isComposing) return;"),
    _m(MARKER, "ArrowUp direction", 'else if (key === "ArrowUp") dy = -1;', 'else if (key === "ArrowUp") dy = 1;'),
    _m(MARKER, "nudge needs a selection", "if (selected < 0 || selected >= markers.length) return;"),
    _m(MARKER, "Space release",
       "  function releaseSpace() {\n    if (!spaceHeld) return;\n    spaceHeld = false;",
       "  function releaseSpace() {\n    if (!spaceHeld) return;"),

    # --------------------------------------------------- canvas: API lifecycle
    _m(MARKER, "prefill coords clamped", "x: clamp01(Number(m.x) || 0),", "x: Number(m.x) || 0,"),
    _m(MARKER, "prefill label coerced", 'label: m.label == null ? "" : String(m.label),', "label: m.label,"),
    _m(MARKER, "prefill must be an array", "if (!Array.isArray(list)) return [];", "if (false) return [];"),
    _m(MARKER, "getMarkers trims", 'label: (m.label || "").trim()', 'label: (m.label || "")'),
    _m(MARKER, "ro:count reported when a marker is placed", "    render();\n    notifyCount();\n    focusInput(markers.length - 1);", "    render();\n    focusInput(markers.length - 1);"),
    _m(MARKER, "ro:count reported when a marker is deleted", "        render();\n        notifyCount();", "        render();"),
    _m(MARKER, "ro:count reported when an image loads", "    renderList();\n    notifyCount();", "    renderList();"),
    _m(MARKER, "setImage releases Space", "    pointerClient = null;\n    releaseSpace();", "    pointerClient = null;"),
    _m(MARKER, "key-up releases Space", 'if (event.key === " " || event.key === "Spacebar") releaseSpace();', ""),
    _m(MARKER, "setImage cancels a drag", "    cancelDrag();\n    endPan();", "    endPan();"),
    _m(MARKER, "setImage ends a pan", "    cancelDrag();\n    endPan();", "    cancelDrag();"),
    _m(MARKER, "setImage keeps the zoom", "    panX = 0;\n    panY = 0;", "    zoom = 1;\n    panX = 0;\n    panY = 0;"),
    # Guarded rather than deleted, because the next line is an `else if` that
    # would be orphaned into a SyntaxError.
    _m(MARKER, "deleting clears the selection", "if (selected === index) selected = -1;",
       "if (false) selected = -1;"),
    _m(MARKER, "deleting shifts the selection", "else if (selected > index) selected -= 1;"),
    _m(MARKER, "blur releases Space", 'window.addEventListener("blur", releaseSpace);'),
    _m(MARKER, "focus is reported to Python", 'send("ro:textfocus:" + (focused ? "1" : "0"));'),
    _m(MARKER, "focus report is deduped", "if (focused === textFocused) return;"),
    _m(MARKER, "zoom report is throttled",
       "      zoomPending = true; // still inside the window; report the settled level later\n      return;",
       "      return;"),



    # ------------------------------------------------------------ domain layer
    _m(GEOMETRY, "coordinates outside the unit interval are rejected", "    if not low <= number <= high:", "    if False:"),
    _m(GEOMETRY, "coordinates are coerced to float", "    return number\n", "    return value\n"),
    _m(STRUCTURE, "from_dict coerces the ordinal to int", 'ordinal=int(data["ord"]),', 'ordinal=data["ord"],'),
    _m(STRUCTURE, "from_dict coerces the label to str", 'label=str(data["label"]),', 'label=data["label"],'),
    _m(CODEC, "base64 decoding rejects stray characters", 'encoded.encode("ascii"), validate=True', 'encoded.encode("ascii"), validate=False'),
    _m(CODEC, "the payload keeps raw UTF-8", "ensure_ascii=False", "ensure_ascii=True"),
    _m(OPTIONS, "coerce trims surrounding whitespace", "cls(str(value).strip().lower())", "cls(str(value).lower())"),
    _m(STRUCTSET, "ordinals must be exactly 1..N", "        if ordinals != expected:", "        if False:"),
    _m(STRUCTSET, "ordered sorts by ordinal", "return tuple(sorted(self.structures, key=lambda s: s.ordinal))", "return self.structures"),
    _m(STRUCTSET, "from_unordered numbers from 1", "for i, s in enumerate(labels_and_points, start=1)", "for i, s in enumerate(labels_and_points, start=2)"),
    _m(STRUCTSET, "the payload version is 2", '"v": 2,', '"v": 99,'),
    _m(STRUCTSET, "cloze escaping runs to a fixpoint", "    previous = \"\"\n    while previous != label:", "    previous = label\n    while previous != label:"),

    # -------------------------------------------------------------- rendering
    _m(RENDERCFG, "behaviour maps showTargetDot", '"showTargetDot": self.show_target_dot,', '"showTargetDot": self.show_decoy_dots,'),
    _m(RENDERCFG, "behaviour maps showDecoyDots", '"showDecoyDots": self.show_decoy_dots,', '"showDecoyDots": self.show_context_labels,'),
    _m(RENDERCFG, "behaviour maps showContextLabels", '"showContextLabels": self.show_context_labels,', '"showContextLabels": self.show_decoy_dots,'),
    _m(RENDERCFG, "behaviour maps minArrowFraction", '"minArrowFraction": self.min_arrow_fraction,', '"minArrowFraction": 0.99,'),
    _m(RENDERCFG, "css var --ro-dot", '"--ro-dot": self.target_dot_color,', '"--ro-dot": self.accent_color,'),
    _m(RENDERCFG, "css var --ro-box-fill", '"--ro-box-fill": self.box_fill,', '"--ro-box-fill": self.accent_color,'),
    _m(RENDERCFG, "the falsey vocabulary is complete", '_FALSEY_STRINGS = {"false", "0", "no", "off", "", "none"}', '_FALSEY_STRINGS = {"false"}'),
    _m(DEFAULTS, "the default direction is forward", '"direction": "forward",', '"direction": "reverse",'),
    _m(DEFAULTS, "the default card mode is multi", '"card_mode": "multi",', '"card_mode": "single",'),

    # ---------------------------------------------------------- reading a note
    _m(READER, "a legacy bare-array payload is accepted", "        if isinstance(payload, list):", "        if False:"),
    _m(READER, "an empty payload reads as absent", "        if not encoded:", "        if False:"),
    _m(READER, "only the first img tag is taken", 'if tag == "img" and self.src is None:', 'if tag == "img":'),
    _m(READER, "an empty src attribute is ignored", 'if name == "src" and value:', 'if name == "src":'),

    # --------------------------------------------------------- the note itself
    _m(FACTORY, "the image field is html-escaped", "html.escape(filename, quote=True)", "filename"),

    # ------------------------------------------------------------ the notetype
    _m(SPEC, "sort_index locates the sort field", "return self.fields.index(self.sort_field)", "return 0"),
    _m(INSTALLER, "create is given the front as the front", "front=template.front,\n                back=template.back,", "front=template.back,\n                back=template.front,"),
    _m(INSTALLER, "create keeps the spec's field order", "fields=self._spec.fields,", "fields=tuple(reversed(self._spec.fields)),"),
    _m(INSTALLER, "create uses the spec's sort index", "sort_index=self._spec.sort_index,", "sort_index=0,"),
    _m(INSTALLER, "a new field alone forces an update", "if fields_changed or collapse_changed or sort_changed or templates_stale:", "if collapse_changed or sort_changed or templates_stale:"),
    _m(INSTALLER, "a stale sort index is repaired", '        notetype["sortf"] = wanted', "        pass"),
    _m(INSTALLER, "the sort field is found by name", "wanted = names.index(self._spec.sort_field)", "wanted = self._spec.sort_index"),
    _m(TEMPLATES, "the fingerprint is extracted from the css", "return match.group(1) if match else None", "return None"),
    _m(TEMPLATES, "script tags in the payload are neutralised", "def _script_safe(text: str) -> str:", "def _script_safe(text: str) -> str:\n    return text"),
    _m(RESOURCES, "web assets are read as UTF-8", 'return path.read_text(encoding="utf-8")', 'return path.read_text(encoding="latin-1")'),

    # ------------------------------------------------------- collection access
    _m(GATEWAYS, "the note type is created as a cloze", 'notetype["type"] = 1  # 1 == cloze (see proto NotetypeKind; no Py const)', 'notetype["type"] = 0'),
    _m(GATEWAYS, "the sort field index is stored", 'notetype["sortf"] = sort_index', 'notetype["sortf"] = 0'),
    _m(GATEWAYS, "a new note type is persisted", "        models.add_dict(notetype)", "        pass"),
    _m(GATEWAYS, "a template update is persisted", "        self._models.update_dict(notetype)", "        pass"),
    _m(GATEWAYS, "front and back are not swapped", 'template["qfmt"] = front\n        template["afmt"] = back\n        models.add_template', 'template["qfmt"] = back\n        template["afmt"] = front\n        models.add_template'),
    _m(GATEWAYS, "find looks the note type up by name", "        return self._models.by_name(name)", "        return None"),
    _m(GATEWAYS, "the stored media basename is returned", "        return self._media.add_file(path)", '        return "wrong.png"'),
    _m(GATEWAYS, "only the named fields are collapsed", 'if field["name"] in targets and not field.get("collapsed", False):', 'if not field.get("collapsed", False):'),

    # ------------------------------------------------------------- packaging
    _m(BUILD, "caches and local state are excluded", 'EXCLUDED_NAMES = {"__pycache__", "meta.json", ".DS_Store"}', "EXCLUDED_NAMES = set()"),
    _m(BUILD, "compiled bytecode is excluded", 'EXCLUDED_SUFFIXES = {".pyc", ".pyo"}', "EXCLUDED_SUFFIXES = set()"),
    _m(BUILD, "entries are deflated", "info.compress_type = zipfile.ZIP_DEFLATED", "info.compress_type = zipfile.ZIP_STORED"),
    _m(BUILD, "the host system is pinned to Unix", "info.create_system = 3", "info.create_system = 0"),
    _m(BUILD, "the file mode is pinned", "info.external_attr = _UNIX_RW_R_R", "info.external_attr = 0"),
    _m(BUILD, "the pinned date is 1980-01-01", "_FIXED_DATE = (1980, 1, 1, 0, 0, 0)", "_FIXED_DATE = (2044, 7, 7, 3, 2, 0)"),
    _m(BUILD, "the version comes from _version.py", 'return str(namespace["__version__"])', 'return "0.0.0"'),
    _m(BUILD, "human_version is stamped into the manifest", 'data["human_version"] = version', "pass"),
    _m(BUILD, "entries are root-relative", "arcname = path.relative_to(PACKAGE_DIR).as_posix()", 'arcname = "sub/" + path.relative_to(PACKAGE_DIR).as_posix()'),
    _m(BUILD, "entries are written in sorted order", 'sorted(PACKAGE_DIR.rglob("*"))', 'PACKAGE_DIR.rglob("*")'),

    # ------------------------------------------------- reviewer: what is drawn
    _m(RENDER, "targets projected on the right axes", "        x: structures[t].x * width,\n        y: structures[t].y * height,", "        x: structures[t].y * width,\n        y: structures[t].x * height,"),
    _m(RENDER, "the arrow ends on the structure", "        x2: target.x,\n        y2: target.y,", "        x2: 0,\n        y2: 0,"),
    _m(RENDER, "the arrow starts on the box border", "      var start = boxBorderToward(box, target);", "      var start = { x: box.x + box.w / 2, y: box.y + box.h / 2 };"),
    _m(RENDER, "decoy dots are drawn", "      if (cfg.showDecoyDots) {\n        drawDots(svg, targets);", "      if (false) {\n        drawDots(svg, targets);"),
    _m(RENDER, "dots sit on their structures", 'svgEl("circle", { class: "ro-dot", cx: target.x, cy: target.y, r: "5" })', 'svgEl("circle", { class: "ro-dot", cx: 0, cy: 0, r: "5" })'),
    _m(RENDER, "the measured label is cleared before the tspans", '    label.textContent = "";', "    "),
    _m(RENDER, "the lone target dot is drawn", "      } else if (targetDotVisible(cfg, isReverse, back)) {\n        drawDot(svg, active);\n      }", "      } else if (false) {\n        drawDot(svg, active);\n      }"),
    _m(RENDER, "a reverse question side hides the target dot", "    return !!cfg.showTargetDot && !(isReverse && !back);", "    return !!cfg.showTargetDot;"),

    # ------------------------------------------------- reviewer: randomisation
    _m(RENDER, "placement samples the rng", "    for (var i = 0; i < cfg.maxPlacementAttempts; i++) {\n      var angle = rng() * Math.PI * 2;", "    for (var i = 0; i < 0; i++) {\n      var angle = rng() * Math.PI * 2;"),
    _m(RENDER, "a minted seed is random", "    return Math.floor(Math.random() * 0xffffffff) >>> 0;", "    return 0;"),
    _m(RENDER, "a fresh view mints rather than reusing", "      seed = randomUint32();\n      writeSeed(seed);", "      seed = 12345;\n      writeSeed(seed);"),
    _m(RENDER, "the minted seed is stored", "      seed = randomUint32();\n      writeSeed(seed);", "      seed = randomUint32();"),
    _m(RENDER, "shuffleIndices shuffles", "    for (var j = n - 1; j > 0; j--) {", "    for (var j = n - 1; j > n; j--) {"),
    _m(RENDER, "directionCoin varies with the seed", "    return makeRng((seed ^ 0x9e3779b9) >>> 0)() < 0.5;", "    return (seed & 1) === 0;"),
    _m(RENDER, "directionCoin has its own seed stream", "    return makeRng((seed ^ 0x9e3779b9) >>> 0)() < 0.5;", "    return makeRng(seed)() < 0.5;"),
    _m(RENDER, "cyclerDirections has its own seed stream", "    var rng = makeRng((seed ^ 0x85ebca6b) >>> 0);", "    var rng = makeRng(seed);"),
    Mutation(RENDER, "makeRng normalises its seed", "    var a = seed >>> 0;", "    var a = seed;",
             survives=True,
             why="The next line applies `| 0`, which wraps to 32 bits anyway, so no "
                 "integer seed can tell the two apart. Kept because it states the "
                 "seed is a u32; there is no behaviour to test."),

    # ------------------------------------------------ reviewer: front/back parity
    _m(RENDER, "the answer reuses the question's seed", "      seed = reused !== null ? parseInt(reused, 10) >>> 0 : randomUint32();", "      seed = randomUint32();"),
    _m(RENDER, "a null stored seed falls through", "      if (stored !== null) return stored;", "      return stored;"),
    _m(RENDER, "the stored seed is read back", "    return window.__roSeedFallback || null;", "    return null;"),

    # ------------------------------------------------- reviewer: payload/config
    _m(RENDER, "the note's config is applied", "        cfg = JSON.parse(decodeBase64Utf8(raw));", "        cfg = {};"),
    _m(RENDER, "a config value overrides the default", "        merged[key] = key in cfg ? cfg[key] : DEFAULT_CONFIG[key];", "        merged[key] = DEFAULT_CONFIG[key];"),
    _m(RENDER, "legacy bare-array payloads still render", "    if (Array.isArray(parsed)) {", "    if (false) {"),
    _m(RENDER, "the answer is NFC-normalised before grading", '.trim().toLowerCase().replace(/\\s+/g, " ").normalize("NFC")', '.trim().toLowerCase().replace(/\\s+/g, " ")'),
    _m(RENDER, "the active ordinal is clamped", "    if (activeIndex < 0 || activeIndex >= count) activeIndex = 0;", ""),

    # ------------------------------------------------------- clipboard: choices
    _m(CLIPBOARD, "svg keeps its extension", '("image/svg+xml", ".svg"),', '("image/svg+xml", ".png"),'),
    _m(CLIPBOARD, "gif keeps its extension", '("image/gif", ".gif"),', '("image/gif", ".png"),'),
    _m(CLIPBOARD, "jpeg keeps its extension", '("image/jpeg", ".jpg"),', '("image/jpeg", ".png"),'),
    _m(CLIPBOARD, "bmp stays pickable as a file",
       '{".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}',
       '{".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}'),
    _m(CLIPBOARD, "bmp is not a pasteable format",
       '("image/webp", ".webp"),', '("image/webp", ".webp"),\n    ("image/bmp", ".bmp"),'),
    _m(CLIPBOARD, "extensions match case-insensitively",
       "return os.path.splitext(path)[1].lower()", "return os.path.splitext(path)[1]"),
    _m(CLIPBOARD, "paste filenames are sanitised",
       'safe = "".join(ch for ch in stamp if ch.isalnum() or ch in "-_")', "safe = stamp"),

    # ------------------------------------------------------ clipboard: sequence
    _m(CLIPBOARD, "a copied file wins",
       "    path = choose_local_file(offer)\n    if path is not None:\n        return PasteChoice(path=path)",
       "    path = None"),
    _m(CLIPBOARD, "published bytes beat a re-encode",
       "        data = source.data_for(mime)\n        if data:",
       "        data = source.data_for(mime)\n        if False:"),
    _m(CLIPBOARD, "an empty format falls through",
       "        if data:\n            return PasteChoice(data=data, suffix=suffix_for_mime(mime))",
       "        return PasteChoice(data=data, suffix=suffix_for_mime(mime))"),
    _m(CLIPBOARD, "the bitmap stays lazy", "    offer = source.offer()", "    offer = source.offer()\n    source.bitmap()"),
    _m(CLIPBOARD, "written bytes keep their format", "suffix=suffix_for_mime(mime)", "suffix=PASTE_SUFFIX"),
    _m(CLIPBOARD, "an empty clipboard yields nothing",
       "    if bitmap is not None:\n        return PasteChoice(bitmap=bitmap)\n    return None",
       "    return PasteChoice(bitmap=bitmap)"),

    # ----------------------------------------------------------------- config
    _m(CONFIG, "zoom clamp range", "return max(MIN_EDITOR_ZOOM, min(MAX_EDITOR_ZOOM, value))", "return value"),
    _m(CONFIG, "zoom clamp rejects bad types",
       "        except (TypeError, ValueError):\n            return DEFAULT_EDITOR_ZOOM",
       "        except (TypeError, ValueError):\n            raise"),
    _m(CONFIG, "zoom clamp rejects non-finite",
       "if not math.isfinite(value):\n            return DEFAULT_EDITOR_ZOOM",
       "if False:\n            return DEFAULT_EDITOR_ZOOM"),
    _m(CONFIG, "zoom range agrees with the canvas", "MAX_EDITOR_ZOOM = 8.0", "MAX_EDITOR_ZOOM = 9.0"),
    _m(CONFIG, "the missing-default marker cannot collide with a real value",
       "_UNSET = object()", "_UNSET = None"),
    _m(CONFIG, "defaults are not frozen into the stored config",
       "if DEFAULT_CONFIG.get(name, _UNSET) != setting",
       "if True"),
    _m(CONFIG, "delta write keeps other keys", "config = dict(stored) if stored else {}", "config = {}"),

    # ------------------------------------------------------------ paste scratch
    _m(SCRATCH, "the write is staged",
       "        path = self.target(suffix)\n        partial = path + PARTIAL",
       "        path = self.target(suffix)\n        partial = path"),
    _m(SCRATCH, "the staged file is swapped in", "            os.replace(partial, path)", "            pass"),
    _m(SCRATCH, "a failed write leaves no partial",
       "            with contextlib.suppress(OSError):\n                os.unlink(partial)", "            pass"),
    _m(SCRATCH, "one directory, however many pastes",
       "        if self._directory is None:\n            self._directory = self._make_dir()",
       "        self._directory = self._make_dir()"),
    _m(SCRATCH, "discard clears the handle",
       "        directory, self._directory = self._directory, None", "        directory = self._directory"),
    _m(SCRATCH, "a failed encode is an error",
       '            if not save(path):\n                raise OSError("the image could not be encoded")',
       "            save(path)"),

    # -------------------------------------------------------------- zoom memory
    _m(ZOOM, "an unchanged level is not written", "        if self._level == self._opening:\n            return"),
    _m(ZOOM, "commit settles", "        self._opening = self._level"),
    _m(ZOOM, "a refused write is swallowed",
       "        with contextlib.suppress(Exception):\n            self._config.set_editor_zoom(self._level)",
       "        self._config.set_editor_zoom(self._level)"),
    _m(ZOOM, "the opening level comes from config", "        self._opening = config.editor_zoom()", "        self._opening = 1.0"),

    # ----------------------------------------------------------------- wording
    _m(MESSAGES, "plural rule", "{'' if count == 1 else 's'}", "{'s' if count == 1 else ''}"),
    _m(MESSAGES, "no prompt when nothing is lost",
       "    if marker_count <= 0:\n        return None", "    if marker_count < 0:\n        return None"),

    # ------------------------------------------------------------------ bridge
    _m(BRIDGE, "zoom messages are parsed", 'if body.startswith("zoom:"):', "if False:"),
    _m(BRIDGE, "text-focus flag is parsed", 'self._on_text_focus(body[len("textfocus:"):] == "1")',
       "self._on_text_focus(True)"),
    _m(BRIDGE, "junk zoom falls back to fit",
       "    except ValueError:\n        return 1.0", "    except ValueError:\n        raise"),
    _m(BRIDGE, "non-finite zoom is rejected",
       "    if not math.isfinite(value):\n        return 1.0", "    if False:\n        return 1.0"),
    _m(BRIDGE, "ready message is routed", 'if body == "ready":', "if False:"),
    _m(BRIDGE, "count message is routed", 'if body.startswith("count:"):', "if False:"),
    _m(BRIDGE, "a negative count is floored", "return max(0, int(raw))", "return int(raw)"),
]

# --------------------------------------------------------------------------- #
# Running one mutant                                                           #
# --------------------------------------------------------------------------- #

#: Patches `readFileSync` so the suites load a mutated source, then requires each
#: test file. node:test runs registered tests at exit, so requiring is enough.
_JS_RUNNER = """
const fs = require("fs"), path = require("path");
const target = path.resolve(process.env.MUT_SOURCE);
const orig = fs.readFileSync;
let applied = false;
fs.readFileSync = function (p, ...rest) {
  let out = orig.call(fs, p, ...rest);
  if (String(p) === target && typeof out === "string") {
    // Anchors in the catalogue are written with LF; the tree is CRLF.
    out = out.replace(/\\r\\n/g, "\\n");
    if (!out.includes(process.env.MUT_BEFORE)) process.exit(99);
    applied = true;
    // A function replacement, so `$&` and friends in MUT_AFTER stay literal and
    // this matches what precheck compiled (Python's str.replace substitutes
    // nothing).
    return out.replace(process.env.MUT_BEFORE, () => process.env.MUT_AFTER);
  }
  return out;
};
// The hook fires from inside test bodies, not at require time, so whether the
// mutant was ever built is only known once everything has run. Only a clean exit
// is overridden: a non-zero code is already carrying a verdict (99 for a stale
// anchor, or a genuine test failure) and must not be relabelled.
process.on("exit", (code) => { if (code === 0 && !applied) process.exitCode = 98; });
for (const file of process.env.MUT_TESTS.split(",")) require(file);
"""

#: Patches the import machinery so the mutant is built by the normal loader.
#:
#: Executing the source into a hand-made module instead breaks any target with a
#: @dataclass: dataclasses resolves annotations through sys.modules, so the
#: module has to be registered before it runs, and registering it early breaks
#: package imports. Hooking get_code avoids the choice, works for files loaded by
#: path (build.py), and sidesteps __pycache__.
_PY_RUNNER = """
import sys, os, importlib.machinery, pytest
sys.path.insert(0, "src")
rel, tests = sys.argv[1], sys.argv[2].split(",")
before, after = sys.stdin.read().split(chr(0), 1)
TARGET = os.path.abspath(rel)
applied = []
_orig = importlib.machinery.SourceFileLoader.get_code
def get_code(self, fullname):
    try:
        path = os.path.abspath(self.path)
    except Exception:
        return _orig(self, fullname)
    if path != TARGET:
        return _orig(self, fullname)
    text = open(self.path, encoding="utf-8").read()
    if before not in text:
        os._exit(99)
    applied.append(True)
    return compile(text.replace(before, after, 1), self.path, "exec")
importlib.machinery.SourceFileLoader.get_code = get_code
sys.dont_write_bytecode = True
code = pytest.main(["-q", "--no-header", "-p", "no:cacheprovider", "-x"] + tests)
# A mutant that never reached the file proves nothing. Without this it exits 0
# and reads as SURVIVED, i.e. "no test covers this".
if not applied:
    os._exit(98)
sys.exit(code)
"""

KILLED, SURVIVED, MISSING = "killed", "survived", "anchor missing"
#: The loader hook never matched the target, so no mutant was ever built. Kept
#: apart from SURVIVED, which would otherwise absorb it and read as an honest
#: "nothing tests this".
NOT_APPLIED = "not applied"


def run(mutation: Mutation) -> str:
    """Apply one mutation in a throwaway process and report what became of it."""
    target = mutation.target
    if target.is_js:
        completed = subprocess.run(
            [_node(), "-e", _JS_RUNNER],
            cwd=ROOT,
            capture_output=True,
            env={
                **_child_env(),
                "MUT_SOURCE": str(ROOT / target.source),
                "MUT_TESTS": ",".join(
                    str(ROOT / t).replace("\\", "/") for t in target.tests
                ),
                "MUT_BEFORE": mutation.before,
                "MUT_AFTER": mutation.after,
            },
        )
    else:
        completed = subprocess.run(
            [sys.executable, "-c", _PY_RUNNER, target.source, ",".join(target.tests)],
            cwd=ROOT,
            input=f"{mutation.before}\0{mutation.after}".encode(),
            capture_output=True,
            env=_child_env(),
        )
    if completed.returncode == 99:
        return MISSING
    if completed.returncode == 98:
        return NOT_APPLIED
    return SURVIVED if completed.returncode == 0 else KILLED


def _node() -> str:
    return "node.exe" if sys.platform == "win32" else "node"


def _environ() -> dict[str, str]:
    import os

    return dict(os.environ)


#: Variables that would change what a suite does, and so be misread as a
#: property of the mutant rather than of the shell the campaign was run from.
#: Both runners drop them: NODE_OPTIONS can inject a require or a loader, exactly
#: as PYTEST_ADDOPTS can inject a flag.
_UNPINNED = frozenset(
    {
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONWARNINGS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "NODE_OPTIONS",
    }
)


def _child_env() -> dict[str, str]:
    """The environment both runners hand their child."""
    env = {k: v for k, v in _environ().items() if k not in _UNPINNED}
    # Anchors go down the pipe as UTF-8; without this the Python child decodes
    # them with the locale encoding (cp1252 on Windows), so the first non-ASCII
    # anchor would read as stale and blame the catalogue for a harness fault.
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# --------------------------------------------------------------------------- #
# The campaign                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Report:
    """What the run found, and whether that matches what the catalogue claims."""

    killed: list[str] = field(default_factory=list)
    expected_survivors: list[str] = field(default_factory=list)
    unexpected_survivors: list[Mutation] = field(default_factory=list)
    newly_killed: list[Mutation] = field(default_factory=list)
    missing: list[Mutation] = field(default_factory=list)
    not_applied: list[Mutation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.unexpected_survivors
            or self.newly_killed
            or self.missing
            or self.not_applied
        )


def _source_of(target: Target) -> str:
    """The target's text, with line endings normalised to match the anchors."""
    return (ROOT / target.source).read_text(encoding="utf-8").replace("\r\n", "\n")


#: Compiles each candidate without running it and reports which ones failed.
#: One process for the whole catalogue: spawning node per mutant took six
#: seconds, which is too slow to also run from the ordinary test suite.
_JS_PARSE = """
const vm = require("vm");
let raw = "";
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  const failures = [];
  JSON.parse(raw).forEach((source, index) => {
    try {
      new vm.Script(source);
    } catch (error) {
      failures.push([index, String(error.message)]);
    }
  });
  process.stdout.write(JSON.stringify(failures));
});
"""


def precheck(mutations: list[Mutation]) -> list[tuple[str, str]]:
    """Report mutants that do not parse.

    A mutant with a syntax error fails every test in its suite for a reason that
    has nothing to do with coverage, and :func:`run` scores that as a kill. Two
    entries here did exactly that, both by deleting the consequent of an ``if``.
    """
    bad: list[tuple[str, str]] = []
    pending: list[Mutation] = []
    sources: list[str] = []

    for mutation in mutations:
        source = _source_of(mutation.target)
        if mutation.before not in source:
            continue  # a stale anchor; the campaign reports that as MISSING
        mutated = source.replace(mutation.before, mutation.after, 1)
        if mutation.target.is_js:
            pending.append(mutation)
            sources.append(mutated)
            continue
        try:
            compile(mutated, mutation.target.source, "exec")
        except SyntaxError as exc:
            bad.append((mutation.label, f"line {exc.lineno}: {exc.msg}"))

    for index, message in _js_parse_failures(sources):
        bad.append((pending[index].label, message))
    return bad


def _js_parse_failures(sources: list[str]) -> list[tuple[int, str]]:
    """Which of ``sources`` do not parse, as ``(index, message)``."""
    if not sources:
        return []
    completed = subprocess.run(
        [_node(), "-e", _JS_PARSE],
        input=json.dumps(sources).encode("utf-8"),
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "the JavaScript parse check failed to run: "
            + completed.stderr.decode("utf-8", "replace").strip()
        )
    return [(index, message) for index, message in json.loads(completed.stdout)]


def self_check(targets: list[Target], mutations: list[Mutation]) -> list[str]:
    """Report targets where a no-op mutation does not survive.

    A no-op replaces a fragment with itself, so the suite must pass exactly as it
    does unmutated. Anything else means the harness is failing for its own
    reasons and reporting those failures as kills. This has happened once
    already, silently invalidating a whole target.
    """
    broken = []
    for target in targets:
        anchor = _fresh_anchor(target, mutations)
        if anchor is None:
            # Nothing to probe with. Say so: the campaign flags the stale anchors
            # separately, but until one is repaired this target runs unguarded,
            # and calling it healthy is the exact failure this function exists to
            # prevent.
            broken.append(f"{target.source} (no anchor still matches; cannot verify)")
            continue
        outcome = run(Mutation(target, "no-op", anchor, anchor))
        # A no-op must SURVIVE. Anything else is the harness failing for its own
        # reasons: KILLED means the suite is already red, NOT_APPLIED that the
        # hook never reached the file, and MISSING that the anchor stopped
        # matching between the check above and the run. Listing the acceptable
        # outcome rather than the unacceptable ones means a future outcome cannot
        # be waved through by omission.
        if outcome != SURVIVED:
            broken.append(f"{target.source} (no-op mutation {outcome})")
    return broken


def _fresh_anchor(target: Target, mutations: list[Mutation]) -> str | None:
    """An anchor for ``target`` that still matches its source.

    Taking the first entry blindly skips the check whenever that one anchor has
    gone stale, which leaves every later mutation for the target unguarded.
    """
    source = _source_of(target)
    return next(
        (m.before for m in mutations if m.target == target and m.before in source), None
    )


def campaign(mutations: list[Mutation], *, verbose: bool = True) -> Report:
    report = Report()
    for mutation in mutations:
        outcome = run(mutation)
        if outcome == MISSING:
            report.missing.append(mutation)
            mark = "ANCHOR MISSING"
        elif outcome == NOT_APPLIED:
            report.not_applied.append(mutation)
            mark = "NOT APPLIED"
        elif outcome == SURVIVED and mutation.survives:
            report.expected_survivors.append(mutation.label)
            mark = "survived (known)"
        elif outcome == SURVIVED:
            report.unexpected_survivors.append(mutation)
            mark = "SURVIVED"
        elif mutation.survives:
            report.newly_killed.append(mutation)
            mark = "KILLED (unexpected)"
        else:
            report.killed.append(mutation.label)
            mark = "killed"
        if verbose:
            print(f"  {mark:<20} {mutation.label}")
    return report


def describe(report: Report, total: int) -> None:
    print(
        f"\n{len(report.killed)} killed, "
        f"{len(report.expected_survivors)} survived as expected, "
        f"{len(report.unexpected_survivors)} survived unexpectedly, "
        f"{len(report.missing)} anchors missing, "
        f"{len(report.not_applied)} never applied (of {total})"
    )
    if report.not_applied:
        print("\nThe mutant was never built for these, so the result says nothing")
        print("about coverage. The loader hook did not match the target file:")
        for mutation in report.not_applied:
            print(f"  - {mutation.label}  ({mutation.target.source})")
    if report.missing:
        print("\nThese mutations no longer match the source: the code moved on and")
        print("the catalogue did not. Update the anchors in mutate.py:")
        for mutation in report.missing:
            print(f"  - {mutation.label}  ({mutation.target.source})")
    if report.unexpected_survivors:
        print("\nNothing failed when these were broken, so no test is really checking them:")
        for mutation in report.unexpected_survivors:
            print(f"  - {mutation.label}  ({mutation.target.tests})")
    if report.newly_killed:
        print("\nThese are listed as knowingly untested, but a test caught them; good.")
        print("Drop the `survives=True` from their entries so they stay covered:")
        for mutation in report.newly_killed:
            print(f"  - {mutation.label}")


def _matches(mutation: Mutation, needle: str | None) -> bool:
    """Match on the label or on the file being mutated, whichever the user meant."""
    if not needle:
        return True
    needle = needle.lower()
    return needle in mutation.label.lower() or needle in mutation.target.source.lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "filter",
        nargs="?",
        help="only run mutations whose label or source file contains this",
    )
    parser.add_argument("--list", action="store_true", help="print the catalogue and stop")
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    args = parser.parse_args()

    chosen = [m for m in MUTATIONS if _matches(m, args.filter)]
    if not chosen:
        print(f"no mutation matches {args.filter!r}")
        return 2

    if args.list:
        for mutation in chosen:
            note = f"  (expected to survive: {mutation.why})" if mutation.survives else ""
            print(f"{mutation.target.source}: {mutation.label}{note}")
        return 0

    unparsable = precheck(chosen)
    if unparsable:
        print("These mutants do not parse, so every test in the suite would fail on",
              file=sys.stderr)
        print("a syntax error and be counted as a kill. Rewrite them as valid code:",
              file=sys.stderr)
        for label, error in unparsable:
            print(f"  - {label}: {error}", file=sys.stderr)
        return 2

    targets = sorted({m.target for m in chosen}, key=lambda t: t.source)
    broken = self_check(targets, chosen)
    if broken:
        print("The harness fails on an unmutated source for:", file=sys.stderr)
        for source in broken:
            print(f"  - {source}", file=sys.stderr)
        print("Every result for those targets would be a false kill. Fix the runner.",
              file=sys.stderr)
        return 2

    if not args.json:
        plural = "" if len(chosen) == 1 else "s"
        print(f"Running {len(chosen)} mutation{plural}\n")
    report = campaign(chosen, verbose=not args.json)
    if args.json:
        print(json.dumps({
            "killed": report.killed,
            "expected_survivors": report.expected_survivors,
            "unexpected_survivors": [m.label for m in report.unexpected_survivors],
            "newly_killed": [m.label for m in report.newly_killed],
            "missing": [m.label for m in report.missing],
            "not_applied": [m.label for m in report.not_applied],
        }, indent=2))
    else:
        describe(report, len(chosen))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
