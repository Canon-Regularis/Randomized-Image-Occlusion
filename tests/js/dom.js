"use strict";

// A DOM mock rich enough to run the reviewer's real `render()` end to end.
//
// `harness.js` loads render.js with a *minimal* DOM: `getElementById` returns
// null, so `render()` bails immediately and only the pure helpers can be tested.
// This module instead builds a whole card — stage, image, SVG overlay, payload
// and config script tags, the active cloze span — so the renderer actually
// draws. Tests can then inspect what it put on the overlay (boxes, their text,
// arrows, dots) and how it left the type-answer box, which is behaviour the
// pure-helper tests cannot reach.
//
// Determinism: `render(true)` mints a fresh random seed. Pass `seed` to
// pre-populate session storage and call `render(false)` instead — the renderer
// then reuses that seed, so every layout/direction decision is reproducible.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const RENDER_JS = path.join(
  __dirname,
  "..",
  "..",
  "src",
  "randomized_occlusion",
  "web",
  "review",
  "render.js",
);
const SEED_KEY = "randomizedOcclusion.seed";

/** Base64 of compact JSON — the wire format the card embeds. */
function b64(value) {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64");
}

/** One mock element. `registry` maps ids to elements for `getElementById`. */
function makeEl(tag, ns, registry) {
  const el = {
    tagName: tag,
    ns: ns || null,
    attributes: {},
    childNodes: [],
    style: {},
    dataset: {},
    _text: "",
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
    // Real `textContent` concatenates descendants and clears children on write.
    get textContent() {
      if (this.childNodes.length) return this.childNodes.map((c) => c.textContent).join("");
      return this._text;
    },
    set textContent(value) {
      this.childNodes = [];
      this._text = String(value);
    },
    // The cycler bar sets a fixed innerHTML; recreate the children it queries.
    set innerHTML(html) {
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
      return child;
    },
    insertBefore(child, ref) {
      const i = this.childNodes.indexOf(ref);
      if (i < 0) this.childNodes.push(child);
      else this.childNodes.splice(i, 0, child);
      return child;
    },
    removeChild(child) {
      const i = this.childNodes.indexOf(child);
      if (i >= 0) this.childNodes.splice(i, 1);
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
        if (selector[0] !== "#" && selector[0] !== "." && node.tagName === selector) return node;
      }
      return null;
    },
    // Proportional-ish text metric: enough to drive wrapping and box sizing.
    getComputedTextLength() {
      return (this._text || "").length * 8;
    },
    getBoundingClientRect() {
      return this._rect || { width: 0, height: 0, left: 0, top: 0 };
    },
    addEventListener(type, fn) {
      (this._handlers[type] = this._handlers[type] || []).push(fn);
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
  data.textContent = b64({
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
  if (o.seed !== undefined) store[SEED_KEY] = String(o.seed);

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
    sessionStorage: {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    },
  };

  const sandbox = { window, document, atob, TextDecoder, Uint8Array, setTimeout: noop, console };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(RENDER_JS, "utf8"), sandbox, { filename: "render.js" });
  const api = sandbox.window.RandomizedOcclusion;

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
      text: tspans.map((t) => t._text).join(" "),
      lines: tspans.length,
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

const arrowsOf = (svg) =>
  svg.childNodes.filter((n) => n.tagName === "line" && n._classes.has("ro-arrow")).length;

module.exports = { buildCard, boxesOf, dotsOf, arrowsOf, b64, SEED_KEY };
