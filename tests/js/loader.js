"use strict";

// Locating render.js and evaluating it inside a `vm` sandbox is needed by both
// DOM stubs — the minimal one in harness.js (for the pure helpers) and the full
// card in dom.js (for end-to-end rendering) — as well as by the invariant tests
// that read the file as text. Keeping the path and the vm wiring here means they
// exist exactly once.

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

module.exports = { RENDER_JS, runRenderJs };
