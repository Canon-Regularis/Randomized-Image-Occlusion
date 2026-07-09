"use strict";

// Geometry at the extremes a real image and its markers can actually reach:
// structures marked exactly on a corner or an edge, images with awkward aspect
// ratios, and many markers crowded into one corner. The prompt box must always
// end up somewhere on the image with an arrow long enough to see — a box sitting
// on top of its own target, or drifting off the picture, is a broken card.

const test = require("node:test");
const assert = require("node:assert/strict");
const { loadInternals } = require("./harness.js");

const I = loadInternals();

// Displayed image sizes a card realistically renders at.
const STAGES = [
  { w: 600, h: 600, name: "square" },
  { w: 1200, h: 300, name: "panoramic" },
  { w: 300, h: 1200, name: "tall" },
  { w: 200, h: 150, name: "small" },
];
const CONFIGS = [
  { minArrowFraction: 0.22, maxPlacementAttempts: 48, name: "default" },
  { minArrowFraction: 0.5, maxPlacementAttempts: 48, name: "long-arrow" },
];
// Corners, edge midpoints, and the centre — all reachable by clicking the canvas.
const NORMALISED = [
  [0, 0],
  [1, 1],
  [0, 1],
  [1, 0],
  [0.5, 0],
  [0, 0.5],
  [1, 0.5],
  [0.5, 1],
  [0.5, 0.5],
];

const SEEDS = Array.from({ length: 40 }, (_, i) => (i * 2246822519 + 7) >>> 0);
// The dot has radius 5 and the box border sits a few px out; below this the arrow
// reads as "no arrow at all".
const VISIBLE_ARROW = 12;

const finite = (v) => typeof v === "number" && Number.isFinite(v);

test("a structure marked on any corner or edge still gets a visible arrow", () => {
  for (const stage of STAGES) {
    for (const config of CONFIGS) {
      for (const [nx, ny] of NORMALISED) {
        const target = { x: nx * stage.w, y: ny * stage.h };
        for (const seed of SEEDS) {
          const centre = I.placeCenter(I.makeRng(seed), stage, target, config);
          const where = `${stage.name}/${config.name}/(${nx},${ny})/seed ${seed}`;

          assert.ok(finite(centre.x) && finite(centre.y), `non-finite centre at ${where}`);
          assert.ok(
            centre.x >= -1e-3 && centre.x <= stage.w + 1e-3 && centre.y >= -1e-3 && centre.y <= stage.h + 1e-3,
            `centre left the image at ${where}`,
          );
          const arrow = Math.hypot(centre.x - target.x, centre.y - target.y);
          assert.ok(arrow >= VISIBLE_ARROW, `arrow only ${arrow.toFixed(2)}px at ${where}`);
        }
      }
    }
  }
});

test("markers crowded into one corner each keep a visible arrow", () => {
  const targets = Array.from({ length: 8 }, (_, i) => ({ x: 0, y: 0, label: `L${i}` }));
  for (const stage of STAGES) {
    for (const config of CONFIGS) {
      targets.forEach((t, i) => {
        t.x = (0.02 + i * 0.01) * stage.w;
        t.y = (0.02 + i * 0.01) * stage.h;
      });
      for (const seed of SEEDS.slice(0, 12)) {
        const centres = I.placeCenters(I.makeRng(seed), stage, targets, config);
        assert.equal(centres.length, targets.length);
        centres.forEach((centre, i) => {
          assert.ok(finite(centre.x) && finite(centre.y), "non-finite clustered centre");
          const arrow = Math.hypot(centre.x - targets[i].x, centre.y - targets[i].y);
          assert.ok(
            arrow >= VISIBLE_ARROW,
            `clustered arrow only ${arrow.toFixed(2)}px (${stage.name}/${config.name}, marker ${i})`,
          );
        });
      }
    }
  }
});

test("boxBorderToward stays sane when the target touches the box", () => {
  const box = { x: 100, y: 100, w: 120, h: 40 }; // centre (160, 120)
  const cases = [
    { point: { x: 160, y: 120 }, name: "target exactly at the box centre" },
    { point: { x: 160, y: 120 + 1e-7 }, name: "target a hair off the centre" },
    { point: { x: 220, y: 120 }, name: "target on the right edge" },
    { point: { x: 100, y: 100 }, name: "target on the top-left corner" },
    { point: { x: 160, y: 100 }, name: "target on the top edge" },
  ];
  for (const { point, name } of cases) {
    const p = I.boxBorderToward(box, point);
    assert.ok(finite(p.x) && finite(p.y), `non-finite border point for ${name}`);
    assert.ok(
      p.x >= box.x - 1 && p.x <= box.x + box.w + 1 && p.y >= box.y - 1 && p.y <= box.y + box.h + 1,
      `border point escaped the box for ${name}`,
    );
  }
});
