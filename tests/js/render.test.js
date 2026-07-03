"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadInternals } = require("./harness.js");

const I = loadInternals();

// ---- seeded RNG: determinism is what keeps front & back identical -----------

test("makeRng is deterministic for a seed and stays in [0, 1)", () => {
  const a = I.makeRng(12345);
  const b = I.makeRng(12345);
  const seqA = [a(), a(), a(), a(), a()];
  const seqB = [b(), b(), b(), b(), b()];
  assert.deepEqual(seqA, seqB);
  for (const v of seqA) assert.ok(v >= 0 && v < 1, `in range: ${v}`);
});

test("makeRng produces different streams for different seeds", () => {
  const a = I.makeRng(1);
  const b = I.makeRng(2);
  assert.notEqual(a(), b());
});

test("hashString is deterministic and an unsigned 32-bit int", () => {
  assert.equal(I.hashString("aorta"), I.hashString("aorta"));
  assert.notEqual(I.hashString("aorta"), I.hashString("vena cava"));
  const h = I.hashString("anything");
  assert.ok(Number.isInteger(h) && h >= 0 && h <= 0xffffffff);
});

// ---- clamp ------------------------------------------------------------------

test("clamp keeps values within bounds and tolerates inverted bounds", () => {
  assert.equal(I.clamp(5, 0, 1), 1);
  assert.equal(I.clamp(-5, 0, 1), 0);
  assert.equal(I.clamp(0.5, 0, 1), 0.5);
  assert.equal(I.clamp(0.5, 1, 0), 1); // hi < lo → lo
});

// ---- shuffle: must be a permutation, deterministically ----------------------

test("shuffleIndices returns a permutation of 0..n-1", () => {
  const arr = I.shuffleIndices(25, I.makeRng(99));
  assert.equal(arr.length, 25);
  const sorted = [...arr].sort((x, y) => x - y);
  assert.deepEqual(
    sorted,
    Array.from({ length: 25 }, (_, i) => i),
  );
});

test("shuffleIndices is deterministic for the same seed", () => {
  assert.deepEqual(I.shuffleIndices(10, I.makeRng(7)), I.shuffleIndices(10, I.makeRng(7)));
});

// ---- answer normalisation (type-to-answer grading) --------------------------

test("normalizeAnswer trims, lowercases, and collapses whitespace", () => {
  assert.equal(I.normalizeAnswer("  Aorta "), "aorta");
  assert.equal(I.normalizeAnswer("Vena\t  Cava"), "vena cava");
  assert.equal(I.normalizeAnswer(null), "");
  assert.equal(I.normalizeAnswer(""), "");
});

// ---- base64/UTF-8 payload decode --------------------------------------------

test("decodeBase64Utf8 round-trips UTF-8 including non-ASCII", () => {
  const source = "café — ✓ Ω 中文";
  const encoded = Buffer.from(source, "utf8").toString("base64");
  assert.equal(I.decodeBase64Utf8(encoded), source);
});

// ---- placement: in-bounds, min arrow length, front/back parity --------------

const STAGE = { w: 800, h: 600 };
const CFG = { minArrowFraction: 0.22, maxPlacementAttempts: 48 };

test("placeCenter always returns a centre inside the stage", () => {
  const rng = I.makeRng(42);
  for (let i = 0; i < 300; i++) {
    const target = { x: rng() * STAGE.w, y: rng() * STAGE.h };
    const c = I.placeCenter(rng, STAGE, target, CFG);
    assert.ok(c.x >= 0 && c.x <= STAGE.w, `x in range: ${c.x}`);
    assert.ok(c.y >= 0 && c.y <= STAGE.h, `y in range: ${c.y}`);
    assert.ok(Number.isFinite(c.x) && Number.isFinite(c.y));
  }
});

test("placeCenter honours (close to) the minimum arrow length with room", () => {
  const diag = Math.hypot(STAGE.w, STAGE.h);
  const minLen = CFG.minArrowFraction * diag;
  const rng = I.makeRng(3);
  const target = { x: STAGE.w / 2, y: STAGE.h / 2 };
  let ok = 0;
  const total = 100;
  for (let i = 0; i < total; i++) {
    const c = I.placeCenter(rng, STAGE, target, CFG);
    if (Math.hypot(c.x - target.x, c.y - target.y) >= minLen * 0.8) ok++;
  }
  assert.ok(ok >= total * 0.9, `most placements meet the min arrow length: ${ok}/${total}`);
});

test("same seed reproduces the same box centre (front/back parity)", () => {
  const target = { x: 500, y: 400 };
  const front = I.placeCenter(I.makeRng(777), STAGE, target, CFG);
  const back = I.placeCenter(I.makeRng(777), STAGE, target, CFG);
  assert.deepEqual(front, back);
});

test("placeCenters returns one in-bounds centre per target", () => {
  const targets = [
    { x: 100, y: 100 },
    { x: 400, y: 300 },
    { x: 700, y: 500 },
    { x: 200, y: 500 },
  ];
  const centers = I.placeCenters(I.makeRng(5), STAGE, targets, CFG);
  assert.equal(centers.length, targets.length);
  for (const c of centers) {
    assert.ok(c.x >= 0 && c.x <= STAGE.w);
    assert.ok(c.y >= 0 && c.y <= STAGE.h);
  }
});

// Regression: a tiny image + high minArrowFraction + corner target used to make
// the placement fall back to ~1px from the target, so the arrow was invisible.
const TINY = { w: 100, h: 100 };
const HARD = { minArrowFraction: 0.5, maxPlacementAttempts: 48 };

test("placeCenter never produces a near-zero arrow on a constrained stage", () => {
  const target = { x: 85, y: 85 };
  for (let seed = 0; seed < 25; seed++) {
    const c = I.placeCenter(I.makeRng(seed), TINY, target, HARD);
    const len = Math.hypot(c.x - target.x, c.y - target.y);
    assert.ok(len > 40, `visible arrow (seed ${seed}): ${len}`);
  }
});

test("placeCenters never produces a near-zero arrow on a constrained stage", () => {
  const targets = [
    { x: 85, y: 85 },
    { x: 15, y: 15 },
    { x: 85, y: 15 },
  ];
  const centers = I.placeCenters(I.makeRng(4), TINY, targets, HARD);
  centers.forEach((c, i) => {
    const len = Math.hypot(c.x - targets[i].x, c.y - targets[i].y);
    assert.ok(len > 40, `visible arrow for target ${i}: ${len}`);
  });
});

// ---- box border geometry ----------------------------------------------------

test("boxBorderToward lands on the box edge toward the target", () => {
  const box = { x: 100, y: 100, w: 40, h: 30 }; // centre (120, 115)
  const p = I.boxBorderToward(box, { x: 400, y: 115 }); // straight right
  assert.ok(Math.abs(p.x - 140) < 1e-6, `right edge x: ${p.x}`);
  assert.ok(Math.abs(p.y - 115) < 1e-6, `centre y: ${p.y}`);
});

test("boxBorderToward returns the centre for a coincident target", () => {
  const box = { x: 0, y: 0, w: 40, h: 30 };
  const p = I.boxBorderToward(box, { x: 20, y: 15 }); // centre == target
  assert.equal(p.x, 20);
  assert.equal(p.y, 15);
});

// ---- single-card cycler layout ----------------------------------------------

test("computeSingleLayout is deterministic and covers every structure", () => {
  const structures = [
    { x: 0.2, y: 0.3, label: "A" },
    { x: 0.6, y: 0.7, label: "B" },
    { x: 0.8, y: 0.2, label: "C" },
  ];
  const first = I.computeSingleLayout(123, STAGE, structures, CFG);
  const second = I.computeSingleLayout(123, STAGE, structures, CFG);
  assert.deepEqual(first.order, second.order);
  assert.deepEqual(first.centers, second.centers);
  assert.deepEqual(
    [...first.order].sort((a, b) => a - b),
    [0, 1, 2],
  );
  assert.equal(first.centers.length, 3);
  assert.equal(first.targets.length, 3);
  assert.equal(first.targets[0].x, 0.2 * STAGE.w); // projected to pixels
  assert.equal(first.targets[0].y, 0.3 * STAGE.h);
});

// ---- active-card resolution (ordinal -> structure index + direction) --------

// render.js runs in a vm sandbox, so objects it returns carry that realm's
// prototype; spreading into a plain literal lets strict deepEqual compare them.
const active = (ord, dir, count) => ({ ...I.resolveActiveCard(ord, dir, count) });

test("resolveActiveCard maps forward-mode ordinals to 0-based indices", () => {
  assert.deepEqual(active(1, "forward", 2), { activeIndex: 0, cardDir: "forward" });
  assert.deepEqual(active(2, "forward", 2), { activeIndex: 1, cardDir: "forward" });
});

test("resolveActiveCard carries reverse direction through", () => {
  assert.deepEqual(active(1, "reverse", 2), { activeIndex: 0, cardDir: "reverse" });
});

test("resolveActiveCard splits each both-mode structure into forward then reverse", () => {
  // In "both" mode structure k owns ordinals 2k-1 (forward) and 2k (reverse).
  assert.deepEqual(active(1, "both", 2), { activeIndex: 0, cardDir: "forward" });
  assert.deepEqual(active(2, "both", 2), { activeIndex: 0, cardDir: "reverse" });
  assert.deepEqual(active(3, "both", 2), { activeIndex: 1, cardDir: "forward" });
  assert.deepEqual(active(4, "both", 2), { activeIndex: 1, cardDir: "reverse" });
});

test("resolveActiveCard clamps out-of-range ordinals to the first structure", () => {
  assert.deepEqual(active(0, "forward", 2), { activeIndex: 0, cardDir: "forward" });
  assert.deepEqual(active(5, "forward", 2), { activeIndex: 0, cardDir: "forward" });
});
