"use strict";

// End-to-end tests of the reviewer's multi-card `render()`: what it actually
// DRAWS. The pure-helper tests in render.test.js cover the maths; these drive
// the whole renderer against a headless card (see dom.js) and assert the card a
// learner would see (prompt text, arrow, dots, the native type-answer box) and
// above all that the FRONT and BACK agree.
//
// Every test pre-seeds session storage and renders with `mint=false`, so the
// layout and the "both"-direction coin are reproducible (a minting render would
// draw a fresh random seed and make these tests flaky).

const test = require("node:test");
const assert = require("node:assert/strict");
const { buildCard, boxesOf, dotsOf, arrowsOf, SEED_KEY } = require("./dom.js");

const STRUCTURES = [
  { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
  { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
  { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
  { ord: 4, x: 0.35, y: 0.6, label: "Pulmonary trunk" },
];
const SEEDS = [1, 7, 12, 23, 99, 1234, 65535, 2654435761];
const DOTS_ON = { showDecoyDots: true, showTargetDot: true };
const STAGE = { width: 800, height: 600 };
//: What a prompt box shows in place of the answer, from config.json.
const PROMPT = "?";

/** Where a structure projects onto the overlay. */
const project = (s) => ({ x: s.x * STAGE.width, y: s.y * STAGE.height });

/** Whether (x, y) lies on the outline of `box`. */
function onBorder(x, y, box) {
  const onVertical =
    near(Math.abs(x - box.cx), box.w / 2, 1e-6) &&
    Math.abs(y - box.cy) <= box.h / 2 + 1e-6;
  const onHorizontal =
    near(Math.abs(y - box.cy), box.h / 2, 1e-6) &&
    Math.abs(x - box.cx) <= box.w / 2 + 1e-6;
  return onVertical || onHorizontal;
}

/**
 * Assert an arrow ends on `structure` and leaves the border of the box reading
 * `expectedText`.
 *
 * The text matters as much as the geometry: every check below is positional, and
 * a card that draws each arrow correctly while printing the wrong name on every
 * box satisfies all of them. On a forward question side the active box shows the
 * prompt, so the caller says which text to expect rather than assuming the label.
 */
function assertArrowPointsAt(svg, structure, expectedText, message) {
  const target = project(structure);
  const arrows = arrowsOf(svg);
  assert.ok(arrows.length >= 1, `${message}: no arrow drawn`);
  const hit = arrows.find(
    (a) => near(a.x2, target.x, 1e-6) && near(a.y2, target.y, 1e-6),
  );
  assert.ok(
    hit,
    `${message}: no arrow ends at (${target.x}, ${target.y}); got ` +
      JSON.stringify(arrows.map((a) => [a.x2, a.y2])),
  );

  // The box this arrow actually leaves, found by its tail. Taking the first box
  // with any text would be structure 0's on every multi-box card, so the checks
  // below would measure a box and an arrow that are not the pair under test and
  // could pass while the real pair was wrong.
  const boxes = boxesOf(svg);
  const box = boxes.find((b) => onBorder(hit.x1, hit.y1, b));
  assert.ok(
    box,
    `${message}: arrow starts at (${hit.x1}, ${hit.y1}), not on the border of ` +
      `any box; boxes at ${JSON.stringify(boxes.map((b) => [b.cx, b.cy]))}`,
  );
  assert.equal(
    box.text,
    expectedText,
    `${message}: the arrow to this structure leaves the box reading ` +
      `${JSON.stringify(box.text)}, not ${JSON.stringify(expectedText)}`,
  );

  // The tail is where the centre-to-target segment crosses the box outline, so
  // it is collinear with centre and target, on the same side as the target, and
  // no further off than the target is. Collinearity alone accepts an arrow drawn
  // backwards out of the far side of the box and hidden underneath it, which is
  // exactly what happens when the target falls inside the box.
  const toTarget = { x: target.x - box.cx, y: target.y - box.cy };
  const toTail = { x: hit.x1 - box.cx, y: hit.y1 - box.cy };
  const span = Math.hypot(toTarget.x, toTarget.y);
  assert.ok(span > 1e-6, `${message}: the box centre sits on top of the target`);

  const cross = toTail.x * toTarget.y - toTail.y * toTarget.x;
  assert.ok(
    Math.abs(cross) / span < 1e-6,
    `${message}: arrow tail is not on the line from the box centre to the target`,
  );
  assert.ok(
    toTail.x * toTarget.x + toTail.y * toTarget.y > 0,
    `${message}: the arrow leaves the box on the side away from the target`,
  );
  assert.ok(
    Math.hypot(toTail.x, toTail.y) <= span + 1e-6,
    `${message}: the arrow starts past the target, so it is drawn backwards`,
  );
}

const near = (a, b, tol) => Math.abs(a - b) <= tol;

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
      assert.equal(
        boxesOf(front.svg)[0].strayText,
        "",
        "the label used to size the box must not be left rendered beside the prompt",
      );
      assertArrowPointsAt(front.svg, STRUCTURES[activeOrdinal - 1], PROMPT,
        "forward question side");
      assert.equal(boxesOf(back.svg)[0].text, label, "answer side reveals the label");
      assertArrowPointsAt(back.svg, STRUCTURES[activeOrdinal - 1], label,
        "forward answer side");
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
    assert.equal(
        arrowsOf(front.svg).length,
        0,
        "reverse question side must not point at the answer",
    );
    assert.equal(boxesOf(back.svg)[0].text, label);
    assertArrowPointsAt(back.svg, STRUCTURES[activeOrdinal - 1],
      STRUCTURES[activeOrdinal - 1].label, "reverse answer side");
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
      const dots = dotsOf(card.svg);
      // Either every structure is dotted (no information) or none is. One dot
      // would mark the answer. Asserted per-configuration rather than as a
      // disjunction, so "draw nothing, ever" cannot satisfy it.
      const expected = config.showDecoyDots ? STRUCTURES.length : 0;
      assert.equal(
        dots.length,
        expected,
        `${JSON.stringify(config)} drew ${dots.length} dot(s) on a reverse question side`,
      );
      for (const structure of config.showDecoyDots ? STRUCTURES : []) {
        const at = project(structure);
        assert.ok(
          dots.some((d) => near(d.x, at.x, 1e-6) && near(d.y, at.y, 1e-6)),
          `no dot on ${structure.label}`,
        );
      }
      assert.equal(arrowsOf(card.svg).length, 0, "reverse question side draws no arrow");
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

// ---- randomisation ----------------------------------------------------------
//
// Everything above pins layout as a function of the seed. None of it pins that
// the function is non-constant, or that the seed changes between reviews. A
// build that puts every box in the same corner forever satisfies all of it, and
// that build has no reason to exist.

test("box placement varies with the seed", () => {
  const centres = SEEDS.map((seed) => {
    const card = side({ direction: "forward", activeOrdinal: 1, seed });
    const box = boxesOf(card.svg)[0];
    return `${box.cx.toFixed(3)},${box.cy.toFixed(3)}`;
  });

  const distinct = new Set(centres);
  assert.ok(
    distinct.size >= SEEDS.length - 1,
    `${SEEDS.length} seeds produced only ${distinct.size} distinct positions: ` +
      JSON.stringify([...distinct]),
  );
});

test("box placement varies across the stage, not within one corner", () => {
  // A fallback-only implementation still moves the box, but only between the
  // four margin corners. Spread is what makes position uninformative.
  const xs = [];
  const ys = [];
  for (const seed of SEEDS) {
    const box = boxesOf(side({ direction: "forward", activeOrdinal: 1, seed }).svg)[0];
    xs.push(box.cx);
    ys.push(box.cy);
  }
  const spread = (v) => Math.max(...v) - Math.min(...v);
  assert.ok(spread(xs) > STAGE.width * 0.2, `x spread ${spread(xs)} is too narrow`);
  assert.ok(spread(ys) > STAGE.height * 0.2, `y spread ${spread(ys)} is too narrow`);
  assert.ok(new Set(xs.map((v) => v.toFixed(3))).size > 4, "x takes more than corner values");
});

test("a fresh question view mints a seed and stores it", () => {
  const card = buildCard({ structures: STRUCTURES, config: DOTS_ON });
  assert.equal(card.store[SEED_KEY], undefined, "precondition: nothing stored yet");

  card.render(true);

  const stored = card.store[SEED_KEY];
  assert.ok(stored !== undefined, "a new question view must mint a seed");
  assert.ok(Number.isFinite(Number(stored)), `stored seed ${stored} is not a number`);
});

test("minted seeds differ between reviews", () => {
  const minted = new Set();
  for (let i = 0; i < 12; i += 1) {
    const card = buildCard({ structures: STRUCTURES, config: DOTS_ON });
    card.render(true);
    minted.add(card.store[SEED_KEY]);
  }
  assert.ok(minted.size > 1, `12 reviews minted ${minted.size} distinct seed(s)`);
});

test("re-rendering the same view reuses the stored seed", () => {
  // A repaint (resize, a second bootstrap pass) must not move the box, or the
  // answer would land somewhere the question never was.
  const card = buildCard({ structures: STRUCTURES, config: DOTS_ON });
  card.render(true);
  const first = boxesOf(card.svg)[0];
  const seed = card.store[SEED_KEY];

  card.render(false);
  const second = boxesOf(card.svg)[0];

  assert.equal(card.store[SEED_KEY], seed, "the seed must not be re-minted");
  assert.ok(near(second.cx, first.cx, 1e-9) && near(second.cy, first.cy, 1e-9),
    `box moved from (${first.cx}, ${first.cy}) to (${second.cx}, ${second.cy})`);
});

test("a forward card with decoys off dots only the active structure", () => {
  // The lone dot marks where the arrow lands. Nothing else may be dotted, or
  // the arrow would be redundant, and it must be drawn, or the arrow points at
  // nothing the learner can see.
  for (const activeOrdinal of [1, 2, 3, 4]) {
    const card = side({
      direction: "forward",
      activeOrdinal,
      seed: 42,
      config: { showDecoyDots: false, showTargetDot: true },
    });
    const dots = dotsOf(card.svg);
    const at = project(STRUCTURES[activeOrdinal - 1]);
    assert.equal(dots.length, 1, `ordinal ${activeOrdinal} drew ${dots.length} dots`);
    assert.ok(near(dots[0].x, at.x, 1e-6) && near(dots[0].y, at.y, 1e-6),
      `the dot is not on structure ${activeOrdinal}`);
  }
});

test("showTargetDot off draws no dot at all", () => {
  const card = side({
    direction: "forward",
    activeOrdinal: 1,
    seed: 42,
    config: { showDecoyDots: false, showTargetDot: false },
  });
  assert.equal(dotsOf(card.svg).length, 0);
});

test("a legacy bare-array payload still renders", () => {
  // v1 notes stored the structures as a bare JSON array with no envelope. They
  // are still in people's collections and must keep rendering.
  const card = buildCard({ structures: STRUCTURES, config: DOTS_ON, legacyPayload: true });
  card.render(false);
  assert.equal(boxesOf(card.svg).length, 1, "a v1 note renders its prompt box");
  assert.equal(dotsOf(card.svg).length, STRUCTURES.length, "and its dots");
});

test("a repaint keeps its place when session storage is unavailable", () => {
  // getItem throws rather than returning null, so the stored-seed path is gone.
  // The in-memory mirror is what stops a resize repaint re-minting and moving
  // the box mid-review.
  const card = buildCard({ structures: STRUCTURES, config: DOTS_ON, storage: "unavailable" });
  card.render(true);
  const first = boxesOf(card.svg)[0];

  card.render(false); // the resize path
  const second = boxesOf(card.svg)[0];

  assert.ok(near(second.cx, first.cx, 1e-9) && near(second.cy, first.cy, 1e-9),
    `box moved from (${first.cx}, ${first.cy}) to (${second.cx}, ${second.cy})`);
});

test("every structure on a context-labels card is pointed at by its own box", () => {
  // Four boxes and four arrows share one SVG here, which is what the helper's
  // box lookup has to get right: taking the first labelled box would measure
  // structure 1's every time, so an arrow paired with the wrong box would pass
  // unnoticed. This is also the only configuration where that can happen, since
  // every other test in this file draws a single box.
  for (const activeOrdinal of [1, 2, 3, 4]) {
    for (const back of [false, true]) {
      const card = side({ direction: "forward", activeOrdinal, back, seed: 7,
                          contextLabels: true });
      assert.equal(boxesOf(card.svg).length, STRUCTURES.length,
        `ordinal ${activeOrdinal}: a context-labels card labels every structure`);
      for (const structure of STRUCTURES) {
        // The active structure is the one being asked about, so on the question
        // side its box shows the prompt; every other box names its own structure.
        const expected =
          !back && structure.ord === activeOrdinal ? PROMPT : structure.label;
        assertArrowPointsAt(card.svg, structure, expected,
          `ordinal ${activeOrdinal}, back=${back}, structure ${structure.ord}`);
      }
    }
  }
});

test("a repaint keeps its place when session storage is full", () => {
  // The other degraded store: setItem throws, but getItem returns null rather
  // than throwing. readSeed() only reaches the in-memory mirror here if it
  // treats a null result as a miss; handling the throw alone would send this
  // path off to mint a fresh seed and move the box.
  const card = buildCard({ structures: STRUCTURES, config: DOTS_ON, storage: "quota" });
  card.render(true);
  const first = boxesOf(card.svg)[0];

  card.render(false); // the resize path
  const second = boxesOf(card.svg)[0];

  assert.ok(near(second.cx, first.cx, 1e-9) && near(second.cy, first.cy, 1e-9),
    `box moved from (${first.cx}, ${first.cy}) to (${second.cx}, ${second.cy})`);
});
