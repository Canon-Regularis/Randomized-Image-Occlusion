"use strict";

// A DOM mock rich enough to run the editor canvas (marker.js) end to end.
//
// Elements come from dom.js's `makeEl`, so the editor and the reviewer are
// tested against one element implementation rather than two that can drift.
// What this module adds on top is everything marker.js needs and render.js
// never did: a tree-walking `document.querySelector` that understands attribute
// selectors, a live `document.activeElement`, window-level event dispatch (the
// drag and pan gestures listen on `window`), and a controllable timer queue.
//
// The geometry model matches the browser's:
// `#ed-img` carries `transform: translate(pan) scale(zoom)` with
// `transform-origin: 0 0`, so its LAYOUT box (offsetLeft/offsetWidth) ignores
// the transform while its RENDERED box (getBoundingClientRect) reflects it.
// The mock reproduces exactly that split by reading marker.js's own live zoom
// and pan back out of `_internals.state()`.

const { runMarkerJs } = require("./loader.js");
const { makeEl } = require("./dom.js");

const EMPTY_RECT = { width: 0, height: 0, left: 0, top: 0, right: 0, bottom: 0 };

// `.ed-stage` has `border: 1px solid` (marker.css). That one pixel is why the
// stage's three coordinate spaces are NOT interchangeable, and modelling them as
// if they were let four wrong implementations pass:
//   * getBoundingClientRect() is the BORDER box;
//   * clientWidth/clientHeight are the CONTENT box, 2px smaller;
//   * `position:absolute; left:0` (the overlay) and `offsetLeft` both resolve
//     against the PADDING box, 1px in from the border box;
//   * `overflow:hidden` clips to the padding box too.
const STAGE_BORDER = 1;

function rect(left, top, width, height) {
  return { left, top, width, height, right: left + width, bottom: top + height };
}

/**
 * Read back the transform marker.js actually wrote.
 *
 * Deriving the image's rect from marker.js's own zoom/pan state would make this
 * a circular oracle: a malformed transform string, wrong units or the wrong
 * order would still "work". Parsing the real declaration means the rect only
 * matches if the CSS is right, and it models the applied-vs-pending
 * distinction, since the DOM shows the last transform written, not the value a
 * calculation is midway through.
 */
// A CSS <number>: optional sign, digits, optional fraction, optional exponent.
// `String(panX)` switches to exponent form below 1e-6, and layoutSize()'s
// rect/appliedZoom round trip lands there routinely (zoom to 128%, press Fit).
const NUM = String.raw`[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?`;
const TRANSLATE = new RegExp(String.raw`translate\(\s*(${NUM})px\s*,\s*(${NUM})px\s*\)`);
const SCALE = new RegExp(String.raw`scale\(\s*(${NUM})\s*\)`);

function parseTransform(value) {
  if (!value) return { x: 0, y: 0, scale: 1 };
  const translate = TRANSLATE.exec(value);
  const scale = SCALE.exec(value);
  // Throw rather than fall back to identity. A silent {0,0,1} is how a 180px
  // error becomes invisible: the mock would report the image exactly where the
  // maths says it should be, whatever nonsense was actually written to the DOM.
  if (!translate || !scale) {
    throw new Error(`marker.js wrote a transform the browser could not parse: ${value}`);
  }
  const parsed = {
    x: Number(translate[1]),
    y: Number(translate[2]),
    scale: Number(scale[1]),
  };
  if (!Number.isFinite(parsed.x) || !Number.isFinite(parsed.y) || !Number.isFinite(parsed.scale)) {
    throw new Error(`marker.js wrote a non-finite transform: ${value}`);
  }
  return parsed;
}

/** Match a node against the selector shapes marker.js actually uses. */
function matches(node, selector) {
  const parts = selector.match(/#[\w-]+|\.[\w-]+|\[[^\]]+\]|^[a-zA-Z]+/g) || [];
  return parts.every((part) => {
    if (part[0] === "#") return node.attributes.id === part.slice(1);
    if (part[0] === ".") return node._classes.has(part.slice(1));
    if (part[0] === "[") {
      const m = part.slice(1, -1).match(/^([\w-]+)\s*=\s*"?([^"]*)"?$/);
      if (!m) return node.attributes[part.slice(1, -1)] !== undefined;
      return String(node.attributes[m[1]]) === m[2];
    }
    return node.tagName.toLowerCase() === part.toLowerCase();
  });
}

function walk(node, visit) {
  for (const child of node.childNodes) {
    visit(child);
    walk(child, visit);
  }
}

/**
 * Build the editor DOM and load marker.js against it.
 *
 * opts: { stage: {width,height}, image: {width,height} }
 * Returns handles plus the helpers a test drives the canvas with.
 */
function buildEditor(opts) {
  const o = Object.assign(
    { stage: { width: 800, height: 600 }, image: { width: 400, height: 300 } },
    opts,
  );
  const SW = o.stage.width;
  const SH = o.stage.height;
  let IW = o.image.width;
  let IH = o.image.height;
  // The stage does not lay out the image until it has loaded, so until then it
  // has no size, which is exactly the window the edit/prefill flow lands in.
  let loaded = false;
  let api = null;

  const ids = new Map();
  const timers = [];
  const sent = [];
  const listeners = {};
  const docListeners = {};

  const documentObj = {
    activeElement: null,
    readyState: "complete",
    getElementById: (id) => ids.get(id) || null,
    createElement: (tag) => el(tag),
    createElementNS: (ns, tag) => el(tag, ns),
    querySelector(selector) {
      let found = null;
      walk(root, (node) => {
        if (!found && matches(node, selector)) found = node;
      });
      return found;
    },
    // Real listeners, not a stub: marker.js watches the document for focusin,
    // focusout and visibilitychange, and a no-op here would silently drop them.
    addEventListener(type, fn) {
      (docListeners[type] = docListeners[type] || []).push(fn);
    },
    removeEventListener(type, fn) {
      const l = docListeners[type];
      if (!l) return;
      const i = l.indexOf(fn);
      if (i >= 0) l.splice(i, 1);
    },
  };

  function el(tag, ns) {
    const node = makeEl(tag, ns || null, ids);
    // makeEl only records focus locally; the editor asks the document who has
    // it (to keep '+'/'-'/arrow keys out of label fields), so route it through.
    node.focus = () => {
      documentObj.activeElement = node;
      node._focused = true;
      fireDocument("focusin", { target: node });
    };
    return node;
  }

  // ---- the tree, mirroring marker.html --------------------------------------
  const root = el("div");
  root.id = "ed-root";

  const stage = el("div");
  stage.id = "ed-stage";
  // `opts.stage` is the CONTENT box; the space an image is actually laid out
  // in, which is what `max-width:100%` resolves against. The border box is that
  // plus the border, and getBoundingClientRect() reports the border box.
  stage.clientWidth = SW;
  stage.clientHeight = SH;
  stage._rect = rect(0, 0, SW + STAGE_BORDER * 2, SH + STAGE_BORDER * 2);

  const empty = el("div");
  empty.id = "ed-empty";

  const img = el("img");
  img.id = "ed-img";
  img.style.display = "none";
  Object.defineProperties(img, {
    // `long` in the DOM spec: rounded, and zero for a box that is not rendered.
    offsetWidth: { get: () => (loaded ? Math.round(IW) : 0) },
    offsetHeight: { get: () => (loaded ? Math.round(IH) : 0) },
    // Flex-centred in the stage's content box, and never negative for an image
    // capped at max-width:100%, but clamp anyway so an oversized fixture is sane.
    offsetLeft: {
      get: () => (loaded ? Math.round(Math.max(0, (stage.clientWidth - IW) / 2)) : 0),
    },
    offsetTop: {
      get: () => (loaded ? Math.round(Math.max(0, (stage.clientHeight - IH) / 2)) : 0),
    },
  });
  img.getBoundingClientRect = () => {
    if (!loaded || img.style.display === "none") return Object.assign({}, EMPTY_RECT);
    // transform-origin is 0 0, so the box is translated wholesale and scaled
    // about its own top-left, exactly what the browser does.
    const t = parseTransform(img.style.transform);
    // offsetLeft is measured from the offsetParent's padding edge, so the
    // image's client position includes the border.
    return rect(
      stage._rect.left + STAGE_BORDER + img.offsetLeft + t.x,
      stage._rect.top + STAGE_BORDER + img.offsetTop + t.y,
      IW * t.scale,
      IH * t.scale,
    );
  };

  const overlay = el("svg");
  overlay.id = "ed-overlay";
  // Absolutely positioned at left:0/top:0 with width/height 100%, so it covers
  // the stage's PADDING box; inset by the border, not coincident with the rect.
  overlay._rect = rect(STAGE_BORDER, STAGE_BORDER, SW, SH);
  const crosshair = el("g");
  crosshair.id = "ed-crosshair";
  const markerGroup = el("g");
  markerGroup.id = "ed-markers";
  overlay.appendChild(crosshair);
  overlay.appendChild(markerGroup);

  stage.appendChild(empty);
  stage.appendChild(img);
  stage.appendChild(overlay);

  const panel = el("div");
  panel.id = "ed-panel";
  const zoomOut = el("button");
  zoomOut.id = "ed-zoom-out";
  const zoomLevel = el("span");
  zoomLevel.id = "ed-zoom-level";
  const zoomIn = el("button");
  zoomIn.id = "ed-zoom-in";
  const zoomFit = el("button");
  zoomFit.id = "ed-zoom-fit";
  const list = el("div");
  list.id = "ed-list";
  [zoomOut, zoomLevel, zoomIn, zoomFit, list].forEach((n) => panel.appendChild(n));

  root.appendChild(stage);
  root.appendChild(panel);

  // ---- window ---------------------------------------------------------------
  const windowObj = {
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    removeEventListener(type, fn) {
      const l = listeners[type];
      if (!l) return;
      const i = l.indexOf(fn);
      if (i >= 0) l.splice(i, 1);
    },
    setTimeout(fn, ms) {
      timers.push({ fn, ms });
      return timers.length;
    },
    // Present, because it is present in QtWebEngine: without it schedule()
    // silently takes its setTimeout fallback and the branch that actually runs
    // in Anki is never executed. Queued alongside the timers so one
    // `runTimers()` still flushes everything.
    requestAnimationFrame(fn) {
      timers.push({ fn, ms: 16 });
      return timers.length;
    },
  };

  // marker.js only constructs one, on #ed-stage. Capturing it lets a test drive
  // the resize route that production actually uses; a panel relayout or the
  // image finishing layout never fires `window.resize`.
  const observers = [];
  function ResizeObserver(callback) {
    this.observe = (node) => observers.push({ callback, node });
    this.disconnect = () => {};
  }

  const sandbox = {
    window: windowObj,
    document: documentObj,
    console,
    ResizeObserver,
    pycmd: (message) => sent.push(message),
    setTimeout: windowObj.setTimeout,
  };
  api = runMarkerJs(sandbox);

  // ---- driving it -----------------------------------------------------------
  function fire(type, event) {
    const ev = Object.assign(
      { preventDefault() {}, stopPropagation() {}, pointerId: 1, button: 0 },
      event,
    );
    (listeners[type] || []).slice().forEach((fn) => fn(ev));
    return ev;
  }

  /** Dispatch straight at the document (focusin, focusout, visibilitychange). */
  function fireDocument(type, event) {
    const ev = Object.assign({ preventDefault() {}, stopPropagation() {} }, event);
    (docListeners[type] || []).slice().forEach((fn) => fn(ev));
    return ev;
  }

  /**
   * Dispatch at `node` and let it BUBBLE, like a real event: up the tree, then
   * on to the document and the window.
   *
   * marker.js depends on each stage: #ed-stage's pointerdown listener sees a
   * plain click-to-add press on the image, the marker groups stopPropagation()
   * to keep their presses off the stage, and the ctrl+wheel guard is bound at
   * window. Dispatching only at the target would exercise a different program.
   */
  function on(node, type, event) {
    let stopped = false;
    const ev = Object.assign(
      {
        preventDefault() {},
        stopPropagation() {
          stopped = true;
        },
        pointerId: 1,
        button: 0,
        target: node,
      },
      event,
    );
    for (let el = node; el && !stopped; el = el.parentNode) {
      ev.currentTarget = el;
      el.dispatch(type, ev);
    }
    // Past the root the event still reaches document and then window, which is
    // where marker.js binds its ctrl+wheel guard and its focus listeners.
    if (!stopped) {
      ev.currentTarget = documentObj;
      (docListeners[type] || []).slice().forEach((fn) => fn(ev));
    }
    if (!stopped) {
      ev.currentTarget = windowObj;
      (listeners[type] || []).slice().forEach((fn) => fn(ev));
    }
    return ev;
  }

  /**
   * Release a pointer the way the platform does: only the PRIMARY button is
   * followed by a `click`. Middle and right release as `auxclick`, which
   * marker.js does not listen for, so a test cannot accidentally invent the
   * click that made a real bug invisible here before.
   */
  function release(node, event) {
    const ev = Object.assign({ button: 0, pointerId: 1 }, event);
    fire("pointerup", ev);
    on(node, ev.button === 0 ? "click" : "auxclick", ev);
    // Chromium follows a right-button release with contextmenu; marker.js
    // suppresses it so a right-drag pan does not pop Anki's menu.
    if (ev.button === 2) on(node, "contextmenu", ev);
    return ev;
  }

  return {
    api,
    ids,
    sent,
    els: { root, stage, img, overlay, crosshair, markerGroup, list, panel,
           zoomIn, zoomOut, zoomFit, zoomLevel, empty },
    document: documentObj,
    window: windowObj,

    /** Resize the stage's CONTENT box, keeping every derived rect consistent. */
    resizeStage(width, height) {
      stage.clientWidth = width;
      stage.clientHeight = height;
      stage._rect = rect(0, 0, width + STAGE_BORDER * 2, height + STAGE_BORDER * 2);
      overlay._rect = rect(STAGE_BORDER, STAGE_BORDER, width, height);
    },
    /** The visible region: the padding box, which is what overflow:hidden clips to. */
    visibleRect: () => Object.assign({}, overlay._rect),
    /** Drive the ResizeObserver route, as a panel relayout would in production. */
    triggerResizeObserver() {
      observers.forEach((o) => o.callback([{ target: o.node }]));
    },
    observedNodes: () => observers.map((o) => o.node),
    /** How many window listeners are registered for `type`. */
    listenerCount: (type) => (listeners[type] || []).length,

    state: () => api._internals.state(),
    /** Complete the image load, which is when the stage can finally size it. */
    load(size) {
      if (size) {
        IW = size.width;
        IH = size.height;
      }
      loaded = true;
      if (typeof img.onload === "function") img.onload();
    },
    /**
     * Flush every pending setTimeout (the zoom-report throttle, rAF fallback)
     * and return how many ran. The count is the only way to observe work being
     * coalesced rather than merely being correct.
     */
    runTimers() {
      let ran = 0;
      while (timers.length) {
        timers.shift().fn();
        ran += 1;
      }
      return ran;
    },

    fire,
    fireDocument,
    on,
    release,
    /** Move focus and let the document hear about it, as a browser would. */
    focus(node) {
      node.focus();
      fireDocument("focusin", { target: node });
    },
    blurAll() {
      documentObj.activeElement = null;
      fireDocument("focusout", {});
    },
    clickImage: (x, y) => on(img, "click", { clientX: x, clientY: y }),
    wheel: (x, y, deltaY, extra) =>
      on(stage, "wheel", Object.assign({ clientX: x, clientY: y, deltaY, deltaMode: 0 }, extra)),
    key: (key, extra) => fire("keydown", Object.assign({ key }, extra)),
    keyUp: (key) => fire("keyup", { key }),

    /** The marker <g> nodes currently on the overlay. */
    groups: () => markerGroup.childNodes.filter((n) => n.tagName === "g"),
    /** Every marker dot's overlay-space centre. */
    dots: () =>
      markerGroup.childNodes
        .filter((n) => n.tagName === "g")
        .map((g) => {
          const dot = g.childNodes.find((c) => c._classes.has("ed-marker-dot"));
          return { x: Number(dot.attributes.cx), y: Number(dot.attributes.cy) };
        }),
    crosshairLines: () => crosshair.childNodes.length,
    /** Point on the image, in client coordinates, for a normalized position. */
    pointAt(nx, ny) {
      const r = img.getBoundingClientRect();
      return { x: r.left + nx * r.width, y: r.top + ny * r.height };
    },
  };
}

module.exports = { buildEditor };
