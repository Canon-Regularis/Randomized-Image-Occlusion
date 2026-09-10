"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const { RENDER_JS, MARKER_JS, MARKER_HTML, BRIDGE_PY } = require("./loader.js");

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

test("every element id marker.js looks up exists in marker.html", () => {
  // dialog.py concatenates the three editor assets at runtime, so a rename in
  // one is a no-op in another: el() returns null and the feature stops working
  // with no error. This test is the only thing that catches it.
  const js = fs.readFileSync(MARKER_JS, "utf8");
  const html = fs.readFileSync(MARKER_HTML, "utf8");
  const declared = new Set(
    [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]),
  );
  const used = new Set([...js.matchAll(/el\("([^"]+)"\)/g)].map((m) => m[1]));
  assert.ok(used.size > 0, "no el() lookups found; has the helper been renamed?");
  const missing = [...used].filter((id) => !declared.has(id));
  assert.deepEqual(missing, [], `marker.js looks up ids marker.html does not define`);
});

test("every pycmd message marker.js sends is routed by the Python bridge", () => {
  // The two ends of this protocol are in different languages and are joined
  // only at runtime. The bridge ignores unrecognised messages, so renaming one
  // side is a silent no-op on the other.
  const js = fs.readFileSync(MARKER_JS, "utf8");
  const bridge = fs.readFileSync(BRIDGE_PY, "utf8");
  const sent = [...new Set([...js.matchAll(/send\("ro:([a-z]+)/g)].map((m) => m[1]))];
  assert.ok(sent.length >= 4, `only found ${sent.length} pycmd sends; has send() been renamed?`);
  const unrouted = sent.filter(
    (name) => !bridge.includes(`"${name}"`) && !bridge.includes(`"${name}:"`),
  );
  assert.deepEqual(unrouted, [], "marker.js sends messages bridge.py does not handle");
});
