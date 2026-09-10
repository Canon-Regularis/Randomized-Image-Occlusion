"use strict";

// A DOM mock rich enough to run the reviewer's real `render()` end to end.
//
// `harness.js` loads render.js with a *minimal* DOM: `getElementById` returns
// null, so `render()` bails immediately and only the pure helpers can be tested.
// This module instead builds a whole card (stage, image, SVG overlay, payload
// and config script tags, the active cloze span), so the renderer actually
// draws. Tests can then inspect what it put on the overlay (boxes, their text,
// arrows, dots) and how it left the type-answer box, which is behaviour the
// pure-helper tests cannot reach.
//
// Determinism: `render(true)` mints a fresh random seed. Pass `seed` to
// pre-populate session storage and call `render(false)` instead; the renderer
// then reuses that seed, so every layout/direction decision is reproducible.

const { runRenderJs } = require("./loader.js");

const SEED_KEY = "randomizedOcclusion.seed";

/** Base64 of compact JSON: the wire format the card embeds. */
function b64(value) {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64");
}

/** A Text node: only the parts the mock's tree walkers actually touch. */
function makeTextNode(data) {
  return {
    nodeType: 3,
    data: String(data),
    // Present and inert, so every `childNodes.find(c => c.tagName === ...)` and
    // `c._classes.has(...)` in this file walks straight past it.
    tagName: undefined,
    ns: null,
    childNodes: [],
    attributes: {},
    _classes: new Set(),
    _handlers: {},
    parentNode: null,
    get textContent() {
      return this.data;
    },
  };
}

/** One mock element. `registry` maps ids to elements for `getElementById`. */
function makeEl(tag, ns, registry) {
  const el = {
    // Real DOM rule: tagName is uppercased for HTML elements, left alone for
    // anything in a namespace (SVG). marker.js compares against "INPUT", so a
    // lowercase mock would silently disable the guard it is testing.
    tagName: ns ? tag : String(tag).toUpperCase(),
    nodeType: 1,
    ns: ns || null,
    attributes: {},
    childNodes: [],
    style: {},
    dataset: {},
    // Set by appendChild/removeChild so event dispatch can walk the tree the way
    // a real bubbling event does.
    parentNode: null,
    _classes: new Set(),
    _handlers: {},
    value: "",

    get id() {
      return this.attributes.id || "";
    },
    set id(value) {
      this.attributes.id = value;
      registry.set(value, this);
    },
    get className() {
      return [...this._classes].join(" ");
    },
    set className(value) {
      this._classes = new Set(String(value).split(/\s+/).filter(Boolean));
    },
    get firstChild() {
      return this.childNodes[0] || null;
    },
    // Real `textContent` concatenates every descendant's text and replaces all
    // children on write. A write is modelled as an actual Text child rather than
    // a string held on the side, so appending elements afterwards leaves it in
    // place (that is how a stale measurement string ends up rendered beside the
    // tspans) and `while (firstChild) removeChild(firstChild)` clears it, exactly
    // as both do in a browser.
    get textContent() {
      return this.childNodes.map((c) => c.textContent).join("");
    },
    set textContent(value) {
      this.childNodes.forEach((child) => {
        child.parentNode = null;
      });
      const text = String(value);
      // Assigning "" removes every child and adds no Text node at all.
      this.childNodes = [];
      if (text !== "") {
        const node = makeTextNode(text);
        node.parentNode = this;
        this.childNodes.push(node);
      }
    },
    // The text written directly on this node, ignoring any child elements'.
    // `boxesOf` reports it as `strayText`.
    get _text() {
      return this.childNodes
        .filter((c) => c.nodeType === 3)
        .map((c) => c.data)
        .join("");
    },
    // The cycler bar sets a fixed innerHTML; recreate the children it queries.
    set innerHTML(html) {
      this.childNodes.forEach((child) => {
        child.parentNode = null;
      });
      this.childNodes = [];
      if (html.indexOf("ro-input") === -1) return;
      for (const [tagName, id, cls] of [
        ["span", "ro-progress", "ro-progress"],
        ["input", "ro-input", "tappable"],
        ["button", "ro-btn", "tappable"],
        ["div", "ro-feedback", "ro-feedback"],
      ]) {
        const child = makeEl(tagName, null, registry);
        child.id = id;
        child.className = cls;
        child.parentNode = this;
        this.childNodes.push(child);
      }
    },

    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name === "id") registry.set(String(value), this);
      if (name === "class") this.className = value;
    },
    getAttribute(name) {
      return this.attributes[name];
    },
    appendChild(child) {
      this.childNodes.push(child);
      child.parentNode = this;
      return child;
    },
    insertBefore(child, ref) {
      const i = this.childNodes.indexOf(ref);
      if (i < 0) this.childNodes.push(child);
      else this.childNodes.splice(i, 0, child);
      child.parentNode = this;
      return child;
    },
    removeChild(child) {
      const i = this.childNodes.indexOf(child);
      // Only detach what was actually ours. Clearing parentNode regardless would
      // silently orphan a node still attached somewhere else, which a real
      // removeChild refuses outright.
      if (i >= 0) {
        this.childNodes.splice(i, 1);
        child.parentNode = null;
      }
      return child;
    },
    /** Descendant lookup by `#id`, `.class`, or tag name. */
    querySelector(selector) {
      const all = [];
      (function collect(node) {
        for (const child of node.childNodes) {
          all.push(child);
          collect(child);
        }
      })(this);
      for (const node of all) {
        if (selector[0] === "#" && node.attributes.id === selector.slice(1)) return node;
        if (selector[0] === "." && node._classes.has(selector.slice(1))) return node;
        // Tag selectors match case-insensitively in HTML, which matters now that
        // tagName is uppercased the way the real DOM does it. Text nodes carry no
        // tag, so they are skipped rather than dereferenced; a real querySelector
        // considers elements only.
        if (
          node.nodeType === 1 &&
          selector[0] !== "#" &&
          selector[0] !== "." &&
          node.tagName.toLowerCase() === selector.toLowerCase()
        ) {
          return node;
        }
      }
      return null;
    },
    // Proportional-ish text metric: enough to drive wrapping and box sizing.
    getComputedTextLength() {
      // textContent, not the direct text: a real implementation measures every
      // glyph the element renders, tspans included.
      return this.textContent.length * 8;
    },
    getBoundingClientRect() {
      // `right`/`bottom` matter to callers that hit-test a point against the
      // box (marker.js does), so a rect is always returned complete.
      const r = this._rect || { width: 0, height: 0, left: 0, top: 0 };
      return {
        width: r.width,
        height: r.height,
        left: r.left,
        top: r.top,
        right: r.right === undefined ? r.left + r.width : r.right,
        bottom: r.bottom === undefined ? r.top + r.height : r.bottom,
      };
    },
    addEventListener(type, fn) {
      (this._handlers[type] = this._handlers[type] || []).push(fn);
    },
    removeEventListener(type, fn) {
      const list = this._handlers[type];
      if (!list) return;
      const i = list.indexOf(fn);
      if (i >= 0) list.splice(i, 1);
    },
    /** Invoke the listeners registered for `type` (tests drive clicks with this). */
    dispatch(type, event) {
      const ev = event || { preventDefault() {}, stopPropagation() {} };
      (this._handlers[type] || []).forEach((fn) => fn(ev));
    },
    focus() {
      this._focused = true;
    },
  };
  el.classList = {
    add: (c) => el._classes.add(c),
    remove: (c) => el._classes.delete(c),
    contains: (c) => el._classes.has(c),
    toggle: (c, force) => {
      const on = force === undefined ? !el._classes.has(c) : force;
      if (on) el._classes.add(c);
      else el._classes.delete(c);
      return on;
    },
  };
  return el;
}

/**
 * Build a card DOM and load render.js against it.
 *
 * opts: { structures, mode, direction, interaction, contextLabels, config,
 *         activeOrdinal, back, stage: {width,height}, seed }
 * Returns { render(mint), svg, ids, store, internals }.
 */
function buildCard(opts) {
  const o = Object.assign(
    {
      mode: "multi",
      direction: "forward",
      interaction: "reveal",
      contextLabels: false,
      config: {},
      activeOrdinal: 1,
      back: false,
      stage: { width: 800, height: 600 },
    },
    opts,
  );

  const ids = new Map();
  const el = (tag, ns) => makeEl(tag, ns, ids);

  const svg = el("svg");
  svg.id = "ro-overlay";
  const img = el("img");
  img._rect = { width: o.stage.width, height: o.stage.height, left: 0, top: 0 };
  const stage = el("div");
  stage.id = "ro-stage";
  stage.appendChild(img);
  const root = el("div");
  root.id = "ro-root";

  const data = el("script");
  data.id = "ro-data";
  // `legacyPayload` emits the v1 shape: a bare array with no envelope, which is
  // what notes made before the options existed still carry.
  data.textContent = o.legacyPayload
    ? b64(o.structures)
    : b64({
        v: 2,
        mode: o.mode,
        direction: o.direction,
        interaction: o.interaction,
        contextLabels: o.contextLabels,
        structures: o.structures,
      });
  const config = el("script");
  config.id = "ro-config";
  config.textContent = b64(o.config);

  const clozeSpan = el("span");
  clozeSpan.className = "cloze";
  clozeSpan.dataset.ordinal = String(o.activeOrdinal);
  const ordinal = el("div");
  ordinal.id = "ro-ordinal";
  ordinal.appendChild(clozeSpan);

  const typeBox = el("div");
  typeBox.className = "ro-type";

  if (o.back) {
    const answer = el("div");
    answer.id = "ro-answer";
  }

  const store = {};
  let seededFallback;
  if (o.seed !== undefined) {
    // A degraded store cannot hand a seed back, so a pre-set seed is modelled
    // where render.js would have left it: in the in-memory mirror. Putting it in
    // `store` instead would make buildCard({ seed, storage }) mint a random seed
    // and the test would stop being deterministic without saying so.
    if (o.storage) seededFallback = String(o.seed);
    else store[SEED_KEY] = String(o.seed);
  }

  const noop = () => {};
  const document = {
    getElementById: (id) => ids.get(id) || null,
    querySelector: (sel) => {
      if (sel === "#ro-ordinal .cloze") return clozeSpan;
      if (sel === ".ro-type") return typeBox;
      return null;
    },
    createElement: (t) => el(t),
    createElementNS: (ns, t) => el(t, ns),
  };
  const window = {
    // `noop` setTimeout keeps render.js's own `run()` bootstrap from firing, so a
    // test's explicit `render(mint)` call is the only render that happens.
    addEventListener: noop,
    setTimeout: noop,
    getComputedStyle: () => ({ fontSize: "18px" }),
    __roSeedFallback: seededFallback,
    // Two different degraded stores, because render.js handles them on two
    // different branches:
    //   "unavailable" - storage is switched off, so both calls throw;
    //   "quota"       - the store is full, so setItem throws while getItem
    //                   returns null.
    // Modelling only the throwing one leaves `stored !== null` in readSeed()
    // untested, which is the branch that keeps the answer side on the same seed
    // as the question.
    sessionStorage: {
      getItem: (k) => {
        if (o.storage === "unavailable") throw new Error("storage disabled");
        if (o.storage === "quota") return null;
        return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
      },
      setItem: (k, v) => {
        if (o.storage === "unavailable") throw new Error("storage disabled");
        if (o.storage === "quota") throw new Error("quota exceeded");
        store[k] = String(v);
      },
    },
  };

  const sandbox = { window, document, atob, TextDecoder, Uint8Array, setTimeout: noop, console };
  const api = runRenderJs(sandbox);

  return {
    svg,
    ids,
    store,
    typeBox,
    internals: api._internals,
    render: (mint) => api.render(mint),
  };
}

/** Boxes drawn on the overlay: text (joined tspans) and the box centre. */
function boxesOf(svg) {
  const out = [];
  for (const node of svg.childNodes) {
    if (node.tagName !== "g" || !node._classes.has("ro-box")) continue;
    const text = node.childNodes.find((c) => c.tagName === "text");
    const rect = node.childNodes.find((c) => c.tagName === "rect");
    const tspans = text ? text.childNodes.filter((c) => c.tagName === "tspan") : [];
    const x = rect ? Number(rect.attributes.x) : 0;
    const y = rect ? Number(rect.attributes.y) : 0;
    const w = rect ? Number(rect.attributes.width) : 0;
    const h = rect ? Number(rect.attributes.height) : 0;
    out.push({
      text: tspans.map((t) => t.textContent).join(" "),
      lines: tspans.length,
      // Text written straight onto the <text> element rather than into a tspan.
      // sizeBox() measures by writing the string there, so a missing reset would
      // leave the last measured line rendered alongside the tspans; on a forward
      // question side that is the prompt drawn twice.
      strayText: text ? text._text : "",
      // The box grows symmetrically around a size-independent centre, so the
      // CENTRE (not the top-left) is what must match between front and back.
      cx: x + w / 2,
      cy: y + h / 2,
      w,
      h,
    });
  }
  return out;
}

const dotsOf = (svg) =>
  svg.childNodes
    .filter((n) => n.tagName === "circle" && n._classes.has("ro-dot"))
    .map((n) => ({ x: Number(n.attributes.cx), y: Number(n.attributes.cy) }));

/** Arrow segments, as endpoints. Where an arrow points is the point of it. */
const arrowsOf = (svg) =>
  svg.childNodes
    .filter((n) => n.tagName === "line" && n._classes.has("ro-arrow"))
    .map((n) => ({
      x1: Number(n.attributes.x1),
      y1: Number(n.attributes.y1),
      x2: Number(n.attributes.x2),
      y2: Number(n.attributes.y2),
    }));

// `makeEl` is exported so the editor's DOM mock (marker_dom.js) builds its tree
// from the same element implementation: one mock to keep honest, not two.
module.exports = { buildCard, boxesOf, dotsOf, arrowsOf, b64, makeEl, SEED_KEY };
