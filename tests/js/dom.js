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
    // The options bag is honoured rather than dropped. render.js registers
    // its load/error handlers with `{once: true}` and relies on the browser
    // detaching them; a mock that ignored that would happily re-enter a
    // handler the browser would never call twice, so a lost `once` -- a second
    // render, the seed minted again -- was unreachable to every test.
    addEventListener(type, fn, options) {
      // `true` is the capture flag, not a bag; capture changes ordering
      // between ancestors, which this mock does not model, so only `once` is
      // read here.
      const once = !!(options && options !== true && options.once);
      (this._handlers[type] = this._handlers[type] || []).push({ fn, once });
    },
    removeEventListener(type, fn) {
      const list = this._handlers[type];
      if (!list) return;
      const i = list.findIndex((h) => h.fn === fn);
      if (i >= 0) list.splice(i, 1);
    },
    /** Invoke the listeners registered for `type` (tests drive clicks with this). */
    dispatch(type, event) {
      const ev = event || { preventDefault() {}, stopPropagation() {} };
      const list = this._handlers[type] || [];
      // Detach before calling, as a browser does: a `once` handler that
      // dispatches the same event again must not find itself still attached.
      for (const h of [...list]) {
        if (h.once) {
          const i = list.indexOf(h);
          if (i >= 0) list.splice(i, 1);
        }
        h.fn(ev);
      }
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
  // `detachedImage` builds the card with the stage present but EMPTY, which is
  // what a parse-mode client looks like before the card HTML has finished
  // arriving. run() has a separate retry for that -- distinct from the one for
  // an image that exists but is not laid out yet -- and until this option there
  // was no way to reach it.
  if (!o.detachedImage) stage.appendChild(img);
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

  // Session storage survives a page load, so the question and answer sides of
  // one card share it. Passing `store` lets a test model that handoff; without
  // it each card gets its own, which cannot express a value written by one page
  // and read by the next.
  const store = o.store || {};
  let seededFallback;
  if (o.seed !== undefined) {
    // "unavailable" cannot hand a seed back at all, so a pre-set seed is modelled
    // where render.js would have left it: in the in-memory mirror. Under "quota"
    // reads still work, so the store is the faithful place -- and it is what lets
    // a test set up the stale-key case.
    if (o.storage === "unavailable") seededFallback = String(o.seed);
    else store[SEED_KEY] = String(o.seed);
  }

  const noop = () => {};

  // A controllable clock. render.js calls run() as its script loads, and run()
  // does everything through setTimeout: the once-per-show guard, the bounded
  // retry for an image that is not laid out yet, and the resize re-render. With
  // setTimeout noop'd none of that could ever execute, so the whole bootstrap
  // was unreachable to every test. `timers: "manual"` queues the callbacks
  // instead, and the card exposes flushTimers()/fire() to step them.
  const manual = o.timers === "manual";
  // A virtual clock, not a bag of callbacks. The delay used to be discarded,
  // which made the three timers in run() -- the 0 ms post-render, the 16 ms
  // retry and the 250 ms safety net -- indistinguishable: changing 250 to
  // 25000 left every bootstrap test green, and nothing could assert that the
  // safety net fires only after load and error have had their chance.
  const queued = [];
  let clock = 0;
  let ticket = 0;
  const listeners = new Map();
  const setTimeoutImpl = manual
    ? (fn, delay) => {
        ticket += 1;
        queued.push({ fn, at: clock + (Number(delay) || 0), seq: ticket });
        return ticket;
      }
    : noop;
  const addEventListenerImpl = manual
    ? (type, fn, options) => {
        const once = !!(options && options !== true && options.once);
        if (!listeners.has(type)) listeners.set(type, []);
        listeners.get(type).push({ fn, once });
      }
    : noop;

  /** The earliest timer still queued, or null. Ties break by arrival order. */
  function nextDue() {
    let best = null;
    for (const timer of queued) {
      const sooner = !best || timer.at < best.at;
      if (sooner || (best && timer.at === best.at && timer.seq < best.seq)) {
        best = timer;
      }
    }
    return best;
  }

  /**
   * Run due callbacks in delay order until none are left at or before
   * `until`, or `rounds` of them have run.
   *
   * Bounded on purpose: the retry in run() re-arms itself, so an image that
   * never gains a size would spin here exactly as it would in a browser. The
   * cap is what lets a test assert the retry gives up.
   */
  function drain(until, rounds) {
    let ran = 0;
    while (ran < rounds) {
      const timer = nextDue();
      if (!timer || timer.at > until) break;
      queued.splice(queued.indexOf(timer), 1);
      // The clock only moves forward, to the moment this timer came due, so a
      // callback that arms another one measures its delay from there.
      clock = Math.max(clock, timer.at);
      timer.fn();
      ran += 1;
    }
    return ran;
  }

  function flushTimers(rounds = 200) {
    return drain(Infinity, rounds);
  }

  /** Run only what is due within `ms` of now, leaving longer timers queued. */
  function advanceTimers(ms, rounds = 200) {
    const until = clock + ms;
    const ran = drain(until, rounds);
    clock = Math.max(clock, until);
    return ran;
  }
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
    // Without `timers: "manual"` these stay noops, so render.js's own run()
    // bootstrap never fires and a test's explicit render(mint) call is the only
    // render that happens.
    addEventListener: addEventListenerImpl,
    setTimeout: setTimeoutImpl,
    getComputedStyle: () => ({ fontSize: "18px" }),
    __roSeedFallback: seededFallback,
    // Two different degraded stores, because render.js handles them on two
    // different branches:
    //   "unavailable" - storage is switched off, so both calls throw;
    //   "quota"       - the store is full, so setItem throws while getItem
    //                   still serves whatever is ALREADY there.
    // getItem used to return null unconditionally under "quota", which made the
    // interesting case unrepresentable: a failed write while a previous card's
    // seed is still stored. That is the one case where a presence check mistakes
    // a stale value for a successful write, and no test could reach it.
    sessionStorage: {
      getItem: (k) => {
        if (o.storage === "unavailable") throw new Error("storage disabled");
        return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
      },
      setItem: (k, v) => {
        if (o.storage === "unavailable") throw new Error("storage disabled");
        if (o.storage === "quota") throw new Error("quota exceeded");
        store[k] = String(v);
      },
      // Removal works even on a full store; only a disabled one refuses.
      removeItem: (k) => {
        if (o.storage === "unavailable") throw new Error("storage disabled");
        delete store[k];
      },
    },
  };

  const sandbox = {
    window,
    document,
    atob,
    TextDecoder,
    Uint8Array,
    setTimeout: setTimeoutImpl,
    console,
  };
  const api = runRenderJs(sandbox);

  return {
    svg,
    ids,
    store,
    typeBox,
    internals: api._internals,
    render: (mint) => api.render(mint),
    img,
    flushTimers,
    advanceTimers,
    /** Put a `detachedImage` card's <img> into the stage, as a late parse does. */
    attachImage: () => stage.appendChild(img),
    /** Re-run the bootstrap, as showing another card in the same webview does. */
    run: () => api.run(),
    /** Fire a window event render.js has subscribed to (only with manual timers). */
    fire: (type) => {
      const list = listeners.get(type) || [];
      for (const h of [...list]) {
        if (h.once) {
          const i = list.indexOf(h);
          if (i >= 0) list.splice(i, 1);
        }
        h.fn();
      }
    },
    listenerCount: (type) => (listeners.get(type) || []).length,
    pendingTimers: () => queued.length,
    /** The delays still queued, soonest first. Lets a test name the timer. */
    timerDelays: () =>
      queued
        .slice()
        .sort((a, b) => a.at - b.at || a.seq - b.seq)
        .map((timer) => timer.at - clock),
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
      // The grading colour, which drawBox puts on the RECT rather than the
      // group: "ro-box-rect ro-correct".
      classes: rect ? [...rect._classes] : [],
    });
  }
  return out;
}

const dotsOf = (svg) =>
  svg.childNodes
    .filter((n) => n.tagName === "circle" && n._classes.has("ro-dot"))
    .map((n) => ({ x: Number(n.attributes.cx), y: Number(n.attributes.cy) }));

// Below this a leader line is not something a learner can see, so counting it
// as an arrow would be a lie the elimination invariant believed: a zero-length
// <line> still reports x2,y2 sitting on its target, which is exactly what
// "this dot is arrowed" was decided by.
const MIN_VISIBLE_ARROW = 1;

/**
 * Visible arrow segments, as endpoints. Where an arrow points is the point of
 * it -- and one too short to render points nowhere, so it is dropped here
 * rather than counted.
 */
const arrowsOf = (svg) =>
  svg.childNodes
    .filter((n) => n.tagName === "line" && n._classes.has("ro-arrow"))
    .map((n) => {
      const x1 = Number(n.attributes.x1);
      const y1 = Number(n.attributes.y1);
      const x2 = Number(n.attributes.x2);
      const y2 = Number(n.attributes.y2);
      return { x1, y1, x2, y2, length: Math.hypot(x2 - x1, y2 - y1) };
    })
    .filter((a) => a.length >= MIN_VISIBLE_ARROW);

// `makeEl` is exported so the editor's DOM mock (marker_dom.js) builds its tree
// from the same element implementation: one mock to keep honest, not two.
module.exports = { buildCard, boxesOf, dotsOf, arrowsOf, b64, makeEl, SEED_KEY };
