/*
 * Randomized Image Occlusion — reviewer renderer.
 *
 * This file is *embedded into the card template* at note-type install time (it
 * is NOT shipped as a media file), so synced cards render correctly on every
 * client — desktop, AnkiDroid, AnkiMobile — without the add-on installed.
 *
 * Responsibilities:
 *   1. Read the structures (base64 JSON) and config out of the DOM.
 *   2. Determine which structure this card tests (the active cloze ordinal).
 *   3. Place the prompt box at a *randomised* position each review, drawing a
 *      leader-line arrow from the box to the structure's fixed target.
 *   4. Keep the front and back of a single review identical by sharing one
 *      per-review seed (sessionStorage, with a window-global fallback).
 *
 * Everything is wrapped in an IIFE: Anki reuses one webview across cards on the
 * desktop, so top-level `let`/`const`/`class` would throw "already declared" on
 * the second card. Assigning to `window.RandomizedOcclusion` is re-entrant-safe.
 */
(function () {
  "use strict";

  var SEED_KEY = "randomizedOcclusion.seed";

  var DEFAULT_CONFIG = {
    minArrowFraction: 0.22, // shortest arrow as a fraction of the stage diagonal
    showTargetDot: true,
    promptText: "?",
    maxPlacementAttempts: 48,
    showDecoyDots: true,
    showContextLabels: false,
  };

  // Placement tuning, as fractions of the stage, named so the geometry reads
  // clearly. (Changing these changes where boxes land; the seed is unaffected.)
  var MARGIN_X_FRACTION = 0.14; // keep box centres this far from the L/R edges
  var MARGIN_Y_FRACTION = 0.1; // ...and from the top/bottom edges
  var MAX_ARROW_FRACTION = 0.6; // longest arrow (single occlusion), of the diagonal
  var MAX_ARROW_FRACTION_MULTI = 0.5; // longest arrow when placing many boxes
  var MIN_SEPARATION_FRACTION = 0.2; // min gap between box centres (multi/cycler)
  var ACCEPT_ARROW_FRACTION = 0.8; // accept a candidate whose arrow >= this * minLen

  // Prompt-box sizing, in px (the box grows to fit its text but never smaller).
  var BOX_PADDING_X = 12; // horizontal padding around the label text
  var BOX_PADDING_Y = 8; // vertical padding around the label text
  var BOX_MIN_WIDTH = 36; // keep even a one-character box legible/tappable
  var BOX_MIN_HEIGHT = 30;

  // ---- small utilities ------------------------------------------------------

  /** Decode UTF-8-safe base64 into a string. */
  function decodeBase64Utf8(b64) {
    var binary = atob(b64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new TextDecoder("utf-8").decode(bytes);
  }

  /** Deterministic 32-bit string hash (used only for the seedless fallback). */
  function hashString(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  /** A fresh random unsigned 32-bit seed (`>>> 0` forces the unsigned range). */
  function randomUint32() {
    return Math.floor(Math.random() * 0xffffffff) >>> 0;
  }

  /** mulberry32 — tiny seeded PRNG returning floats in [0, 1). */
  function makeRng(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /**
   * A stable per-review forward/reverse coin for "both" mode, drawn from a
   * SEPARATE seed stream so it never perturbs the placement rng. Returns true for
   * forward, false for reverse; the front and back of one review share the seed,
   * so they always agree.
   */
  function directionCoin(seed) {
    return makeRng((seed ^ 0x9e3779b9) >>> 0)() < 0.5;
  }

  function readSeed() {
    try {
      return window.sessionStorage.getItem(SEED_KEY);
    } catch (e) {
      return window.__roSeedFallback || null;
    }
  }

  function writeSeed(value) {
    try {
      window.sessionStorage.setItem(SEED_KEY, String(value));
    } catch (e) {
      window.__roSeedFallback = String(value);
    }
  }

  // ---- DOM reading ----------------------------------------------------------

  function readConfig() {
    // Config is embedded as base64 JSON (like the structures) so user-editable
    // values (prompt_text, colours) can never break out of the <script> element
    // or be mistaken for an Anki template field directive.
    // NOTE: this whole file is inlined into the card template, so it must never
    // contain a double-brace field token — Anki would try to resolve it.
    var el = document.getElementById("ro-config");
    var raw = el ? (el.textContent || "").trim() : "";
    var cfg = {};
    if (raw) {
      try {
        cfg = JSON.parse(decodeBase64Utf8(raw));
      } catch (e) {
        cfg = {};
      }
    }
    var merged = {};
    for (var key in DEFAULT_CONFIG) {
      if (Object.prototype.hasOwnProperty.call(DEFAULT_CONFIG, key)) {
        merged[key] = key in cfg ? cfg[key] : DEFAULT_CONFIG[key];
      }
    }
    return merged;
  }

  /**
   * The note payload (self-describing, so a note renders correctly regardless of
   * the current global config). v2 shape:
   *   {v:2, mode:"multi"|"single", direction:"forward"|"reverse"|"both",
   *    contextLabels:bool, structures:[{ord,x,y,label}, ...]}
   * v1 (older notes) was a bare structures array, treated as multi/forward.
   */
  function readData() {
    var el = document.getElementById("ro-data");
    var b64 = el ? (el.textContent || "").trim() : "";
    var parsed = null;
    if (b64) {
      try {
        parsed = JSON.parse(decodeBase64Utf8(b64));
      } catch (e) {
        parsed = null;
      }
    }
    if (Array.isArray(parsed)) {
      return { mode: "multi", direction: "forward", contextLabels: undefined, structures: parsed };
    }
    if (parsed && Array.isArray(parsed.structures)) {
      return {
        mode: parsed.mode === "single" ? "single" : "multi",
        direction: parsed.direction || "forward",
        contextLabels: parsed.contextLabels,
        structures: parsed.structures,
      };
    }
    return { mode: "multi", direction: "forward", contextLabels: undefined, structures: [] };
  }

  /**
   * The active cloze ordinal identifies this card. Anki renders the active
   * deletion as `<span class="cloze" data-ordinal="N">` and the others as
   * `class="cloze-inactive"`, so `.cloze` selects the active one.
   */
  function readActiveOrdinal() {
    var active = document.querySelector("#ro-ordinal .cloze");
    if (active && active.dataset && active.dataset.ordinal) {
      return parseInt(active.dataset.ordinal, 10) || 1;
    }
    return 1;
  }

  function isBackSide() {
    return !!document.getElementById("ro-answer");
  }

  /**
   * The image is provided by the `Image` field as a full `<img src=...>` tag
   * (so Anki's media check detects the reference), hence we select it by
   * position inside the stage rather than by id.
   */
  function getImage() {
    var stage = document.getElementById("ro-stage");
    return stage ? stage.querySelector("img") : null;
  }

  // ---- geometry / placement -------------------------------------------------

  function clamp(value, lo, hi) {
    if (hi < lo) return lo;
    return Math.max(lo, Math.min(hi, value));
  }

  /**
   * Choose a randomised box CENTRE for this review.
   *
   * Deliberately independent of the box's text/size: the front shows "?" and
   * the back shows the (wider) label, so if placement depended on box width the
   * same seed could accept a different position on each side and the box would
   * jump on flip. Computing a size-independent centre means both sides derive
   * the IDENTICAL point and the box simply grows symmetrically around it.
   *
   * Centres are kept within a margin of the stage (a fraction of its size, so
   * this too is resolution-independent) to keep typical boxes on-image, and the
   * arrow (centre -> target) is at least `minLen` long. Never returns null.
   */
  /**
   * The point inside the [marginX, maxX] x [marginY, maxY] rectangle FARTHEST
   * from `target` — always a corner. Used as a deterministic fallback so the
   * arrow is as long as the geometry allows (never near-zero) when random
   * sampling can't find a long-enough placement (small image / high minArrow).
   */
  function farthestInMargin(target, marginX, marginY, maxX, maxY) {
    var x = Math.abs(marginX - target.x) >= Math.abs(maxX - target.x) ? marginX : maxX;
    var y = Math.abs(marginY - target.y) >= Math.abs(maxY - target.y) ? marginY : maxY;
    return { x: x, y: y };
  }

  function placeCenter(rng, stage, target, cfg) {
    var diag = Math.hypot(stage.w, stage.h);
    var minLen = cfg.minArrowFraction * diag;
    var maxLen = Math.max(minLen + 1, MAX_ARROW_FRACTION * diag);
    var marginX = stage.w * MARGIN_X_FRACTION;
    var marginY = stage.h * MARGIN_Y_FRACTION;
    var maxX = stage.w - marginX;
    var maxY = stage.h - marginY;

    for (var i = 0; i < cfg.maxPlacementAttempts; i++) {
      var angle = rng() * Math.PI * 2;
      var length = minLen + rng() * (maxLen - minLen);
      var cx = clamp(target.x + Math.cos(angle) * length, marginX, maxX);
      var cy = clamp(target.y + Math.sin(angle) * length, marginY, maxY);
      if (Math.hypot(cx - target.x, cy - target.y) >= minLen * ACCEPT_ARROW_FRACTION) {
        return { x: cx, y: cy };
      }
    }
    // No random candidate cleared the bar (constrained geometry): use the
    // farthest in-margin point so the arrow stays visible rather than near-zero.
    return farthestInMargin(target, marginX, marginY, maxX, maxY);
  }

  /**
   * Intersection of the segment from the box centre towards the target with the
   * box's border, so the arrow starts at the edge of the box rather than its
   * middle. Returns the box centre if target coincides with it (degenerate).
   */
  function boxBorderToward(box, target) {
    var cx = box.x + box.w / 2;
    var cy = box.y + box.h / 2;
    var dx = target.x - cx;
    var dy = target.y - cy;
    if (dx === 0 && dy === 0) return { x: cx, y: cy };

    var halfW = box.w / 2;
    var halfH = box.h / 2;
    // Scale (dx, dy) so it just reaches the rectangle border.
    var scaleX = dx !== 0 ? halfW / Math.abs(dx) : Infinity;
    var scaleY = dy !== 0 ? halfH / Math.abs(dy) : Infinity;
    var scale = Math.min(scaleX, scaleY);
    return { x: cx + dx * scale, y: cy + dy * scale };
  }

  // ---- SVG drawing ----------------------------------------------------------

  var SVG_NS = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    var el = document.createElementNS(SVG_NS, name);
    if (attrs) {
      for (var key in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, key)) {
          el.setAttribute(key, attrs[key]);
        }
      }
    }
    return el;
  }

  /** Match the SVG's user-space to a pixel size (width/height/viewBox). */
  function setSvgSize(svg, width, height) {
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  }

  function ensureArrowMarker(svg) {
    var defs = svgEl("defs");
    var marker = svgEl("marker", {
      id: "ro-arrowhead",
      class: "ro-arrowhead",
      markerWidth: "10",
      markerHeight: "10",
      refX: "8",
      refY: "5",
      orient: "auto-start-reverse",
      markerUnits: "userSpaceOnUse",
    });
    marker.appendChild(svgEl("path", { d: "M0,1 L9,5 L0,9 Z" }));
    defs.appendChild(marker);
    svg.appendChild(defs);
  }

  /** Draw a target marker at `target` ({x, y} in pixels). */
  function drawDot(svg, target) {
    svg.appendChild(
      svgEl("circle", { class: "ro-dot", cx: target.x, cy: target.y, r: "5" })
    );
  }

  /**
   * Draw a labelled box centred at `center` with a leader-line arrow to `target`.
   * Placement is decided by the caller (so front and back agree); this only
   * measures the text, sizes the box symmetrically around the centre, and draws.
   */
  function drawBox(svg, center, target, text, cfg, showArrow, extraClass) {
    var group = svgEl("g", { class: "ro-box" });
    var rectClass = extraClass ? "ro-box-rect " + extraClass : "ro-box-rect";
    var rect = svgEl("rect", { class: rectClass, rx: "8", ry: "8" });
    var label = svgEl("text", {
      class: "ro-box-text",
      "text-anchor": "middle",
      "dominant-baseline": "central",
    });
    label.textContent = text;
    group.appendChild(rect);
    group.appendChild(label);
    svg.appendChild(group);

    var textLen;
    try {
      textLen = label.getComputedTextLength();
    } catch (e) {
      textLen = String(text).length * 9;
    }
    var fontSize = parseFloat(window.getComputedStyle(label).fontSize) || 18;
    var box = {
      w: Math.max(BOX_MIN_WIDTH, textLen + BOX_PADDING_X * 2),
      h: Math.max(BOX_MIN_HEIGHT, fontSize + BOX_PADDING_Y * 2),
    };
    box.x = center.x - box.w / 2;
    box.y = center.y - box.h / 2;

    rect.setAttribute("x", box.x);
    rect.setAttribute("y", box.y);
    rect.setAttribute("width", box.w);
    rect.setAttribute("height", box.h);
    label.setAttribute("x", center.x);
    label.setAttribute("y", center.y);

    if (showArrow) {
      var start = boxBorderToward(box, target);
      var line = svgEl("line", {
        class: "ro-arrow",
        x1: start.x,
        y1: start.y,
        x2: target.x,
        y2: target.y,
        "marker-end": "url(#ro-arrowhead)",
      });
      // Insert the arrow beneath the box group so the arrowhead reads cleanly.
      svg.insertBefore(line, group);
    }
  }

  /**
   * Placement for context-label mode: a box centre for EVERY structure, kept
   * apart from the other centres and from every target dot. Size-independent
   * (uses a nominal separation, not the text width) so the front and back agree.
   * Deterministic given the seeded rng.
   */
  function placeCenters(rng, stage, targets, cfg) {
    var diag = Math.hypot(stage.w, stage.h);
    var minLen = cfg.minArrowFraction * diag;
    var maxLen = Math.max(minLen + 1, MAX_ARROW_FRACTION_MULTI * diag);
    var marginX = stage.w * MARGIN_X_FRACTION;
    var marginY = stage.h * MARGIN_Y_FRACTION;
    var maxX = stage.w - marginX;
    var maxY = stage.h - marginY;
    var sep = Math.min(stage.w, stage.h) * MIN_SEPARATION_FRACTION;

    var centers = [];
    for (var i = 0; i < targets.length; i++) {
      var target = targets[i];
      var best = null;
      var bestScore = -Infinity;
      // Candidates whose (clamped) arrow is too short to read are rejected
      // outright, so the arrow-visibility invariant is enforced by the loop
      // itself — exactly as in placeCenter — and never traded for separation.
      // Among arrow-valid candidates, "score" is the smallest distance to any
      // already-placed centre or any *other* target; maximising it spreads the
      // boxes out.
      for (var attempt = 0; attempt < cfg.maxPlacementAttempts; attempt++) {
        var angle = rng() * Math.PI * 2;
        var length = minLen + rng() * (maxLen - minLen);
        var cx = clamp(target.x + Math.cos(angle) * length, marginX, maxX);
        var cy = clamp(target.y + Math.sin(angle) * length, marginY, maxY);
        if (Math.hypot(cx - target.x, cy - target.y) < minLen * ACCEPT_ARROW_FRACTION) {
          continue; // clamping pulled the box onto its own target
        }
        var score = Infinity;
        for (var placedIdx = 0; placedIdx < centers.length; placedIdx++) {
          score = Math.min(
            score,
            Math.hypot(cx - centers[placedIdx].x, cy - centers[placedIdx].y),
          );
        }
        for (var otherIdx = 0; otherIdx < targets.length; otherIdx++) {
          if (otherIdx !== i) {
            score = Math.min(
              score,
              Math.hypot(cx - targets[otherIdx].x, cy - targets[otherIdx].y),
            );
          }
        }
        if (score >= sep) {
          best = { x: cx, y: cy };
          break;
        }
        if (score > bestScore) {
          bestScore = score;
          best = { x: cx, y: cy };
        }
      }
      // No sampled candidate had a visible arrow (tiny stage / huge min arrow):
      // a readable arrow beats separation, so take the farthest in-margin point.
      centers.push(best || farthestInMargin(target, marginX, marginY, maxX, maxY));
    }
    return centers;
  }

  // ---- single-card cycling mode --------------------------------------------

  /** Size the overlay to the image and clear it. Returns the stage or null. */
  function fitSvg(svg, img) {
    var rect = img.getBoundingClientRect();
    var w = rect.width;
    var h = rect.height;
    if (!w || !h) return null;
    setSvgSize(svg, w, h);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    ensureArrowMarker(svg);
    return { w: w, h: h };
  }

  /** Seeded Fisher-Yates shuffle of [0..n-1]. */
  function shuffleIndices(n, rng) {
    var arr = [];
    for (var i = 0; i < n; i++) arr.push(i);
    for (var j = n - 1; j > 0; j--) {
      var k = Math.floor(rng() * (j + 1));
      var tmp = arr[j];
      arr[j] = arr[k];
      arr[k] = tmp;
    }
    return arr;
  }

  function normalizeAnswer(text) {
    return (text || "").trim().toLowerCase().replace(/\s+/g, " ");
  }

  /**
   * Cycle order + box centres for single mode, deterministic from the seed so
   * the front interaction and the back answer key produce identical geometry.
   */
  function computeSingleLayout(seed, stage, structures, cfg) {
    var rng = makeRng(seed);
    var order = shuffleIndices(structures.length, rng);
    var targets = [];
    for (var i = 0; i < structures.length; i++) {
      targets.push({
        x: structures[i].x * stage.w,
        y: structures[i].y * stage.h,
        label: structures[i].label,
      });
    }
    var centers = placeCenters(rng, stage, targets, cfg);
    return { order: order, targets: targets, centers: centers };
  }

  /** Create (once) the DOM control bar under #ro-root. */
  function ensureCyclerBar() {
    var existing = document.getElementById("ro-cycler");
    if (existing) return existing;
    var root = document.getElementById("ro-root");
    if (!root) return null;
    var bar = document.createElement("div");
    bar.id = "ro-cycler";
    bar.className = "ro-cycler";
    bar.innerHTML =
      '<div class="ro-cycler-row">' +
      '<span class="ro-progress" id="ro-progress"></span>' +
      '<input id="ro-input" class="tappable" type="text" autocomplete="off" ' +
      'autocapitalize="off" autocorrect="off" spellcheck="false" ' +
      'placeholder="Type the label…">' +
      '<button id="ro-btn" class="tappable" type="button" tabindex="-1">Check</button>' +
      "</div>" +
      '<div class="ro-feedback" id="ro-feedback" role="status" aria-live="polite"></div>';
    root.appendChild(bar);
    return bar;
  }

  /**
   * Per-cycle-position forward/backward assignment for single mode (true =
   * forward). Only "both" mixes; a fixed direction applies uniformly. Drawn from
   * a SEPARATE seed stream so it never disturbs the cycle order or placement.
   * Pure — exposed on _internals for testing.
   */
  function cyclerDirections(seed, n, direction) {
    var dirs = [];
    var rng = makeRng((seed ^ 0x85ebca6b) >>> 0);
    for (var i = 0; i < n; i++) {
      dirs.push(direction === "both" ? rng() < 0.5 : direction !== "reverse");
    }
    return dirs;
  }

  /** State machine driving the single-card cycle interaction. */
  function makeCycler(structures, seed, direction, cfg, bar) {
    var n = structures.length;
    // The cycle order and per-marker directions depend only on the seed, so they
    // stay stable across every repaint / resize; centres are recomputed per paint.
    var order = shuffleIndices(n, makeRng(seed));
    var forwards = cyclerDirections(seed, n, direction);
    var state = { idx: 0, revealed: false, results: [] };
    var input = bar.querySelector("#ro-input");
    var button = bar.querySelector("#ro-btn");
    var progress = bar.querySelector("#ro-progress");
    var feedback = bar.querySelector("#ro-feedback");

    function currentStructure() {
      return structures[order[state.idx]];
    }
    function currentForward() {
      return forwards[state.idx];
    }
    // Green/red only for graded (forward) answers; a backward "located" marker
    // stays neutral because locating a structure is self-assessed.
    function boxClass(result) {
      if (result === "correct") return "ro-correct";
      if (result === "wrong") return "ro-wrong";
      return undefined;
    }

    function updateBar() {
      var done = state.idx >= n;
      bar.classList.toggle("ro-done", done);
      if (progress) {
        progress.textContent = done ? n + " / " + n + " ✓" : state.idx + 1 + " / " + n;
      }
      // Keep the input visible (and focused) through a forward marker's reveal so
      // it keeps shielding Space/Enter from Anki's card-flip shortcut; only
      // backward markers (nothing to type) and the done state hide it.
      var typing = !done && currentForward();
      if (input) input.style.display = typing ? "" : "none";
      if (button) {
        button.textContent = done
          ? "Done — press Show Answer"
          : state.revealed
            ? "Next"
            : currentForward()
              ? "Check"
              : "Reveal";
      }
    }

    function paint() {
      var svg = document.getElementById("ro-overlay");
      var img = getImage();
      if (!svg || !img) return;
      var stage = fitSvg(svg, img);
      if (!stage) return;
      var layout = computeSingleLayout(seed, stage, structures, cfg);

      for (var d = 0; d < layout.targets.length; d++) drawDot(svg, layout.targets[d]);

      // Already-answered structures stay revealed (accumulating answer key).
      for (var p = 0; p < state.idx && p < n; p++) {
        var ai = layout.order[p];
        drawBox(svg, layout.centers[ai], layout.targets[ai], layout.targets[ai].label, cfg, true, boxClass(state.results[p]));
      }
      // Current structure. Forward: "?" + arrow until revealed, then the label.
      // Backward: show the label with NO arrow (you locate it), revealing the
      // arrow to the structure on answer.
      if (state.idx < n) {
        var ci = layout.order[state.idx];
        if (state.revealed) {
          drawBox(svg, layout.centers[ci], layout.targets[ci], layout.targets[ci].label, cfg, true, boxClass(state.results[state.idx]));
        } else if (currentForward()) {
          drawBox(svg, layout.centers[ci], layout.targets[ci], cfg.promptText, cfg, true);
        } else {
          drawBox(svg, layout.centers[ci], layout.targets[ci], currentStructure().label, cfg, false);
        }
      }
      updateBar();
    }

    // Focus the current marker's interaction element so Space/Enter are shielded
    // from Anki: the text input for a forward prompt, the Reveal/Next button for a
    // backward one (which has nothing to type).
    function focusCurrent() {
      if (state.idx >= n) return;
      try {
        if (currentForward()) {
          if (!state.revealed && input) input.focus();
        } else if (button) {
          button.focus();
        }
      } catch (e) {
        /* focus is best-effort */
      }
    }

    function reveal() {
      if (state.idx >= n || state.revealed) return;
      if (currentForward()) {
        var correct =
          normalizeAnswer(input ? input.value : "") ===
          normalizeAnswer(currentStructure().label);
        state.results[state.idx] = correct ? "correct" : "wrong";
        if (feedback) {
          feedback.textContent = correct
            ? "✓ Correct"
            : "✗ Answer: " + currentStructure().label;
          feedback.className = "ro-feedback " + (correct ? "correct" : "wrong");
        }
      } else {
        // Backward: a location can't be typed, so it is self-assessed — the arrow
        // now points to the named structure to confirm where it is.
        state.results[state.idx] = "located";
        if (feedback) {
          feedback.textContent = "Location: " + currentStructure().label;
          feedback.className = "ro-feedback";
        }
      }
      state.revealed = true;
      paint();
    }

    function next() {
      if (!state.revealed || state.idx >= n) return;
      state.idx++;
      state.revealed = false;
      if (input) input.value = "";
      if (feedback) {
        feedback.textContent = "";
        feedback.className = "ro-feedback";
      }
      paint();
      focusCurrent();
    }

    function onButton() {
      if (state.idx >= n) return;
      if (state.revealed) next();
      else reveal();
    }

    if (button) {
      button.addEventListener("click", onButton);
      button.addEventListener(
        "touchend",
        function (e) {
          e.preventDefault();
          onButton();
        },
        { passive: false }
      );
      button.addEventListener("keydown", function (e) {
        // A backward marker focuses this button; shield Space/Enter from Anki's
        // card-flip shortcut (the button's native activation still advances).
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.stopPropagation();
        }
      });
    }
    if (input) {
      input.addEventListener("keydown", function (e) {
        // Keep keystrokes from reaching Anki's shortcut handlers; typed spaces
        // are consumed by the focused input so they won't flip the card. Enter
        // submits the current (forward) answer rather than flipping.
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          reveal();
        }
      });
    }

    return { paint: paint, focus: focusCurrent, seed: seed };
  }

  /** Single-card mode: interactive cycler on the front, answer key on the back. */
  function renderSingle(structures, seed, direction, back, cfg) {
    var svg = document.getElementById("ro-overlay");
    var img = getImage();
    if (!svg || !img) return;

    if (back) {
      var stage = fitSvg(svg, img);
      if (!stage) return;
      var layout = computeSingleLayout(seed, stage, structures, cfg);
      for (var d = 0; d < layout.targets.length; d++) drawDot(svg, layout.targets[d]);
      for (var b = 0; b < layout.targets.length; b++) {
        drawBox(svg, layout.centers[b], layout.targets[b], layout.targets[b].label, cfg, true);
      }
      var doneBar = document.getElementById("ro-cycler");
      if (doneBar) doneBar.style.display = "none";
      return;
    }

    var bar = ensureCyclerBar();
    if (!bar) return;
    bar.style.display = "";
    var created = false;
    if (!bar.__roController) {
      bar.__roController = makeCycler(structures, seed, direction, cfg, bar);
      created = true;
    }
    // The controller's captured seed is the source of truth for the whole front
    // interaction; write it back so the back's answer key reproduces the same
    // layout even if a resize on the mint=false path re-minted a different seed.
    writeSeed(bar.__roController.seed);
    bar.__roController.paint();
    // Auto-focus only on genuine (re)creation — never on a resize repaint, which
    // would steal focus and re-pop the mobile keyboard mid-review. next() handles
    // focusing when the learner deliberately advances.
    if (created) bar.__roController.focus();
  }

  // ---- orchestration --------------------------------------------------------

  /**
   * Map the active cloze ordinal to a structure index and a card direction. The
   * ordinal is always the structure's 1-based index (every mode emits one card
   * per structure). Direction is fixed for forward/reverse; for "both" the
   * caller's per-review coin (preferForward) decides. An out-of-range ordinal
   * falls back to the first structure. Pure (no DOM/rng), unit-tested via
   * _internals.
   */
  function resolveActiveCard(activeOrdinal, direction, count, preferForward) {
    var activeIndex = activeOrdinal - 1;
    if (activeIndex < 0 || activeIndex >= count) activeIndex = 0;
    var cardDir;
    if (direction === "both") {
      cardDir = preferForward ? "forward" : "reverse";
    } else {
      cardDir = direction === "reverse" ? "reverse" : "forward";
    }
    return { activeIndex: activeIndex, cardDir: cardDir };
  }

  function render(mint) {
    var stageEl = document.getElementById("ro-stage");
    var img = getImage();
    var svg = document.getElementById("ro-overlay");
    if (!stageEl || !img || !svg) return;

    // getBoundingClientRect gives the true fractional displayed size, so the
    // overlay's user space tracks the image exactly (no ~1px rounding drift).
    var rect = img.getBoundingClientRect();
    var width = rect.width;
    var height = rect.height;
    if (!width || !height) return; // image not laid out yet; a later pass will retry

    var data = readData();
    var structures = data.structures;
    if (!structures.length) return;

    var cfg = readConfig();
    var back = isBackSide();
    var activeOrdinal = readActiveOrdinal();

    // Seed lifecycle (this is what keeps front and back identical while still
    // randomising every review):
    //   - a fresh question view (mint=true, front) mints and stores a new seed;
    //   - the answer side (back) and any re-layout (resize, mint=false) reuse
    //     the stored seed, so they reproduce the exact same layout.
    // Minting only on a genuine new question view — not on every render — is
    // what stops the box jumping on resize or on a double initial render.
    var seed;
    if (back) {
      var stored = readSeed();
      seed = stored !== null ? parseInt(stored, 10) >>> 0 : hashString("" + activeOrdinal + structures.length);
    } else if (mint) {
      seed = randomUint32();
      writeSeed(seed);
    } else {
      var reused = readSeed();
      seed = reused !== null ? parseInt(reused, 10) >>> 0 : randomUint32();
      if (reused === null) writeSeed(seed);
    }

    // Single-card mode drives its own interactive cycler / answer key.
    if (data.mode === "single") {
      renderSingle(structures, seed, data.direction, back, cfg);
      return;
    }

    // Match the SVG's user-space to the image's displayed pixel size.
    setSvgSize(svg, width, height);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    ensureArrowMarker(svg);

    var rng = makeRng(seed);
    var stage = { w: width, h: height };

    // Map the active cloze ordinal to a structure index and card direction;
    // "both" draws a fresh forward/reverse coin from this review's seed.
    var preferForward = data.direction !== "both" || directionCoin(seed);
    var activeCard = resolveActiveCard(
      activeOrdinal,
      data.direction,
      structures.length,
      preferForward
    );
    var activeIndex = activeCard.activeIndex;
    var cardDir = activeCard.cardDir;

    // Project every structure to pixel space.
    var targets = [];
    for (var t = 0; t < structures.length; t++) {
      targets.push({
        x: structures[t].x * width,
        y: structures[t].y * height,
        label: structures[t].label,
      });
    }
    var active = targets[activeIndex];

    // Reverse cards ("given the name, locate it") show the label with NO arrow
    // on the question side; the arrow (revealing the location) appears on the
    // answer side. Forward cards show "?" + arrow, revealing the label on flip.
    var isReverse = cardDir === "reverse";
    var activeText = !back && !isReverse ? cfg.promptText : active.label;
    var activeArrow = back || !isReverse;

    // Per-note context-labels setting, falling back to the global config for
    // older notes that predate it.
    var contextLabels = data.contextLabels;
    if (contextLabels === undefined || contextLabels === null) {
      contextLabels = cfg.showContextLabels;
    }

    if (contextLabels) {
      var centers = placeCenters(rng, stage, targets, cfg);
      for (var d = 0; d < targets.length; d++) drawDot(svg, targets[d]);
      for (var b = 0; b < targets.length; b++) {
        if (b === activeIndex) {
          drawBox(svg, centers[b], targets[b], activeText, cfg, activeArrow);
        } else {
          drawBox(svg, centers[b], targets[b], targets[b].label, cfg, true);
        }
      }
    } else {
      // Decoy dots (all markers) force the learner to follow the arrow to the
      // right one instead of recognising a lone dot.
      if (cfg.showDecoyDots) {
        for (var e = 0; e < targets.length; e++) drawDot(svg, targets[e]);
      } else if (cfg.showTargetDot) {
        drawDot(svg, active);
      }
      var center = placeCenter(rng, stage, active, cfg);
      drawBox(svg, center, active, activeText, cfg, activeArrow);
    }

    // Type-to-answer doesn't apply to reverse ("locate") cards — hide the box.
    var typeEl = document.querySelector(".ro-type");
    if (typeEl) typeEl.style.display = isReverse ? "none" : "";
  }

  /** Defer until the image is laid out, then render (and re-render on resize). */
  function run(attempt) {
    attempt = attempt || 0;
    var img = getImage();
    if (!img) {
      // DOM/image may not be ready yet (parse-mode clients); retry a bounded
      // number of times, then give up — a note with an empty Image field must
      // not spin setTimeout forever and peg the CPU.
      if (attempt < 30) {
        window.setTimeout(function () {
          run(attempt + 1);
        }, 16);
      }
      return;
    }

    // Several triggers below (load / error / safety-net timer) may all fire;
    // this guard ensures the initial render for this show happens exactly once.
    // Without it, a second pass would re-mint the seed and the box would jump.
    var ran = false;
    function go() {
      if (ran) return;
      ran = true;
      // setTimeout(0) guarantees we run after the full card HTML is in the DOM
      // (so the back-side sentinel #ro-answer is reliably detectable).
      window.setTimeout(function () {
        render(true);
      }, 0);
    }

    if (img.complete && img.naturalWidth) {
      go();
    } else {
      img.addEventListener("load", go, { once: true });
      img.addEventListener("error", go, { once: true });
      // Safety net in case neither event fires (cached/odd clients). The `ran`
      // guard makes this a no-op once load/error has already rendered.
      window.setTimeout(go, 250);
    }

    if (!window.__roResizeBound) {
      window.__roResizeBound = true;
      // A resize is a re-layout of the SAME review, not a new one: re-render
      // with the stored seed (mint=false) so the layout stays identical.
      window.addEventListener("resize", function () {
        window.setTimeout(function () {
          render(false);
        }, 0);
      });
    }
  }

  window.RandomizedOcclusion = { run: run, render: render };
  // Pure, DOM-free helpers exposed for headless unit tests. Assigning extra
  // properties is harmless in production and contains no template tokens.
  window.RandomizedOcclusion._internals = {
    makeRng: makeRng,
    hashString: hashString,
    clamp: clamp,
    placeCenter: placeCenter,
    placeCenters: placeCenters,
    boxBorderToward: boxBorderToward,
    shuffleIndices: shuffleIndices,
    normalizeAnswer: normalizeAnswer,
    resolveActiveCard: resolveActiveCard,
    directionCoin: directionCoin,
    cyclerDirections: cyclerDirections,
    computeSingleLayout: computeSingleLayout,
    decodeBase64Utf8: decodeBase64Utf8,
  };
  run();
})();
