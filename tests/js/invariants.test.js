"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { RENDER_JS } = require("./harness.js");

const WEB_DIR = path.join(__dirname, "..", "..", "src", "randomized_occlusion", "web");
const MARKER_JS = path.join(WEB_DIR, "editor", "marker.js");

test("render.js contains no Anki field tokens ('{{' or '}}')", () => {
  // render.js is inlined into the card template, so any '{{'/'}}' would be
  // mis-parsed by Anki as a field reference and break every card.
  const code = fs.readFileSync(RENDER_JS, "utf8");
  assert.ok(!code.includes("{{"), "render.js must not contain '{{'");
  assert.ok(!code.includes("}}"), "render.js must not contain '}}'");
});

test("render.js parses as valid JavaScript", () => {
  const code = fs.readFileSync(RENDER_JS, "utf8");
  assert.doesNotThrow(() => new vm.Script(code, { filename: "render.js" }));
});

test("marker.js parses as valid JavaScript", () => {
  const code = fs.readFileSync(MARKER_JS, "utf8");
  assert.doesNotThrow(() => new vm.Script(code, { filename: "marker.js" }));
});
