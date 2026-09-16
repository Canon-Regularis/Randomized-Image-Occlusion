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


@dataclass(frozen=True)
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
READER = Target(
    "src/randomized_occlusion/collection/note_reader.py",
    ("tests/test_note_reader.py", "tests/test_edge_cases.py", "tests/test_fuzz.py"),
)
FACTORY = Target("src/randomized_occlusion/collection/note_factory.py", ("tests/test_note_factory.py", "tests/test_edge_cases.py"))
INSTALLER = Target("src/randomized_occlusion/notetype/installer.py", ("tests/test_installer.py",))
NOTETYPE_FACTORY = Target(
    "src/randomized_occlusion/notetype/factory.py", ("tests/test_notetype_factory.py",)
)
# Reachable only since ops/runner.py stopped importing CollectionOp at module
# scope; that one import put the whole save path beyond every test.
SAVERS = Target("src/randomized_occlusion/editor/savers.py", ("tests/test_savers.py",))
SPEC = Target("src/randomized_occlusion/notetype/spec.py", ("tests/test_installer.py", "tests/test_manifest.py"))
SHORTCUTS = Target("src/randomized_occlusion/review_shortcuts.py", ("tests/test_review_shortcuts.py",))
TEMPLATES = Target("src/randomized_occlusion/notetype/templates.py", ("tests/test_templates.py",))
RESOURCES = Target("src/randomized_occlusion/resources.py", ("tests/test_templates.py",))
GATEWAYS = Target("src/randomized_occlusion/collection/gateways.py", ("tests/test_gateways.py",))
BUILD = Target("build.py", ("tests/test_build.py",))


@dataclass(frozen=True)
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

    # ------------------------------------------------- canvas: pan / drag / resize
    _m(MARKER, "setPan bounds the horizontal pan",
       "    panX = clampPan(x, base.width * zoom, stage.clientWidth, img.offsetLeft);",
       "    panX = x;"),
    _m(MARKER, "setPan bounds the vertical pan",
       "    panY = clampPan(y, base.height * zoom, stage.clientHeight, img.offsetTop);",
       "    panY = y;"),
    _m(MARKER, "setPan applies what it computed", "    applyTransform();\n  }\n\n  /**\n   * The image's un-zoomed size, sub-pixel.", "  }\n\n  /**\n   * The image's un-zoomed size, sub-pixel."),
    _m(MARKER, "a pan starts from the current offset",
       "      originX: panX,\n      originY: panY,", "      originX: 0,\n      originY: 0,"),
    _m(MARKER, "a pan records where it began",
       "      startX: event.clientX,\n      startY: event.clientY,", "      startX: 0,\n      startY: 0,"),
    Mutation(MARKER, "starting a pan clears a stale latch",
             "    suppressNextImageClick = false;\n    capturePointer(el(\"ed-stage\"), event.pointerId);",
             "    capturePointer(el(\"ed-stage\"), event.pointerId);",
             survives=True,
             why="onStagePointerDown clears the latch at the top of every stage "
                 "press, and startPan is only ever reached from there, so this "
                 "second clear cannot change any outcome. Kept because the two "
                 "clears guard different things: one is about the press that is "
                 "starting, this one about the gesture that is."),
    _m(MARKER, "panning marks the stage", '    setStageClass("ed-panning", true);', "    void 0;"),
    _m(MARKER, "ending a pan unmarks the stage", '    setStageClass("ed-panning", false);', "    void 0;"),
    _m(MARKER, "a drag remembers which marker it holds",
       "    drag = { index: index, pointerId: event.pointerId };", "    drag = { index: 0, pointerId: event.pointerId };"),
    _m(MARKER, "a drag tracks the pointer it began with",
       "    drag = { index: index, pointerId: event.pointerId };", "    drag = { index: index, pointerId: -1 };"),
    _m(MARKER, "a drag ignores another pointer's move",
       "    if (!drag || event.pointerId !== drag.pointerId) return;\n    var pos", "    if (!drag) return;\n    var pos"),
    _m(MARKER, "a drag ignores another pointer's release",
       "    if (!drag || event.pointerId !== drag.pointerId) return;\n    var overImage", "    if (!drag) return;\n    var overImage"),
    _m(MARKER, "releasing a drag tears it down", "    cancelDrag();\n    // Defensive.", "    // Defensive."),
    _m(MARKER, "a resize is coalesced into one frame", "    if (resizeFrame !== null) return;", "    if (false) return;"),
    _m(MARKER, "a resize re-bounds the pan", "      setPan(panX, panY);", "      void 0;"),
    _m(MARKER, "the resize frame is released", "      resizeFrame = null;", "      void 0;"),

    # ------------------------------------------------- canvas: nudge / crosshair
    _m(MARKER, "a nudge moves horizontally", "    marker.x = clamp01(marker.x + dxPx / rect.width);", "    marker.x = clamp01(marker.x);"),
    _m(MARKER, "a nudge moves vertically", "    marker.y = clamp01(marker.y + dyPx / rect.height);", "    marker.y = clamp01(marker.y);"),
    _m(MARKER, "a nudge is scaled by the displayed size",
       "    marker.x = clamp01(marker.x + dxPx / rect.width);", "    marker.x = clamp01(marker.x + dxPx);"),
    _m(MARKER, "a nudge stays on the image", "    marker.y = clamp01(marker.y + dyPx / rect.height);", "    marker.y = marker.y + dyPx / rect.height;"),
    _m(MARKER, "a nudge redraws the overlay", "    marker.y = clamp01(marker.y + dyPx / rect.height);\n    renderOverlay();", "    marker.y = clamp01(marker.y + dyPx / rect.height);"),
    _m(MARKER, "the crosshair is cleared before redrawing",
       "    clear(group);\n    // Hidden while panning",
       "    void 0;\n    // Hidden while panning"),
    _m(MARKER, "the crosshair hides while panning", "    if (!pointerClient || pan !== null || !imageReady()) return;", "    if (!pointerClient || !imageReady()) return;"),
    _m(MARKER, "the crosshair hides with no pointer", "    if (!pointerClient || pan !== null || !imageReady()) return;", "    if (pan !== null || !imageReady()) return;"),
    _m(MARKER, "the crosshair stays off the image edges",
       "    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return;", "    if (false) return;"),
    _m(MARKER, "the crosshair is drawn in overlay space",
       "    var cx = x - base.left;\n    var cy = y - base.top;", "    var cx = x;\n    var cy = y;"),
    _m(MARKER, "the crosshair draws both lines",
       "    group.appendChild(\n      svgEl(\"line\", { class: \"ed-crosshair-line\", x1: cx, y1: 0, x2: cx, y2: base.height })\n    );",
       "    void 0;"),
    _m(MARKER, "pointer movement is tracked for the crosshair",
       "    pointerClient = { x: event.clientX, y: event.clientY };", "    pointerClient = { x: 0, y: 0 };"),
    _m(MARKER, "leaving the stage drops the crosshair", "    pointerClient = null;\n    renderCrosshair();", "    renderCrosshair();"),

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

    _m(MARKER, "an existing ordinal is carried through the canvas",
       "        ord: isFinite(ord) && ord >= 1 ? Math.floor(ord) : null,",
       "        ord: null,"),
    _m(MARKER, "a junk ordinal is not trusted",
       "        ord: isFinite(ord) && ord >= 1 ? Math.floor(ord) : null,",
       "        ord: ord,"),
    _m(MARKER, "the ordinal is handed back on save",
       "        ord: m.ord == null ? null : m.ord,", "        ord: null,"),
    _m(MARKER, "an undecodable image is reported, not ignored",
       "      imageBroken = true;", "      imageBroken = false;"),
    _m(MARKER, "a broken image says so on its own channel",
       '    send("ro:broken:" + (imageBroken ? "1" : "0"));',
       '    send("ro:broken:0");'),
    _m(MARKER, "the marker count is not used to report breakage",
       '    send("ro:count:" + markers.length);',
       '    send("ro:count:" + (imageBroken ? 0 : markers.length));'),
    _m(MARKER, "a good image clears the broken latch",
       "    imageBroken = false;\n    if (empty) empty.style.display = \"none\";",
       '    if (empty) empty.style.display = "none";'),
    _m(MARKER, "clearing the list reports the focus it destroyed",
       "    reportTextFocus();\n    if (!markers.length) {",
       "    if (!markers.length) {"),
    _m(MARKER, "Space reaches a focused button",
       "      if (isButton(document.activeElement)) return;",
       "      if (false) return;"),

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
    _m(STRUCTSET, "ordinals must be distinct",
       "        if len(set(ordinals)) != len(ordinals):", "        if False:"),
    _m(STRUCTSET, "an ordinal must be able to address a card",
       "        if ordinals[-1] > MAX_ORDINAL:", "        if False:"),
    _m(STRUCTSET, "an existing ordinal is kept, not reassigned",
       "            if ordinal is None:\n                ordinal, nxt = nxt, nxt + 1",
       "            if True:\n                ordinal, nxt = nxt, nxt + 1"),
    _m(STRUCTSET, "a new structure never reuses a freed ordinal",
       "        nxt = max(max(kept, default=0) + 1, next_ordinal)",
       "        nxt = max(kept, default=0) + 1"),
    _m(STRUCTSET, "a new structure follows the structures it is added to",
       "        nxt = max(max(kept, default=0) + 1, next_ordinal)",
       "        nxt = next_ordinal"),
    _m(STRUCTSET, "the high-water mark only ever goes up",
       "        if self.next_ordinal < floor:", "        if False:"),
    _m(STRUCTSET, "the high-water mark is carried in the payload",
       '            "nextOrd": self.next_ordinal,', '            "nextOrd": 0,'),
    _m(STRUCTSET, "each new structure gets its own ordinal",
       "                ordinal, nxt = nxt, nxt + 1", "                ordinal = nxt"),
    _m(STRUCTSET, "ordered sorts by ordinal", "return tuple(sorted(self.structures, key=lambda s: s.ordinal))", "return self.structures"),
    _m(STRUCTSET, "from_unordered numbers from 1", "for i, s in enumerate(labels_and_points, start=1)", "for i, s in enumerate(labels_and_points, start=2)"),
    _m(STRUCTSET, "the payload version is 2", '"v": 2,', '"v": 99,'),
    _m(STRUCTSET, "cloze escaping runs to a fixpoint", "    previous = \"\"\n    while previous != label:", "    previous = label\n    while previous != label:"),
    _m(STRUCTSET, "a label cannot inject markup into the card",
       '    label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")',
       '    label = label.replace("&", "&amp;")'),
    _m(STRUCTSET, "the ampersand is escaped before the entities it would break",
       '    label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")',
       '    label = label.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")'),
    _m(STRUCTSET, "a trailing brace is kept clear of the closing delimiter",
       '    if label.endswith("}"):', "    if False:"),

    # -------------------------------------------------------------- rendering
    _m(RENDERCFG, "only real hex lengths are accepted",
       '    r"^(#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})"',
       '    r"^(#[0-9A-Fa-f]{3,8}"'),
    _m(RENDERCFG, "behaviour maps showTargetDot", '"showTargetDot": self.show_target_dot,', '"showTargetDot": self.show_decoy_dots,'),
    _m(RENDERCFG, "behaviour maps showDecoyDots", '"showDecoyDots": self.show_decoy_dots,', '"showDecoyDots": self.show_context_labels,'),
    _m(RENDERCFG, "behaviour maps showContextLabels", '"showContextLabels": self.show_context_labels,', '"showContextLabels": self.show_decoy_dots,'),
    _m(RENDERCFG, "behaviour maps minArrowFraction", '"minArrowFraction": self.min_arrow_fraction,', '"minArrowFraction": 0.99,'),
    _m(RENDERCFG, "css var --ro-dot", '"--ro-dot": self.target_dot_color,', '"--ro-dot": self.accent_color,'),
    _m(RENDERCFG, "css var --ro-box-fill", '"--ro-box-fill": self.box_fill,', '"--ro-box-fill": self.accent_color,'),
    _m(OPTIONS, "the falsey vocabulary is complete",
       '_FALSEY_STRINGS = frozenset({"false", "0", "no", "off", "", "none"})',
       '_FALSEY_STRINGS = frozenset({"false"})'),
    _m(OPTIONS, "a config boolean honours the falsey spellings",
       "        return value.strip().lower() not in _FALSEY_STRINGS",
       "        return bool(value)"),
    _m(RENDERCFG, "the render config shares the domain's boolean rule",
       "    return coerce_bool(value, default)", "    return bool(value)"),
    _m(DEFAULTS, "the default direction is forward", '"direction": "forward",', '"direction": "reverse",'),
    _m(DEFAULTS, "the default card mode is multi", '"card_mode": "multi",', '"card_mode": "single",'),

    # ---------------------------------------------------------- reading a note
    _m(READER, "a legacy bare-array payload is accepted", "        if isinstance(payload, list):", "        if False:"),
    _m(READER, "an empty payload reads as absent", "        if not encoded:", "        if False:"),
    _m(READER, "the context-labels fallback is applied",
       "        if context_labels is None:", "        if False:"),
    _m(READER, "the context-labels fallback defaults to off",
       "        self, fields: Mapping[str, str], *, context_labels_default: bool = False",
       "        self, fields: Mapping[str, str], *, context_labels_default: bool = True"),
    _m(READER, "an absent contextLabels key is not a stored False",
       "    if isinstance(value, (bool, int, float, str)):", "    if True:"),
    _m(READER, "a null contextLabels reads as absent, not as False",
       "    return None\n\n\nclass _ImgSrcExtractor", "    return False\n\n\nclass _ImgSrcExtractor"),
    _m(READER, "an uninterpretable flag reads as absent, not as False",
       "    if isinstance(value, (bool, int, float, str)):", "    if not isinstance(value, (bool, int, float, str)):"),
    _m(READER, "a null interaction reads as absent, not as reveal",
       '                if payload.get("interaction") is not None',
       '                if "interaction" in payload'),
    _m(READER, "the stored contextLabels value is coerced",
       "        return coerce_bool(value, False)", "        return bool(value)"),
    _m(READER, "the context-labels flag comes from its own key",
       '                _stored_flag(payload.get("contextLabels")),',
       '                _stored_flag(payload.get("interaction")),'),
    _m(READER, "the payload's interaction beats the type flag",
       "        if payload_interaction is not None:", "        if False:"),
    _m(READER, "a legacy single note defaults to typing",
       "        elif mode == CardMode.SINGLE:", "        elif False:"),
    _m(READER, "the type flag comes from the note's own field",
       '                if str(fields.get(spec.type_flag_field, "")).strip()',
       "                if False"),
    _m(READER, "a whitespace-only type flag is not set",
       '                if str(fields.get(spec.type_flag_field, "")).strip()',
       '                if str(fields.get(spec.type_flag_field, ""))'),
    _m(READER, "a v1 bare array reads as multi mode",
       "            return self._structures(payload), Direction.FORWARD, CardMode.MULTI, None, None",
       "            return self._structures(payload), Direction.FORWARD, CardMode.SINGLE, None, None"),
    _m(READER, "a v1 bare array reads as forward",
       "            return self._structures(payload), Direction.FORWARD, CardMode.MULTI, None, None",
       "            return self._structures(payload), Direction.REVERSE, CardMode.MULTI, None, None"),
    _m(READER, "a v2 payload must carry a structures list",
       '        if isinstance(payload, dict) and isinstance(payload.get("structures"), list):',
       "        if isinstance(payload, dict):"),
    _m(READER, "the payload's direction is read back",
       '                Direction.coerce(payload.get("direction"), Direction.FORWARD),',
       "                Direction.FORWARD,"),
    _m(READER, "the payload's mode is read back",
       '                CardMode.coerce(payload.get("mode"), CardMode.MULTI),',
       "                CardMode.MULTI,"),
    _m(READER, "the header comes from the header field",
       '            header=_field_text(fields.get(spec.header_field, "")),',
       '            header="",'),
    _m(READER, "the stored header is read back as plain text",
       '            header=_field_text(fields.get(spec.header_field, "")),',
       '            header=fields.get(spec.header_field, ""),'),
    _m(READER, "markup in a field is dropped, not shown",
       "    def handle_data(self, data: str) -> None:",
       "    def handle_data_unused(self, data: str) -> None:"),
    _m(READER, "a line break in a field is kept",
       '        if tag == "br":', "        if False:"),
    _m(READER, "a block tag ends a line",
       "        if tag in _BLOCK_TAGS:", "        if False:"),
    _m(READER, "no line break is invented at the edges",
       "        if self._pending_break and self._parts:",
       "        if self._pending_break:"),
    _m(READER, "the reader does not swap header and back extra",
       '            back_extra=_field_text(fields.get(spec.back_extra_field, "")),',
       '            back_extra=_field_text(fields.get(spec.header_field, "")),'),
    _m(READER, "the image filename is extracted, not stored raw",
       '            image_filename=_extract_image_filename(fields.get(spec.image_field, "")),',
       '            image_filename=fields.get(spec.image_field, ""),'),
    _m(READER, "the payload comes from the structures field",
       '            self._parse_payload(fields.get(spec.structures_field, ""))',
       '            self._parse_payload(fields.get(spec.image_field, ""))'),
    _m(READER, "an undecodable payload is named as such",
       '            raise ValueError("this note\'s structure data could not be decoded") from exc',
       '            raise ValueError("unreadable") from exc'),
    _m(READER, "only the first img tag is taken", 'if tag == "img" and self.src is None:', 'if tag == "img":'),
    _m(READER, "an empty src attribute is ignored", 'if name == "src" and value:', 'if name == "src":'),

    # --------------------------------------------------------- the note itself
    _m(FACTORY, "the image field is html-escaped", "html.escape(filename, quote=True)", "filename"),
    _m(FACTORY, "the image src is quoted",
       'return f\'<img src="{html.escape(filename, quote=True)}">\'',
       "return f'<img src={html.escape(filename, quote=True)}>'"),
    _m(FACTORY, "quotes in the filename are escaped",
       "html.escape(filename, quote=True)", "html.escape(filename, quote=False)"),
    _m(FACTORY, "single mode never uses the native type box",
       "            options.interaction == Interaction.TYPE and options.mode != CardMode.SINGLE",
       "            options.interaction == Interaction.TYPE"),
    _m(FACTORY, "the type flag is set for a type note", '            spec.type_flag_field: "1" if native_type else "",', '            spec.type_flag_field: "",'),
    _m(FACTORY, "the type flag is empty for a reveal note", '            spec.type_flag_field: "1" if native_type else "",', '            spec.type_flag_field: "1",'),
    _m(FACTORY, "the cloze field is generated from the structures",
       "            spec.cloze_field: structures.cloze_field(options),",
       '            spec.cloze_field: "",'),
    _m(FACTORY, "the cloze field is built with the note's own options",
       "            spec.cloze_field: structures.cloze_field(options),",
       "            spec.cloze_field: structures.cloze_field(_DEFAULT_OPTIONS),"),
    _m(FACTORY, "the payload carries the note's own options",
       "            spec.structures_field: structures.to_payload_base64(options),",
       "            spec.structures_field: structures.to_payload_base64(_DEFAULT_OPTIONS),"),
    _m(FACTORY, "header and back extra are not swapped",
       "                else html.escape(header, quote=False)",
       "                else html.escape(back_extra, quote=False)"),
    _m(FACTORY, "plain text is escaped before it reaches an HTML field",
       "                else html.escape(header, quote=False)",
       "                else header"),
    _m(FACTORY, "the back extra is escaped too",
       "                else html.escape(back_extra, quote=False)",
       "                else back_extra"),
    _m(FACTORY, "an untouched field is written back verbatim",
       "                header_html if header_html is not None",
       "                None if header_html is not None"),
    _m(FACTORY, "the note type name comes from the spec",
       "            notetype_name=spec.name,", '            notetype_name="",'),
    _m(FACTORY, "the build defaults are the domain defaults",
       "_DEFAULT_OPTIONS = CardOptions()", "_DEFAULT_OPTIONS = CardOptions(mode=CardMode.SINGLE)"),

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
    # -------------------------------------------------- reviewer: the bootstrap
    _m(RENDER, "the once-per-show guard holds", "      if (ran) return;", "      if (false) return;"),
    _m(RENDER, "the guard is armed after the first pass", "      ran = true;", "      ran = false;"),
    _m(RENDER, "the first paint mints a seed", "        render(true);", "        render(false);"),
    _m(RENDER, "a resize repaints without minting",
       "        window.setTimeout(function () {\n          render(false);\n        }, 0);",
       "        window.setTimeout(function () {\n          render(true);\n        }, 0);"),
    _m(RENDER, "an unlaid-out image is retried", "      if (attempt < 30) {", "      if (false) {"),
    _m(RENDER, "the retry is bounded", "      if (attempt < 30) {", "      if (true) {"),
    _m(RENDER, "the retry counts up", "          run(attempt + 1);", "          run(attempt);"),
    _m(RENDER, "an image with no size is retried",
       "      if (tries < 30) {", "      if (false) {"),
    _m(RENDER, "the watch for an unlaid-out image is bounded",
       "      if (tries < 30) {", "      if (true) {"),
    _m(RENDER, "the guard is spent only once there is something to measure",
       "      if (box.width && box.height) {", "      if (true) {"),
    _m(RENDER, "the resize listener is bound once",
       "    if (!window.__roResizeBound) {", "    if (true) {"),
    _m(RENDER, "the safety net gives load and error their chance first",
       "      }, 250);", "      }, 0);"),
    _m(RENDER, "the safety net is not a quarter of a minute",
       "      }, 250);", "      }, 25000);"),
    _m(RENDER, "the load listener detaches itself",
       '      img.addEventListener("load", function () {\n        go(0);\n      }, { once: true });',
       '      img.addEventListener("load", function () {\n        go(0);\n      });'),

    # --------------------------------------------- reviewer: the cycler's paint
    _m(RENDER, "the question side shows the prompt, not the answer",
       "          drawBox(svg, layout.centers[ci], layout.targets[ci], cfg.promptText, cfg, true, undefined, layout.targets[ci].label, true);",
       "          drawBox(svg, layout.centers[ci], layout.targets[ci], layout.targets[ci].label, cfg, true, undefined, layout.targets[ci].label, true);"),
    _m(RENDER, "a locate marker is drawn without an arrow",
       "          drawBox(svg, layout.centers[ci], layout.targets[ci], currentStructure().label, cfg, false, undefined, undefined, false);",
       "          drawBox(svg, layout.centers[ci], layout.targets[ci], currentStructure().label, cfg, true, undefined, undefined, false);"),
    Mutation(RENDER, "a locate marker never wraps for a prompt it cannot show",
             "          drawBox(svg, layout.centers[ci], layout.targets[ci], currentStructure().label, cfg, false, undefined, undefined, false);",
             "          drawBox(svg, layout.centers[ci], layout.targets[ci], currentStructure().label, cfg, false, undefined, undefined, true);",
             survives=True,
             why="Since the clamp was made label-only, `flips` no longer moves any "
                 "centre -- it only caps the width the box wraps to, and a swept "
                 "6400-layout probe (stages 200-800, labels up to 43 chars, 25 "
                 "seeds) found NO layout where the prompt's width reshapes a box "
                 "that never shows it, so the wrong value here changes nothing "
                 "observable. Kept because it states which boxes can show a text "
                 "the clamp never measured, which is what stops a wide prompt "
                 "hanging off the image if the geometry ever tightens."),
    _m(RENDER, "the answer key draws every answered marker",
       "      for (var p = 0; p < state.idx && p < n; p++) {", "      for (var p = 0; p < 0 && p < n; p++) {"),
    _m(RENDER, "the answer key draws each marker from its own slot",
       "        var ai = layout.order[p];", "        var ai = layout.order[0];"),
    _m(RENDER, "the current marker is drawn",
       "      if (state.idx < n) {\n        if (state.revealed) {", "      if (false) {\n        if (state.revealed) {"),
    _m(RENDER, "the current marker is the one the cycle is on",
       "      var ci = state.idx < n ? layout.order[state.idx] : -1;",
       "      var ci = state.idx < n ? layout.order[0] : -1;"),
    _m(RENDER, "revealing shows the label", "        if (state.revealed) {", "        if (false) {"),
    _m(RENDER, "a correct answer is marked correct", '      if (result === "correct") return "ro-correct";', '      if (result === "correct") return undefined;'),
    _m(RENDER, "a wrong answer is marked wrong", '      if (result === "wrong") return "ro-wrong";', '      if (result === "wrong") return undefined;'),
    _m(RENDER, "the grading colour follows the answered marker",
       "boxClass(state.results[p]), undefined, forwards[p]);",
       "boxClass(state.results[0]), undefined, forwards[p]);"),
    Mutation(RENDER, "the answer key wraps like the question side did",
             "boxClass(state.results[p]), undefined, forwards[p]);",
             "boxClass(state.results[p]), undefined, true);",
             survives=True,
             why="Since the clamp was made label-only, `flips` no longer moves any "
                 "centre -- it only caps the width the box wraps to, and a swept "
                 "6400-layout probe (stages 200-800, labels up to 43 chars, 25 "
                 "seeds) found NO layout where the prompt's width reshapes a box "
                 "that never shows it, so the wrong value here changes nothing "
                 "observable. Kept because it states which boxes can show a text "
                 "the clamp never measured, which is what stops a wide prompt "
                 "hanging off the image if the geometry ever tightens."),
    Mutation(RENDER, "the single-card back reproduces the front's wrap",
             "cfg, true, undefined, undefined, slot >= 0 && dirs[slot]);",
             "cfg, true, undefined, undefined, true);",
             survives=True,
             why="Since the clamp was made label-only, `flips` no longer moves any "
                 "centre -- it only caps the width the box wraps to, and a swept "
                 "6400-layout probe (stages 200-800, labels up to 43 chars, 25 "
                 "seeds) found NO layout where the prompt's width reshapes a box "
                 "that never shows it, so the wrong value here changes nothing "
                 "observable. Kept because it states which boxes can show a text "
                 "the clamp never measured, which is what stops a wide prompt "
                 "hanging off the image if the geometry ever tightens."),
    _m(RENDER, "the cycler controller is built once",
       "    if (!bar.__roController) {", "    if (true) {"),

    # ------------------------------------------- reviewer: the elimination leak
    _m(RENDER, "a reverse question side withholds the target's dot",
       "        if (d === activeIndex ? dotTarget : cfg.showDecoyDots) {",
       "        if (d === activeIndex ? true : cfg.showDecoyDots) {"),
    _m(RENDER, "context boxes keep their arrows",
       "          drawBox(svg, centers[b], targets[b], targets[b].label, cfg, true);",
       "          drawBox(svg, centers[b], targets[b], targets[b].label, cfg, activeArrow);"),
    _m(RENDER, "context decoy dots follow the config",
       "        if (d === activeIndex ? dotTarget : cfg.showDecoyDots) {",
       "        if (d === activeIndex ? dotTarget : true) {"),
    _m(RENDER, "the cycler dots only structures an arrow points at",
       "      }\n      drawDots(svg, dotted);",
       "      }\n      drawDots(svg, layout.targets);"),
    _m(RENDER, "the current marker is dotted only once it has an arrow",
       "      var currentArrowed = ci >= 0 && (state.revealed || currentForward());",
       "      var currentArrowed = ci >= 0;"),
    _m(RENDER, "an interior target is left from the opposite border",
       "    return { x: cx - dx * scale, y: cy - dy * scale };",
       "    return { x: cx + dx * scale, y: cy + dy * scale };"),
    _m(RENDER, "an arrow to an interior target is still drawn",
       "    if (scale <= 1) return { x: cx + dx * scale, y: cy + dy * scale };",
       "    if (true) return { x: cx + dx * scale, y: cy + dy * scale };"),
    _m(RENDER, "a target on the centre still gets a line",
       "    if (dx === 0 && dy === 0) return { x: cx, y: cy - box.h / 2 };",
       "    if (dx === 0 && dy === 0) return { x: cx, y: cy };"),
    _m(RENDER, "the clamp covers the prompt as well as the label",
       "      if (promptBox.w > clampBox.w) clampBox.w = promptBox.w;",
       "      if (false) clampBox.w = promptBox.w;"),
    _m(RENDER, "the clamp covers the prompt's height too",
       "      if (promptBox.h > clampBox.h) clampBox.h = promptBox.h;",
       "      if (false) clampBox.h = promptBox.h;"),
    _m(RENDER, "only a flipping box is clamped for the prompt",
       "    if (flips) {", "    if (true) {"),
    _m(RENDER, "an unstorable seed falls back to the shared value",
       "      if (!seedPersisted(seed)) {",
       "      if (false) {"),
    _m(RENDER, "seedPersisted ignores the in-memory mirror",
       '    return readFrom("sessionStorage") === wanted || readFrom("localStorage") === wanted;',
       "    return readSeed() !== null;"),
    Mutation(RENDER, "seedPersisted compares the value, not mere presence",
             '    return readFrom("sessionStorage") === wanted || readFrom("localStorage") === wanted;',
             '    return readFrom("sessionStorage") !== null || readFrom("localStorage") !== null;',
             survives=True,
             why="writeSeed now removes the key from whichever store refused the "
                 "write, so by the time this runs each store holds either THIS "
                 "card's seed or nothing -- presence and equality coincide. The "
                 "comparison is kept because it is what makes that reasoning local: "
                 "it stays correct even if a removal is ever missed, which is the "
                 "bug it was written for."),
    _m(RENDER, "seedPersisted accepts either durable store",
       '    return readFrom("sessionStorage") === wanted || readFrom("localStorage") === wanted;',
       '    return readFrom("sessionStorage") === wanted;'),
    _m(RENDER, "a refused durable write drops the stale value",
       "        window.localStorage.removeItem(SEED_KEY);", "        void 0;"),
    _m(RENDER, "decoy dots are drawn",
       "      // Decoy dots (all markers) force the learner to follow the arrow to the\n      // right one instead of recognising a lone dot.\n      if (cfg.showDecoyDots) {",
       "      // Decoy dots (all markers) force the learner to follow the arrow to the\n      // right one instead of recognising a lone dot.\n      if (false) {"),
    _m(RENDER, "the context dot loop covers every structure",
       "      for (var d = 0; d < targets.length; d++) {", "      for (var d = 0; d < 1; d++) {"),
    _m(RENDER, "dots sit on their structures", 'svgEl("circle", { class: "ro-dot", cx: target.x, cy: target.y, r: "5" })', 'svgEl("circle", { class: "ro-dot", cx: 0, cy: 0, r: "5" })'),
    _m(RENDER, "the measured label is cleared before the tspans", '    label.textContent = "";', "    "),
    _m(RENDER, "the lone target dot is drawn",
       "      } else if (targetDotVisible(cfg, isReverse, back)) {\n        drawDot(svg, active);\n      }\n      var center = placeCenter(rng, stage, active, cfg);",
       "      } else if (false) {\n        drawDot(svg, active);\n      }\n      var center = placeCenter(rng, stage, active, cfg);"),
    _m(RENDER, "the context target dot follows targetDotVisible",
       "      var dotTarget = targetDotVisible(cfg, isReverse, back);",
       "      var dotTarget = true;"),
    _m(RENDER, "single mode honours showTargetDot",
       "      if (cfg.showTargetDot) {\n        for (var d = 0; d < state.idx && d < n; d++) {",
       "      if (true) {\n        for (var d = 0; d < state.idx && d < n; d++) {"),
    _m(RENDER, "the single-card answer key honours showTargetDot",
       "      if (cfg.showTargetDot) drawDots(svg, layout.targets);",
       "      drawDots(svg, layout.targets);"),
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
    _m(RENDER, "a null stored seed falls through",
       '    var stored = readFrom("sessionStorage");\n    if (stored !== null) return stored;',
       '    var stored = readFrom("sessionStorage");\n    return stored;'),
    _m(RENDER, "the seed is read back from the durable store",
       '    stored = readFrom("localStorage");\n    if (stored !== null) return stored;',
       '    stored = null;'),
    _m(RENDER, "the seed is written to the durable store",
       "      window.localStorage.setItem(SEED_KEY, String(value));", "      void 0;"),
    _m(RENDER, "a refused session write drops the stale value",
       "        window.sessionStorage.removeItem(SEED_KEY);", "        void 0;"),
    _m(RENDER, "the stored seed is read back", "    return window.__roSeedFallback || null;", "    return null;"),

    # ------------------------------------------------- reviewer: payload/config
    _m(RENDER, "the note's config is applied", "        cfg = JSON.parse(decodeBase64Utf8(raw));", "        cfg = {};"),
    _m(RENDER, "a config value overrides the default", "        merged[key] = key in cfg ? cfg[key] : DEFAULT_CONFIG[key];", "        merged[key] = DEFAULT_CONFIG[key];"),
    _m(RENDER, "legacy bare-array payloads still render", "    if (Array.isArray(parsed)) {", "    if (false) {"),
    _m(RENDER, "the answer is NFC-normalised before grading",
       '    return s.normalize ? s.normalize("NFC") : s;', "    return s;"),
    Mutation(RENDER, "a WebView without normalize still grades",
             '    return s.normalize ? s.normalize("NFC") : s;',
             '    return s.normalize("NFC");',
             survives=True,
             why="The guard exists for a WebView with no String.prototype.normalize. "
                 "Node always has it, and the tests share one realm with the vm "
                 "sandbox, so deleting it would break the harness rather than the "
                 "card. Kept because the fallback is what stops the card throwing "
                 "before its first paint on an old Android."),
    _m(RENDER, "the arrowhead orients along its line",
       '      orient: "auto",', '      orient: "auto-start-reverse",'),
    _m(RENDER, "Enter presses the button the bar is showing",
       "        if (!e.repeat) onButton();", "        if (!e.repeat) reveal();"),
    _m(RENDER, "a held Enter does not grade and advance at once",
       "        if (!e.repeat) onButton();", "        onButton();"),
    _m(RENDER, "base64 is decoded as UTF-8, not Latin-1",
       "    return decodeURIComponent(escape(atob(b64)));",
       "    return atob(b64);"),
    Mutation(RENDER, "imul falls back where the built-in is missing",
             "    Math.imul ||", "    null ||",
             survives=True,
             why="Forcing the fallback changes no output, which is exactly the point: "
                 "the polyfill agrees with Math.imul on every input the seed code "
                 "feeds it, so the placement is identical on a WebView that lacks "
                 "the built-in. A kill here would mean the two had diverged."),
    _m(RENDER, "hypot2 is a real hypotenuse",
       "    return Math.sqrt(dx * dx + dy * dy);", "    return dx + dy;"),
    _m(RENDER, "keyName reads the event key",
       "    if (e.key) return e.key;", "    if (false) return e.key;"),
    _m(RENDER, "an orphaned card falls back to the first structure",
       "    if (activeIndex < 0) activeIndex = 0;", ""),
    _m(RENDER, "the active ordinal is looked up, not subtracted from",
       "      if (Number(structures[i].ord) === activeOrdinal) {",
       "      if (i === activeOrdinal - 1) {"),

    # ------------------------------------------------------- clipboard: choices
    _m(CLIPBOARD, "svg keeps its extension", '("image/svg+xml", ".svg"),', '("image/svg+xml", ".png"),'),
    _m(CLIPBOARD, "gif keeps its extension", '("image/gif", ".gif"),', '("image/gif", ".png"),'),
    _m(CLIPBOARD, "jpeg keeps its extension", '("image/jpeg", ".jpg"),', '("image/jpeg", ".png"),'),
    _m(CLIPBOARD, "bmp stays pickable as a file",
       '        ".avif", ".bmp", ".ico", ".svg",',
       '        ".avif", ".ico", ".svg",'),
    _m(CLIPBOARD, "the JPEG aliases Windows writes are accepted",
       '        ".png", ".jpg", ".jpeg", ".jfif", ".jpe", ".gif", ".webp",',
       '        ".png", ".jpg", ".jpeg", ".gif", ".webp",'),
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

    # ------------------------------------------------- reviewer key override
    _m(SHORTCUTS, "only the question side is intercepted",
       '    if main_state != "review" or reviewer_state != "question":',
       '    if main_state != "review":'),
    _m(SHORTCUTS, "only the reviewer state is intercepted",
       '    if main_state != "review" or reviewer_state != "question":',
       '    if reviewer_state != "question":'),
    _m(SHORTCUTS, "only our own note type is intercepted",
       "    if not notetype_name or notetype_name != our_notetype_name:",
       "    if False:"),
    _m(SHORTCUTS, "only single-card mode is intercepted",
       "    return single_card_mode", "    return True"),
    _m(SHORTCUTS, "only the review state gets new bindings",
       '        if state != "review":\n            return',
       "        if False:\n            return"),
    _m(SHORTCUTS, "the keys are appended, not substituted",
       "        shortcuts.extend((key, handler) for key in _KEYS)",
       "        shortcuts[:] = [(key, handler) for key in _KEYS]"),
    _m(SHORTCUTS, "a key we do not want falls through to Anki",
       "        if not intercept:\n            mw.reviewer.onEnterKey()",
       "        if False:\n            mw.reviewer.onEnterKey()"),
    _m(SHORTCUTS, "an intercepted key does not also flip the card",
       "            mw.reviewer.onEnterKey()\n            return",
       "            mw.reviewer.onEnterKey()"),
    _m(SHORTCUTS, "a broken note falls through rather than raising",
       "        except Exception:\n            intercept = False",
       "        except Exception:\n            raise"),

    # ----------------------------------------------------------------- config
    _m(CONFIG, "zoom clamp range", "return max(MIN_EDITOR_ZOOM, min(MAX_EDITOR_ZOOM, value))", "return value"),
    _m(CONFIG, "zoom clamp rejects bad types",
       "        except (TypeError, ValueError, OverflowError):",
       "        except OverflowError:"),
    _m(CONFIG, "zoom clamp survives an out-of-range integer",
       "        except (TypeError, ValueError, OverflowError):",
       "        except (TypeError, ValueError):"),
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

    _m(SCRATCH, "a superseded paste is reclaimed",
       "        previous, self._latest = self._latest, path",
       "        previous, self._latest = None, path"),
    _m(SCRATCH, "reclamation happens only after a successful write",
       "        partial = path + PARTIAL\n        try:",
       "        partial = path + PARTIAL\n        previous, self._latest = self._latest, path\n        if previous is not None:\n            with contextlib.suppress(OSError):\n                os.unlink(previous)\n        try:"),
    _m(SCRATCH, "each paste gets its own filename",
       "        self._sequence += 1", "        pass"),
    _m(SCRATCH, "the sequence is part of the name",
       "        stamp = f'{self._now().strftime(\"%Y%m%d-%H%M%S\")}-{self._sequence}'",
       "        stamp = self._now().strftime(\"%Y%m%d-%H%M%S\")"),

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

    _m(READER, "a malformed structure entry is reported as unreadable",
       "        except (KeyError, TypeError, OverflowError) as exc:",
       "        except KeyError as exc:"),
    _m(READER, "an out-of-range number is reported as unreadable",
       "        except (KeyError, TypeError, OverflowError) as exc:",
       "        except (KeyError, TypeError) as exc:"),
    _m(READER, "a readable validation message is kept",
       "            raise ValueError(str(exc) or _MALFORMED) from exc",
       "            raise ValueError(_MALFORMED) from exc"),

    # ------------------------------------------------------ note type: templates
    _m(TEMPLATES, "the header sentinel is substituted",
       '_FRONT_TEMPLATE.replace("__RO_HEADER__", s.header_field)',
       '_FRONT_TEMPLATE.replace("__RO_HEADER__", s.back_extra_field)'),
    _m(TEMPLATES, "the image sentinel is substituted",
       '.replace("__RO_IMAGE__", s.image_field)', '.replace("__RO_IMAGE__", s.cloze_field)'),
    _m(TEMPLATES, "the type-flag sentinel is substituted",
       '.replace("__RO_TYPEFLAG__", s.type_flag_field)', '.replace("__RO_TYPEFLAG__", s.header_field)'),
    _m(TEMPLATES, "the front's cloze sentinel is substituted",
       '            .replace("__RO_CLOZE__", s.cloze_field)', '            .replace("__RO_CLOZE__", s.header_field)'),
    _m(TEMPLATES, "the structures sentinel is substituted",
       '.replace("__RO_STRUCTURES__", s.structures_field)', '.replace("__RO_STRUCTURES__", s.cloze_field)'),
    _m(TEMPLATES, "the config blob is embedded",
       '.replace("__RO_CONFIG__", encode_json_b64(render_config.behaviour()))',
       '.replace("__RO_CONFIG__", "")'),
    _m(TEMPLATES, "the reviewer js is embedded",
       '.replace("__RO_RENDER_JS__", self._render_js)', '.replace("__RO_RENDER_JS__", "")'),
    _m(TEMPLATES, "the reviewer js is neutralised on the way in",
       "self._render_js = _script_safe(render_js)", "self._render_js = render_js"),
    _m(TEMPLATES, "a closing tag inside the script is broken up",
       'return text.replace("</", "<\\\\/")', "return text"),
    _m(TEMPLATES, "the back's cloze sentinel is substituted",
       '_BACK_TEMPLATE.replace("__RO_CLOZE__", s.cloze_field)',
       '_BACK_TEMPLATE.replace("__RO_CLOZE__", s.header_field)'),
    _m(TEMPLATES, "the back-extra sentinel is substituted",
       '            "__RO_BACKEXTRA__", s.back_extra_field',
       '            "__RO_BACKEXTRA__", s.header_field'),
    _m(TEMPLATES, "the css carries its fingerprint comment",
       'css = f"/* ro-fingerprint:{fingerprint} */\\n" + css_body', "css = css_body"),
    _m(TEMPLATES, "the css variables are substituted",
       'return _CARD_CSS.replace("__RO_VARIABLES__", variables)', "return _CARD_CSS"),
    _m(TEMPLATES, "the css variables come from the config",
       'f"  {name}: {value};\\n"', 'f"  {name}: inherit;\\n"'),
    _m(TEMPLATES, "the fingerprint marker anchors the search",
       '_FINGERPRINT_RE = re.compile(r"ro-fingerprint:([0-9a-f]+)")',
       '_FINGERPRINT_RE = re.compile(r"([0-9a-f]+)")'),
    _m(TEMPLATES, "the fingerprint covers the front",
       'payload = "\\n".join([str(TEMPLATE_VERSION), front, back, css_body])',
       'payload = "\\n".join([str(TEMPLATE_VERSION), back, css_body])'),
    _m(TEMPLATES, "the fingerprint covers the back",
       'payload = "\\n".join([str(TEMPLATE_VERSION), front, back, css_body])',
       'payload = "\\n".join([str(TEMPLATE_VERSION), front, css_body])'),
    _m(TEMPLATES, "the fingerprint covers the css body",
       'payload = "\\n".join([str(TEMPLATE_VERSION), front, back, css_body])',
       'payload = "\\n".join([str(TEMPLATE_VERSION), front, back])'),
    _m(TEMPLATES, "the fingerprint covers the version lever",
       'payload = "\\n".join([str(TEMPLATE_VERSION), front, back, css_body])',
       'payload = "\\n".join([front, back, css_body])'),
    _m(TEMPLATES, "the fingerprint separates the parts it hashes",
       'payload = "\\n".join([str(TEMPLATE_VERSION), front, back, css_body])',
       'payload = "".join([str(TEMPLATE_VERSION), front, back, css_body])'),
    _m(TEMPLATES, "the fingerprint is twelve hex characters",
       'return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]',
       'return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:6]'),
    _m(TEMPLATES, "TEMPLATE_VERSION is a live lever", "TEMPLATE_VERSION = 1", "TEMPLATE_VERSION = 2"),
    _m(TEMPLATES, "the variables block drops its trailing newline",
       '    ).rstrip("\\n")', "    )"),

    # ------------------------------------------------------------ card options
    _m(OPTIONS, "a member passes through coerce untouched",
       "        if isinstance(value, cls):\n            return value", "        if False:\n            return value"),
    _m(OPTIONS, "an unrecognised value falls back to the default",
       "        except ValueError:\n            return default", "        except ValueError:\n            raise"),
    _m(OPTIONS, "coerce survives a non-string",
       "            return cls(str(value).strip().lower())", "            return cls(value.strip().lower())"),
    _m(OPTIONS, "coerce ignores surrounding whitespace",
       "            return cls(str(value).strip().lower())", "            return cls(str(value).lower())"),
    _m(OPTIONS, "coerce ignores case",
       "            return cls(str(value).strip().lower())", "            return cls(str(value).strip())"),
    _m(OPTIONS, "forward is the wire spelling", '    FORWARD = "forward"  # name the arrowed structure', '    FORWARD = "fwd"  # name the arrowed structure'),
    _m(OPTIONS, "single is the wire spelling", '    SINGLE = "single"  # one card that cycles through all structures', '    SINGLE = "one"  # one card that cycles through all structures'),
    _m(OPTIONS, "CardOptions defaults to the forward direction", "    direction: Direction = Direction.FORWARD", "    direction: Direction = Direction.REVERSE"),
    _m(OPTIONS, "the default interaction is reveal", "    interaction: Interaction = Interaction.REVEAL", "    interaction: Interaction = Interaction.TYPE"),
    _m(OPTIONS, "context labels are off by default", "    context_labels: bool = False", "    context_labels: bool = True"),
    _m(OPTIONS, "the default card model is multi", "    mode: CardMode = CardMode.MULTI", "    mode: CardMode = CardMode.SINGLE"),
    _m(OPTIONS, "from_config coerces the direction",
       "            direction=Direction.coerce(config.get(\"direction\"), Direction.FORWARD),",
       "            direction=Direction.FORWARD,"),
    _m(OPTIONS, "from_config coerces the interaction",
       "            interaction=Interaction.coerce(\n                config.get(\"interaction\"), Interaction.REVEAL\n            ),",
       "            interaction=Interaction.REVEAL,"),
    _m(OPTIONS, "from_config reads the card_mode key",
       "            mode=CardMode.coerce(config.get(\"card_mode\"), CardMode.MULTI),",
       "            mode=CardMode.coerce(config.get(\"mode\"), CardMode.MULTI),"),
    _m(OPTIONS, "from_config reads the show_context_labels key",
       "            context_labels=coerce_bool(config.get(\"show_context_labels\"), False),",
       "            context_labels=coerce_bool(config.get(\"context_labels\"), False),"),
    _m(OPTIONS, "an absent context-labels key reads as off",
       "            context_labels=coerce_bool(config.get(\"show_context_labels\"), False),",
       "            context_labels=coerce_bool(config.get(\"show_context_labels\"), True),"),

    # ----------------------------------------------------------------- savers
    _m(SAVERS, "the reported count is cards, not structures",
       "        count = result.structures.card_count(result.options)",
       "        count = len(result.structures)"),
    _m(SAVERS, "the count is taken with the note's own options",
       "        count = result.structures.card_count(result.options)",
       "        count = result.structures.card_count(CardOptions())"),
    _m(SAVERS, "the op is parented away from the dialog",
       "            parent=_progress_parent(dialog),\n            request=request,\n            render_config=self._config.render_config(),\n            spec=self._spec,\n            on_success=lambda _changes: dialog.finish_saved(f\"Added {_cards(count)}.\"),",
       "            parent=dialog,\n            request=request,\n            render_config=self._config.render_config(),\n            spec=self._spec,\n            on_success=lambda _changes: dialog.finish_saved(f\"Added {_cards(count)}.\"),"),
    _m(SAVERS, "the update op is parented away from the dialog",
       "            parent=_progress_parent(dialog),\n            request=request,\n            render_config=self._config.render_config(),\n            spec=self._spec,\n            on_success=lambda _changes: dialog.finish_saved(\"Card updated.\"),",
       "            parent=dialog,\n            request=request,\n            render_config=self._config.render_config(),\n            spec=self._spec,\n            on_success=lambda _changes: dialog.finish_saved(\"Card updated.\"),"),
    _m(SAVERS, "a dialog offering no parent falls back to itself",
       "        return dialog.progress_parent\n    return dialog",
       "        return dialog.progress_parent\n    return None"),
    _m(SAVERS, "a chosen deck is used", '        deck = result.deck_name or "Default"', '        deck = "Default"'),
    _m(SAVERS, "no deck falls back to Default", '        deck = result.deck_name or "Default"', "        deck = result.deck_name"),
    _m(SAVERS, "the chosen deck is remembered", "        self._config.set_deck(deck)", "        pass"),
    _m(SAVERS, "the deck reaches the request", "            deck_name=deck,", '            deck_name="",'),
    _m(SAVERS, "the created note carries the marked structures",
       "            structures=result.structures,\n            deck_name=deck,",
       "            structures=result.structures[:0],\n            deck_name=deck,"),
    _m(SAVERS, "creating reports success to the dialog",
       '            on_success=lambda _changes: dialog.finish_saved(f"Added {_cards(count)}."),',
       "            on_success=lambda _changes: None,"),
    _m(SAVERS, "creating reports failure to the dialog",
       '            on_failure=lambda exc: dialog.save_failed(f"Could not add the card:\\n\\n{exc}"),',
       "            on_failure=lambda exc: None,"),
    _m(SAVERS, "the update targets the opened note", "            note_id=self._note_id,", "            note_id=0,"),
    _m(SAVERS, "the update keeps the existing image filename",
       '            existing_image_filename=result.existing_image_filename or "",',
       '            existing_image_filename="",'),
    _m(SAVERS, "the update carries a newly chosen image",
       "            new_image_path=result.new_image_path,", "            new_image_path=None,"),
    _m(SAVERS, "updating reports success to the dialog",
       '            on_success=lambda _changes: dialog.finish_saved("Card updated."),',
       "            on_success=lambda _changes: None,"),
    _m(SAVERS, "updating reports failure to the dialog",
       '            on_failure=lambda exc: dialog.save_failed(f"Could not update the card:\\n\\n{exc}"),',
       "            on_failure=lambda exc: None,"),
    _m(SAVERS, "the plural rule is applied to cards", '    return count_phrase(count, "card")', '    return f"{count} card"'),

    # ------------------------------------------------- note type: construction
    _m(NOTETYPE_FACTORY, "the bundled reviewer js is loaded into the assembler",
       'return TemplateAssembler(spec, read_web("review/render.js"))',
       'return TemplateAssembler(spec, "")'),
    _m(NOTETYPE_FACTORY, "the assembler is built for the requested spec",
       'return TemplateAssembler(spec, read_web("review/render.js"))',
       'return TemplateAssembler(DEFAULT_SPEC, read_web("review/render.js"))'),
    _m(NOTETYPE_FACTORY, "build_assembler defaults to the canonical spec",
       "def build_assembler(spec: NoteTypeSpec = DEFAULT_SPEC) -> TemplateAssembler:",
       "def build_assembler(spec: NoteTypeSpec = None) -> TemplateAssembler:"),
    _m(NOTETYPE_FACTORY, "the installer and its assembler share one spec",
       "return NoteTypeInstaller(AnkiModelGateway(collection), build_assembler(spec), spec)",
       "return NoteTypeInstaller(AnkiModelGateway(collection), build_assembler(), spec)"),
    _m(NOTETYPE_FACTORY, "the installer is given the assembler's spec",
       "return NoteTypeInstaller(AnkiModelGateway(collection), build_assembler(spec), spec)",
       "return NoteTypeInstaller(AnkiModelGateway(collection), build_assembler(spec), DEFAULT_SPEC)"),
    _m(NOTETYPE_FACTORY, "the gateway is bound to the caller's collection",
       "return NoteTypeInstaller(AnkiModelGateway(collection), build_assembler(spec), spec)",
       "return NoteTypeInstaller(AnkiModelGateway(None), build_assembler(spec), spec)"),

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


@dataclass
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
        cwd=ROOT,
        input=json.dumps(sources).encode("utf-8"),
        capture_output=True,
        # The same scrubbing run() does. Without it NODE_OPTIONS could inject a
        # --require into the check that validates the campaign, which is the one
        # place the hardening had a hole.
        env=_child_env(),
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
