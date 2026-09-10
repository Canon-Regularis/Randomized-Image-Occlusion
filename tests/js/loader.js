"use strict";

// Locating the two inlined scripts and evaluating them inside a `vm` sandbox is
// needed by every DOM stub (the minimal one in harness.js for render.js's pure
// helpers, the full card in dom.js for end-to-end rendering, and the editor in
// marker_dom.js) as well as by the invariant tests that read the files as text.
// Keeping the paths and the vm wiring here means they exist exactly once.

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const WEB_DIR = path.join(__dirname, "..", "..", "src", "randomized_occlusion", "web");
const RENDER_JS = path.join(WEB_DIR, "review", "render.js");
const MARKER_JS = path.join(WEB_DIR, "editor", "marker.js");
const MARKER_HTML = path.join(WEB_DIR, "editor", "marker.html");
// The Python half of the editor's pycmd protocol, read as text by the
// invariant test that keeps the two ends of it in step.
const BRIDGE_PY = path.join(
  __dirname, "..", "..", "src", "randomized_occlusion", "editor", "bridge.py",
);

/**
 * Evaluate render.js in `sandbox` and hand back the API it exposes.
 * The caller supplies whatever DOM/window stubs its test needs.
 */
function runRenderJs(sandbox) {
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(RENDER_JS, "utf8"), sandbox, { filename: "render.js" });
  const api = sandbox.window && sandbox.window.RandomizedOcclusion;
  if (!api) throw new Error("render.js did not expose window.RandomizedOcclusion");
  return api;
}

/**
 * Evaluate marker.js in `sandbox` and hand back the API it exposes.
 * The caller supplies whatever DOM/window stubs its test needs.
 */
function runMarkerJs(sandbox) {
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MARKER_JS, "utf8"), sandbox, { filename: "marker.js" });
  const api = sandbox.window && sandbox.window.ROEditor;
  if (!api) throw new Error("marker.js did not expose window.ROEditor");
  return api;
}

module.exports = {
  RENDER_JS,
  MARKER_JS,
  MARKER_HTML,
  BRIDGE_PY,
  WEB_DIR,
  runRenderJs,
  runMarkerJs,
};
