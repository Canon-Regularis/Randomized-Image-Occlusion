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
   * The note payload. v2 is `{direction, structures}`; v1 (older notes) was a
   * bare structures array, treated as forward. Self-describing so a note renders
   * correctly regardless of the current global config.
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
  function placeCenter(rng, stage, target, cfg) {
    var diag = Math.hypot(stage.w, stage.h);
    var minLen = cfg.minArrowFraction * diag;
    var maxLen = Math.max(minLen + 1, 0.6 * diag);
    var marginX = stage.w * 0.14;
    var marginY = stage.h * 0.1;

    var best = null;
    var bestLen = -1;
    for (var i = 0; i < cfg.maxPlacementAttempts; i++) {
      var angle = rng() * Math.PI * 2;
      var length = minLen + rng() * (maxLen - minLen);
      var cx = clamp(target.x + Math.cos(angle) * length, marginX, stage.w - marginX);
      var cy = clamp(target.y + Math.sin(angle) * length, marginY, stage.h - marginY);
      var actualLen = Math.hypot(cx - target.x, cy - target.y);
      if (actualLen >= minLen * 0.8) {
        return { x: cx, y: cy };
      }
      if (actualLen > bestLen) {
        bestLen = actualLen;
        best = { x: cx, y: cy };
      }
    }
    return (
      best || {
        x: clamp(target.x + minLen, marginX, stage.w - marginX),
        y: clamp(target.y, marginY, stage.h - marginY),
      }
    );
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
    var rect = svgEl("rect", { class: rectClass, rx: "6", ry: "6" });
    var label = svgEl("text", {
      class: "ro-box-text",
      "text-anchor": "middle",
      "dominant-baseline": "central",
    });
    label.textContent = text;
    group.appendChild(rect);
    group.appendChild(label);
    svg.appendChild(group);

    var padX = 12;
    var padY = 8;
    var textLen;
    try {
      textLen = label.getComputedTextLength();
    } catch (e) {
      textLen = String(text).length * 9;
    }
    var fontSize = parseFloat(window.getComputedStyle(label).fontSize) || 18;
    var box = {
      w: Math.max(36, textLen + padX * 2),
      h: Math.max(30, fontSize + padY * 2),
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
    var maxLen = Math.max(minLen + 1, 0.5 * diag);
    var marginX = stage.w * 0.14;
    var marginY = stage.h * 0.1;
    var sep = Math.min(stage.w, stage.h) * 0.2;

    var centers = [];
    for (var i = 0; i < targets.length; i++) {
      var target = targets[i];
      var best = null;
      var bestScore = -Infinity;
      for (var a = 0; a < cfg.maxPlacementAttempts; a++) {
        var angle = rng() * Math.PI * 2;
        var length = minLen + rng() * (maxLen - minLen);
        var cx = clamp(target.x + Math.cos(angle) * length, marginX, stage.w - marginX);
        var cy = clamp(target.y + Math.sin(angle) * length, marginY, stage.h - marginY);
        var score = Infinity;
        for (var j = 0; j < centers.length; j++) {
          score = Math.min(score, Math.hypot(cx - centers[j].x, cy - centers[j].y));
        }
        for (var k = 0; k < targets.length; k++) {
          if (k !== i) {
            score = Math.min(score, Math.hypot(cx - targets[k].x, cy - targets[k].y));
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
      centers.push(
        best || {
          x: clamp(target.x + minLen, marginX, stage.w - marginX),
          y: clamp(target.y, marginY, stage.h - marginY),
        }
      );
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
    svg.setAttribute("width", w);
    svg.setAttribute("height", h);
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
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
      '<div class="ro-feedback" id="ro-feedback"></div>';
    root.appendChild(bar);
    return bar;
  }

  /** State machine driving the single-card type-and-cycle interaction. */
  function makeCycler(structures, seed, cfg, bar) {
    var n = structures.length;
    // The cycle order is stage-independent (depends only on the seed), so it is
    // stable across every repaint / resize; centres are recomputed per paint.
    var order = shuffleIndices(n, makeRng(seed));
    var state = { idx: 0, revealed: false, results: [] };
    var input = bar.querySelector("#ro-input");
    var button = bar.querySelector("#ro-btn");
    var progress = bar.querySelector("#ro-progress");
    var feedback = bar.querySelector("#ro-feedback");

    function currentStructure() {
      return structures[order[state.idx]];
    }

    function updateBar() {
      var done = state.idx >= n;
      if (progress) {
        progress.textContent = done
          ? n + " / " + n + " ✓"
          : state.idx + 1 + " / " + n;
      }
      if (input) input.style.display = done ? "none" : "";
      if (button) {
        button.textContent = done
          ? "Done — press Show Answer"
          : state.revealed
            ? "Next"
            : "Check";
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
        var av = state.results[p] === "correct" ? "ro-correct" : "ro-wrong";
        drawBox(svg, layout.centers[ai], layout.targets[ai], layout.targets[ai].label, cfg, true, av);
      }
      // Current structure: "?" until revealed, then its label.
      if (state.idx < n) {
        var ci = layout.order[state.idx];
        if (state.revealed) {
          var cv = state.results[state.idx] === "correct" ? "ro-correct" : "ro-wrong";
          drawBox(svg, layout.centers[ci], layout.targets[ci], layout.targets[ci].label, cfg, true, cv);
        } else {
          drawBox(svg, layout.centers[ci], layout.targets[ci], cfg.promptText, cfg, true);
        }
      }
      updateBar();
    }

    function focusInput() {
      if (input && state.idx < n && !state.revealed) {
        try {
          input.focus();
        } catch (e) {
          /* focus is best-effort */
        }
      }
    }

    function check() {
      if (state.idx >= n || state.revealed) return;
      var correct =
        normalizeAnswer(input ? input.value : "") ===
        normalizeAnswer(currentStructure().label);
      state.results[state.idx] = correct ? "correct" : "wrong";
      state.revealed = true;
      if (feedback) {
        feedback.textContent = correct
          ? "✓ Correct"
          : "✗ Answer: " + currentStructure().label;
        feedback.className = "ro-feedback " + (correct ? "correct" : "wrong");
      }
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
      focusInput();
    }

    function onButton() {
      if (state.idx >= n) return;
      if (state.revealed) next();
      else check();
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
    }
    if (input) {
      input.addEventListener("keydown", function (e) {
        // Keep keystrokes from reaching Anki's shortcut handlers; typed spaces
        // are consumed by the focused input so they won't flip the card. Enter
        // checks the answer rather than flipping (best effort).
        e.stopPropagation();
        if (e.key === "Enter") {
          e.preventDefault();
          check();
        }
      });
    }

    return { paint: paint, focusInput: focusInput, seed: seed };
  }

  /** Single-card mode: interactive cycler on the front, answer key on the back. */
  function renderSingle(structures, seed, back, cfg) {
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
      bar.__roController = makeCycler(structures, seed, cfg, bar);
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
    if (created) bar.__roController.focusInput();
  }

  // ---- orchestration --------------------------------------------------------

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
      seed = (Math.floor(Math.random() * 0xffffffff)) >>> 0;
      writeSeed(seed);
    } else {
      var reused = readSeed();
      seed = reused !== null ? parseInt(reused, 10) >>> 0 : (Math.floor(Math.random() * 0xffffffff)) >>> 0;
      if (reused === null) writeSeed(seed);
    }

    // Single-card mode drives its own interactive cycler / answer key.
    if (data.mode === "single") {
      renderSingle(structures, seed, back, cfg);
      return;
    }

    // Match the SVG's user-space to the image's displayed pixel size.
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    ensureArrowMarker(svg);

    var rng = makeRng(seed);
    var stage = { w: width, h: height };

    // Map the active cloze ordinal to a structure and a card direction. In
    // "both" mode each structure owns two consecutive ordinals (forward, then
    // reverse); otherwise the ordinal is the structure's 1-based index.
    var activeIndex;
    var cardDir;
    if (data.direction === "both") {
      activeIndex = Math.floor((activeOrdinal - 1) / 2);
      cardDir = activeOrdinal % 2 === 1 ? "forward" : "reverse";
    } else {
      activeIndex = activeOrdinal - 1;
      cardDir = data.direction === "reverse" ? "reverse" : "forward";
    }
    if (activeIndex < 0 || activeIndex >= structures.length) activeIndex = 0;

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
  run();
})();
