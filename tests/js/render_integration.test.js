"use strict";

// End-to-end tests of the reviewer's multi-card `render()`: what it actually
// DRAWS. The pure-helper tests in render.test.js cover the maths; these drive
// the whole renderer against a headless card (see dom.js) and assert the card a
// learner would see — prompt text, arrow, dots, the native type-answer box — and
// above all that the FRONT and BACK agree.
//
// Every test pre-seeds session storage and renders with `mint=false`, so the
// layout and the "both"-direction coin are reproducible (a minting render would
// draw a fresh random seed and make these tests flaky).

const test = require("node:test");
const assert = require("node:assert/strict");
const { buildCard, boxesOf, dotsOf, arrowsOf } = require("./dom.js");

const STRUCTURES = [
  { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
  { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
  { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
  { ord: 4, x: 0.35, y: 0.6, label: "Pulmonary trunk" },
];
const SEEDS = [1, 7, 12, 23, 99, 1234, 65535, 2654435761];
const DOTS_ON = { showDecoyDots: true, showTargetDot: true };

/** Render one side of a card with a fixed seed. */
function side(overrides) {
  const card = buildCard(
    Object.assign({ structures: STRUCTURES, config: DOTS_ON }, overrides),
  );
  card.render(false); // reuse the pre-seeded seed rather than minting
  return card;
}

// ---- prompt / answer semantics ---------------------------------------------

test("a forward card asks with the prompt text and answers with the label", () => {
  for (const seed of SEEDS) {
    for (const activeOrdinal of [1, 2, 3, 4]) {
      const front = side({ direction: "forward", activeOrdinal, seed });
      const back = side({ direction: "forward", activeOrdinal, seed, back: true });
      const label = STRUCTURES[activeOrdinal - 1].label;

      assert.equal(boxesOf(front.svg).length, 1, "one box on a non-context card");
      assert.equal(boxesOf(front.svg)[0].text, "?", "question side shows the prompt text");
      assert.ok(arrowsOf(front.svg) >= 1, "forward question side points an arrow at the structure");
      assert.equal(boxesOf(back.svg)[0].text, label, "answer side reveals the label");
      assert.ok(arrowsOf(back.svg) >= 1, "answer side keeps the arrow");
    }
  }
});

test("a reverse card names the structure and withholds the arrow until the answer", () => {
  for (const seed of SEEDS) {
    const activeOrdinal = 2;
    const front = side({ direction: "reverse", activeOrdinal, seed });
    const back = side({ direction: "reverse", activeOrdinal, seed, back: true });
    const label = STRUCTURES[activeOrdinal - 1].label;

    assert.equal(boxesOf(front.svg)[0].text, label, "reverse question side shows the name");
    assert.equal(arrowsOf(front.svg), 0, "reverse question side must not point at the answer");
    assert.equal(boxesOf(back.svg)[0].text, label);
    assert.ok(arrowsOf(back.svg) >= 1, "the answer reveals where it is");
  }
});

// ---- the invariant the whole add-on rests on --------------------------------

test("the answer box lands exactly where the question box was", () => {
  // The box widens to fit the longer label, so its top-left legitimately moves;
  // the CENTRE is what must be identical, front and back.
  for (const direction of ["forward", "reverse", "both"]) {
    for (const seed of SEEDS) {
      for (const activeOrdinal of [1, 3]) {
        const front = boxesOf(side({ direction, activeOrdinal, seed }).svg)[0];
        const back = boxesOf(side({ direction, activeOrdinal, seed, back: true }).svg)[0];
        assert.ok(
          Math.abs(front.cx - back.cx) < 1e-6 && Math.abs(front.cy - back.cy) < 1e-6,
          `centre moved (${direction}, seed ${seed}): front ${front.cx},${front.cy} vs back ${back.cx},${back.cy}`,
        );
      }
    }
  }
});

test("a both-direction card rolls the same way on the front and the back", () => {
  const rolls = new Set();
  for (const seed of SEEDS) {
    const front = side({ direction: "both", activeOrdinal: 1, seed });
    const back = side({ direction: "both", activeOrdinal: 1, seed, back: true });
    // The type-answer box is hidden exactly on reverse rolls, so its visibility
    // reports which way this review rolled.
    assert.equal(
      front.typeBox.style.display,
      back.typeBox.style.display,
      `front and back disagree on the roll for seed ${seed}`,
    );
    // The roll must match the coin the renderer derives from the same seed.
    const forward = front.internals.directionCoin(seed);
    assert.equal(front.typeBox.style.display, forward ? "" : "none");
    rolls.add(forward);
  }
  assert.equal(rolls.size, 2, "these seeds must exercise both a forward and a reverse roll");
});

test("the native type-answer box is hidden on reverse cards, shown on forward", () => {
  const forward = side({ direction: "forward", seed: 1 });
  const reverse = side({ direction: "reverse", seed: 1 });
  assert.equal(forward.typeBox.style.display, "");
  assert.equal(reverse.typeBox.style.display, "none");
});

// ---- context labels ---------------------------------------------------------

test("context-label cards draw every structure on both sides", () => {
  const front = side({ direction: "forward", contextLabels: true, activeOrdinal: 2, seed: 7 });
  const back = side({ direction: "forward", contextLabels: true, activeOrdinal: 2, seed: 7, back: true });
  assert.equal(boxesOf(front.svg).length, STRUCTURES.length);
  assert.equal(boxesOf(back.svg).length, STRUCTURES.length);
  // the tested structure is still the only one hidden behind the prompt text
  assert.ok(boxesOf(front.svg).some((b) => b.text === "?"));
  assert.ok(!boxesOf(back.svg).some((b) => b.text === "?"));
});

// ---- the reverse question side must never pinpoint the answer ---------------

test("no dot configuration ever pinpoints a reverse card's answer", () => {
  // A LONE dot on a "locate it" question side gives the answer away. Either every
  // structure is dotted (which says nothing) or none is.
  const configs = [
    { showDecoyDots: true, showTargetDot: true },
    { showDecoyDots: true, showTargetDot: false },
    { showDecoyDots: false, showTargetDot: true },
    { showDecoyDots: false, showTargetDot: false },
  ];
  for (const config of configs) {
    for (const activeOrdinal of [1, 2, 3, 4]) {
      const card = buildCard({
        structures: STRUCTURES,
        direction: "reverse",
        activeOrdinal,
        seed: 42,
        config,
      });
      card.render(false);
      const dots = dotsOf(card.svg).length;
      assert.ok(
        dots === 0 || dots === STRUCTURES.length,
        `${JSON.stringify(config)} drew ${dots} dot(s) on a reverse question side`,
      );
      assert.equal(arrowsOf(card.svg), 0, "reverse question side draws no arrow");
    }
  }
});

// ---- long labels stay on screen ---------------------------------------------

test("a long label wraps and its box stays within the image", () => {
  const long = "inferior mesenteric artery and its sigmoid branches";
  const structures = [{ ord: 1, x: 0.12, y: 0.5, label: long }]; // near the left edge
  for (const stage of [{ width: 360, height: 640 }, { width: 500, height: 350 }, { width: 800, height: 600 }]) {
    const front = buildCard({ structures, direction: "forward", seed: 5, stage, config: DOTS_ON });
    front.render(false);
    const back = buildCard({ structures, direction: "forward", seed: 5, stage, back: true, config: DOTS_ON });
    back.render(false);

    const box = boxesOf(back.svg)[0];
    assert.ok(box.w <= stage.width + 0.5, `box (${box.w}px) wider than the image (${stage.width}px)`);
    assert.ok(
      box.cx - box.w / 2 >= -0.5 && box.cx + box.w / 2 <= stage.width + 0.5,
      `box runs off the image: [${box.cx - box.w / 2}, ${box.cx + box.w / 2}] of ${stage.width}`,
    );
    assert.equal(box.text.replace(/\s+/g, " "), long, "wrapping must not lose or reorder words");
    if (stage.width <= 400) assert.ok(box.lines >= 2, "a narrow screen forces the label to wrap");

    const frontBox = boxesOf(front.svg)[0];
    assert.ok(
      Math.abs(frontBox.cx - box.cx) < 1e-6 && Math.abs(frontBox.cy - box.cy) < 1e-6,
      "wrapping must not move the box centre between the sides",
    );
  }
});
