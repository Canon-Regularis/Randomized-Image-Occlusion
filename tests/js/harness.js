"use strict";

// Loads the reviewer renderer (which is written to run inside Anki's webview)
// into a headless `vm` sandbox with just enough DOM fakes that its top-level
// IIFE runs without a browser, then hands back the pure helper functions it
// exposes on `window.RandomizedOcclusion._internals`.
//
// The DOM here is deliberately minimal: `getElementById` returns null, so
// `render()` bails immediately and only the pure geometry/decoding helpers can
// be exercised. Tests that need the renderer to actually draw use `dom.js`.

const { runRenderJs } = require("./loader.js");

function stubNode() {
  return {
    setAttribute() {},
    appendChild() {},
    insertBefore() {},
    removeChild() {},
    getComputedTextLength() {
      return 0;
    },
    style: {},
    dataset: {},
    textContent: "",
    firstChild: null,
  };
}

function loadInternals() {
  const noop = () => {};
  const store = {};
  const windowObj = {
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
  const documentObj = {
    getElementById: () => null,
    querySelector: () => null,
    createElement: () => stubNode(),
    createElementNS: () => stubNode(),
  };
  const sandbox = {
    window: windowObj,
    document: documentObj,
    atob,
    TextDecoder,
    Uint8Array,
    setTimeout: noop,
    console,
  };
  const api = runRenderJs(sandbox);
  if (!api._internals) {
    throw new Error("render.js did not expose RandomizedOcclusion._internals");
  }
  return api._internals;
}

module.exports = { loadInternals };
