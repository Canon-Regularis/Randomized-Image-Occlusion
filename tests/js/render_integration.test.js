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
  // Which border the arrow leaves from depends on where the target is.
  const inside =
    Math.abs(toTarget.x) <= box.w / 2 + 1e-6 && Math.abs(toTarget.y) <= box.h / 2 + 1e-6;
  const dot = toTail.x * toTarget.x + toTail.y * toTarget.y;
  if (inside) {
    // The target sits underneath its own box. Leaving from the border toward it
    // would put the tail PAST the target and draw the line back into the box,
    // where it is hidden; stopping at the target draws nothing at all. So the
    // arrow leaves from the opposite border and crosses to the target.
    assert.ok(dot < 0,
      `${message}: the target is inside its own box, so the arrow must leave ` +
      "from the opposite border or it is drawn underneath it");
  } else {
    assert.ok(dot > 0,
      `${message}: the arrow leaves the box on the side away from the target`);
    assert.ok(Math.hypot(toTail.x, toTail.y) <= span + 1e-6,
      `${message}: the arrow starts past the target, so it is drawn backwards`);
  }

  // Either way it has to be visible. "Not past the target" is satisfied by a
  // zero-length line, by the box centre, and by the target itself.
  const length = Math.hypot(hit.x2 - hit.x1, hit.y2 - hit.y1);
  assert.ok(length > 1,
    `${message}: the arrow is ${length.toFixed(3)}px long, so nothing is drawn`);
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

// ---- the bootstrap ----------------------------------------------------------
//
// render.js calls run() as it loads, and run() does everything through
// setTimeout: the once-per-show guard, the bounded retry for an image that is
// not laid out yet, and the resize re-render. Every other test in this file
// calls render(mint) directly with timers noop'd, so none of that was ever
// executed. `timers: "manual"` queues the callbacks for flushTimers() to step.

const ONE = [{ ord: 1, x: 0.4, y: 0.4, label: "Aorta" }];

test("the bootstrap renders the card and mints a seed", () => {
  const card = buildCard({ structures: ONE, timers: "manual", config: DOTS_ON });
  assert.equal(boxesOf(card.svg).length, 0, "nothing is drawn before the clock runs");

  card.flushTimers();

  assert.equal(boxesOf(card.svg).length, 1, "the bootstrap never rendered");
  assert.ok(SEED_KEY in card.store, "a question view must mint and store a seed");
});

test("the safety net fires only after load and error have had their chance", () => {
  // The 250 ms net is for clients where neither event ever arrives, so it has
  // to come last. The mock used to discard the delay, which made it
  // indistinguishable from the 0 ms post-render and the 16 ms retry: raising
  // 250 to 25 seconds -- a blank card for the first half-minute of every
  // review -- left every bootstrap test green.
  const card = buildCard({ structures: ONE, timers: "manual", config: DOTS_ON });
  assert.deepEqual(card.timerDelays(), [250],
    "a still-loading image should arm the safety net and nothing else");

  assert.equal(card.advanceTimers(249), 0, "the safety net fired early");
  assert.equal(boxesOf(card.svg).length, 0, "nothing is drawn before it fires");

  card.advanceTimers(1);
  assert.equal(boxesOf(card.svg).length, 1, "the safety net never fired");
});

test("the image's load handlers do not accumulate across cards", () => {
  // Anki reuses ONE webview for every card, so run() is called again for each
  // show against the same <img>. load and error are registered `{once: true}`
  // precisely so the browser detaches them; without it every card reviewed
  // leaves another stale closure attached, and one load event then re-enters
  // every show of the session.
  const card = buildCard({ structures: ONE, timers: "manual", config: DOTS_ON });
  for (let show = 0; show < 5; show += 1) {
    card.img.dispatch("load");
    card.flushTimers();
    card.run(); // the next card, same webview
  }
  card.img.dispatch("load");

  const attached = (card.img._handlers.load || []).length;
  assert.ok(attached <= 1,
    `${attached} load handlers are still attached after six shows`);
});

test("the bootstrap renders exactly once per show", () => {
  // load, error and a safety-net timer can all fire. Without the `ran` guard a
  // second pass would mint a fresh seed and the box would jump mid-review.
  const card = buildCard({ structures: ONE, timers: "manual", config: DOTS_ON });
  card.flushTimers();
  const first = boxesOf(card.svg)[0];
  const seed = card.store[SEED_KEY];

  card.img.dispatch("load"); // a late load event for the same show
  card.flushTimers();

  assert.equal(boxesOf(card.svg).length, 1, "the card was drawn twice over");
  const second = boxesOf(card.svg)[0];
  assert.ok(near(second.cx, first.cx, 1e-9) && near(second.cy, first.cy, 1e-9),
    "the box moved on a second bootstrap pass");
  assert.equal(card.store[SEED_KEY], seed, "the seed was re-minted");
});

test("an image with no size yet is retried, not abandoned", () => {
  // render() bails on a zero-sized image saying a later pass will retry, but the
  // once-per-show guard means there is no later pass: before this, only a resize
  // ever recovered such a card and it otherwise stayed blank for the review.
  const card = buildCard({
    structures: ONE, timers: "manual", stage: { width: 0, height: 0 }, config: DOTS_ON,
  });
  card.flushTimers(5);
  assert.equal(boxesOf(card.svg).length, 0, "nothing can be drawn without a size");
  assert.ok(card.pendingTimers() > 0, "the retry gave up while the image had no size");

  card.img._rect = { width: 800, height: 600, left: 0, top: 0 };
  card.flushTimers();

  assert.equal(boxesOf(card.svg).length, 1, "the card never recovered once laid out");
});

test("a load event while the image has no size does not waste the render", () => {
  // load/error call go(), and go() arms a once-per-show guard. Arming it while
  // there is still nothing to measure would leave the retry with nothing to do
  // and the card blank for the whole review.
  const card = buildCard({
    structures: ONE, timers: "manual", stage: { width: 0, height: 0 }, config: DOTS_ON,
  });
  card.img.dispatch("load"); // fires while the image is still 0x0
  card.flushTimers(3); // a few retry rounds, well short of the 30-attempt budget
  assert.equal(boxesOf(card.svg).length, 0, "nothing can be drawn without a size");

  card.img._rect = { width: 800, height: 600, left: 0, top: 0 };
  card.flushTimers();
  assert.equal(boxesOf(card.svg).length, 1,
    "the early load event burned the once-per-show guard");
});

test("an image that is still loading keeps its listeners and its resize binding", () => {
  // A zero-sized <img> is also what a still-loading image looks like. Returning
  // early on "no size" skipped the load/error listeners AND the resize binding
  // below them, which took a slow load from "blank until the next resize" to
  // "blank for the rest of the review" with no way back.
  const card = buildCard({
    structures: ONE, timers: "manual", stage: { width: 0, height: 0 }, config: DOTS_ON,
  });
  assert.equal(card.listenerCount("resize"), 1,
    "the resize binding was skipped while the image had no size");

  card.flushTimers(500); // let the bounded retry give up
  assert.equal(boxesOf(card.svg).length, 0);

  card.img._rect = { width: 800, height: 600, left: 0, top: 0 };
  card.fire("resize");
  card.flushTimers();
  assert.equal(boxesOf(card.svg).length, 1,
    "a later resize could not rescue the card");
});

test("a card with no image element yet is retried, not abandoned", () => {
  // A parse-mode client can run the script before the card HTML is in the DOM,
  // so there is no <img> to find at all. That is a different miss from an image
  // that exists but has no size, and it has its own retry; splitting the two
  // guards apart left this one with nothing exercising it.
  const card = buildCard({
    structures: ONE, timers: "manual", detachedImage: true, config: DOTS_ON,
  });
  card.flushTimers(5);
  assert.equal(boxesOf(card.svg).length, 0, "there is nothing to draw on yet");
  assert.ok(card.pendingTimers() > 0, "the retry gave up before the image existed");

  card.attachImage();
  card.flushTimers();

  assert.equal(boxesOf(card.svg).length, 1, "the card never recovered once the image arrived");
});

test("the retry for a card whose image never arrives is bounded", () => {
  // A note with an empty Image field has no <img> and never will, and must not
  // spin setTimeout forever.
  const card = buildCard({
    structures: ONE, timers: "manual", detachedImage: true, config: DOTS_ON,
  });
  const ran = card.flushTimers(500);
  assert.ok(ran < 500, `the retry ran ${ran} times without stopping`);
  assert.equal(card.pendingTimers(), 0, "the retry is still armed after giving up");
});

test("an image that loads only after the safety net has fired still renders", () => {
  // The guard used to be per-invocation: the retry re-entered run(), so a slow
  // image built up ~30 guards and ~30 safety nets, and every net fired while
  // there was still nothing to measure -- spending all of them. When `load`
  // finally landed, every go() returned at its first line and the card stayed
  // blank for the whole review. Only a resize ever rescued it, which is the one
  // escape hatch the older test happened to use.
  const card = buildCard({
    structures: ONE, timers: "manual", stage: { width: 0, height: 0 }, config: DOTS_ON,
  });
  card.flushTimers(2000); // every net fires, and the bounded watch gives up
  assert.equal(boxesOf(card.svg).length, 0, "nothing can be drawn at 0x0");

  // The ordinary browser sequence for a slow image. No resize on a fresh page.
  card.img._rect = { width: 800, height: 600, left: 0, top: 0 };
  card.img.dispatch("load");
  card.flushTimers(2000);

  assert.equal(boxesOf(card.svg).length, 1,
    "the card never rendered after its image finished loading");
});

test("a load that arrives before layout is not wasted", () => {
  // `load` can fire before the element has been given a box. That must not
  // spend the guard, and it must not be the end of the matter either: the
  // trigger starts its own bounded watch, so the card paints as soon as there
  // is something to measure.
  const card = buildCard({
    structures: ONE, timers: "manual", stage: { width: 0, height: 0 }, config: DOTS_ON,
  });
  card.img.dispatch("load"); // still 0x0
  card.flushTimers(3);
  assert.equal(boxesOf(card.svg).length, 0);

  card.img._rect = { width: 800, height: 600, left: 0, top: 0 };
  card.flushTimers(2000);
  assert.equal(boxesOf(card.svg).length, 1,
    "the early load event spent the guard after all");
});

test("the arrowhead orients along the line it caps", () => {
  // "auto-start-reverse" is SVG2. Older phone WebViews drop the whole attribute
  // and fall back to orient=0, which points every arrowhead due east regardless
  // of where its arrow goes. The marker is only ever used as marker-end, so
  // plain "auto" is equivalent wherever both are understood.
  const card = buildCard({ structures: ONE, config: DOTS_ON });
  card.render(false);
  const markers = [];
  (function walk(node) {
    for (const child of node.childNodes) {
      if (child.tagName === "marker") markers.push(child);
      walk(child);
    }
  })(card.svg);
  assert.equal(markers.length, 1, "expected exactly one arrowhead marker");
  assert.equal(markers[0].attributes.orient, "auto");
});

test("the retry for an image that never appears is bounded", () => {
  // A note with an empty Image field must not spin setTimeout forever.
  const card = buildCard({
    structures: ONE, timers: "manual", stage: { width: 0, height: 0 }, config: DOTS_ON,
  });
  const ran = card.flushTimers(500);
  assert.ok(ran < 500, `the retry ran ${ran} times without stopping`);
  assert.equal(card.pendingTimers(), 0, "the retry is still armed after giving up");
});

test("a resize repaints without re-randomising", () => {
  const card = buildCard({ structures: ONE, timers: "manual", config: DOTS_ON });
  card.flushTimers();
  const before = boxesOf(card.svg)[0];
  const seed = card.store[SEED_KEY];

  card.fire("resize");
  card.flushTimers();

  const after = boxesOf(card.svg)[0];
  assert.ok(near(after.cx, before.cx, 1e-9) && near(after.cy, before.cy, 1e-9),
    "the box moved on resize, so the layout was re-randomised mid-review");
  assert.equal(card.store[SEED_KEY], seed, "the resize re-minted the seed");
});

test("the resize listener is bound once, not once per card shown", () => {
  // The guard is on `window`, and Anki's reviewer reuses ONE webview across
  // cards, so a leak here accumulates a listener per card reviewed and every
  // resize eventually triggers a storm of repaints.
  const card = buildCard({ structures: ONE, timers: "manual", config: DOTS_ON });
  card.flushTimers();
  assert.equal(card.listenerCount("resize"), 1);

  for (let show = 0; show < 4; show += 1) {
    card.run(); // the next card, same webview
    card.flushTimers();
  }
  assert.equal(card.listenerCount("resize"), 1,
    "a listener was added per card shown");
});

test("a new question view re-randomises rather than reusing the stored seed", () => {
  // The whole premise: the box must land somewhere new every review. A card
  // arrives with the PREVIOUS card's seed still in session storage, so the
  // bootstrap has to mint over it; reusing it would pin the layout for good.
  const card = buildCard({ structures: ONE, timers: "manual", seed: 4242, config: DOTS_ON });
  assert.equal(card.store[SEED_KEY], "4242", "the fixture seed should be pre-stored");

  card.flushTimers();

  assert.notEqual(card.store[SEED_KEY], "4242",
    "the question view reused the stored seed instead of minting a new one");
});

// ---- the elimination leak ---------------------------------------------------

/**
 * A dot that nothing points at can be identified by elimination. If exactly one
 * dot is un-arrowed and it sits on the structure being asked about, the question
 * side has answered itself.
 *
 * This is the property the whole add-on exists to provide, so it is asserted
 * over every configuration rather than over the cases that happened to be found
 * broken. Reverse + context labels leaked exactly this way, undetected, because
 * no test ever rendered that pair.
 */
const rawArrowCount = (svg) =>
  svg.childNodes.filter((n) => n.tagName === "line" && n._classes.has("ro-arrow")).length;

function assertNoEliminationLeak(card, structure, message) {
  const dots = dotsOf(card.svg);
  const arrows = arrowsOf(card.svg);
  // arrowsOf drops lines too short to see. If one was dropped here, the
  // learner is looking at an un-arrowed dot while everything below counts it
  // as arrowed -- the leak would be real and this check would miss it.
  assert.equal(arrows.length, rawArrowCount(card.svg),
    `${message}: an arrow was drawn too short to be visible`);
  const target = project(structure);
  const unarrowed = dots.filter(
    (d) => !arrows.some((a) => near(a.x2, d.x, 1e-6) && near(a.y2, d.y, 1e-6)),
  );
  const identifies =
    unarrowed.length === 1 &&
    near(unarrowed[0].x, target.x, 1e-6) &&
    near(unarrowed[0].y, target.y, 1e-6);
  assert.ok(
    !identifies,
    `${message}: exactly one dot has no arrow pointing at it and it is the ` +
      `answer at (${target.x}, ${target.y}), so the question side can be ` +
      `solved by elimination`,
  );
}

test("no question side identifies its own answer by elimination", () => {
  for (const contextLabels of [false, true]) {
    for (const direction of ["forward", "reverse", "both"]) {
      for (const seed of [1, 7, 42, 1234]) {
        for (const activeOrdinal of [1, 2, 3, 4]) {
          const card = side({ direction, contextLabels, activeOrdinal, seed });
          assertNoEliminationLeak(
            card,
            STRUCTURES[activeOrdinal - 1],
            `${direction}, contextLabels=${contextLabels}, ordinal ` +
              `${activeOrdinal}, seed ${seed}`,
          );
        }
      }
    }
  }
});

test("an arrow never overshoots a target inside its own box", () => {
  // A long label on a small stage puts the target inside the box that points at
  // it. boxBorderToward scaled the direction vector out to the border, and for
  // an interior target that scale exceeds 1, so the tail landed BEYOND the
  // target and the arrow was drawn backwards, hidden under the box.
  const structures = [{ ord: 1, x: 0.5, y: 0.3, label: "Superior mesenteric artery" }];
  for (const seed of [1, 2, 3, 7, 12, 42, 99, 1234]) {
    const card = buildCard({
      structures, seed, stage: { width: 200, height: 150 },
      config: { showDecoyDots: false, showTargetDot: true },
    });
    card.render(false);
    const box = boxesOf(card.svg)[0];
    const arrow = arrowsOf(card.svg)[0];
    const target = { x: 0.5 * 200, y: 0.3 * 150 };
    const toTarget = Math.hypot(target.x - box.cx, target.y - box.cy);
    const toTail = Math.hypot(arrow.x1 - box.cx, arrow.y1 - box.cy);
    const inside =
      Math.abs(target.x - box.cx) <= box.w / 2 + 1e-6 &&
      Math.abs(target.y - box.cy) <= box.h / 2 + 1e-6;
    if (inside) {
      // Leaves from the opposite border, so it crosses the box to reach the
      // target rather than being drawn underneath it.
      const dot = (arrow.x1 - box.cx) * (target.x - box.cx) +
        (arrow.y1 - box.cy) * (target.y - box.cy);
      assert.ok(dot < 0,
        `seed ${seed}: the target is inside its own box but the arrow leaves ` +
        "from the near border, so it is hidden underneath it");
    } else {
      assert.ok(toTail <= toTarget + 1e-6,
        `seed ${seed}: the arrow starts ${toTail.toFixed(1)}px from the box centre ` +
        `but the target is only ${toTarget.toFixed(1)}px away, so it points backwards`);
    }
    assert.ok(onBorder(arrow.x1, arrow.y1, box),
      `seed ${seed}: the arrow starts at (${arrow.x1.toFixed(1)}, ` +
      `${arrow.y1.toFixed(1)}), which is not on the box outline`);
    const length = Math.hypot(arrow.x2 - arrow.x1, arrow.y2 - arrow.y1);
    assert.ok(length > 1,
      `seed ${seed}: the arrow is ${length.toFixed(3)}px long, so nothing is drawn`);
  }
});

test("a prompt wider than the label keeps the box on the image", () => {
  // The centre is clamped using the LABEL's width so the front and back agree,
  // but the rect is sized from what is actually shown. prompt_text is
  // user-configurable, so a prompt wider than the label overflowed the clamp.
  const structures = [{ ord: 1, x: 0.06, y: 0.5, label: "A" }];
  const config = { promptText: "Which structure is indicated here?", showDecoyDots: false };
  for (const seed of [2, 3, 12, 99]) {
    const front = buildCard({ structures, seed, config });
    const back = buildCard({ structures, seed, back: true, config });
    front.render(false);
    back.render(false);
    const box = boxesOf(front.svg)[0];
    assert.ok(box.cx - box.w / 2 >= -1e-6 && box.cx + box.w / 2 <= STAGE.width + 1e-6,
      `seed ${seed}: the question box spans [${(box.cx - box.w / 2).toFixed(1)}, ` +
      `${(box.cx + box.w / 2).toFixed(1)}] outside 0..${STAGE.width}`);
    // The widened clamp must apply to both sides, or fixing the overflow would
    // make the box jump when the card is flipped.
    const other = boxesOf(back.svg)[0];
    assert.ok(near(box.cx, other.cx, 1e-6) && near(box.cy, other.cy, 1e-6),
      `seed ${seed}: the box moved between question and answer`);
  }
});

test("every card of a note asks a different question", () => {
  // The elimination check above fires only when exactly ONE dot is un-arrowed,
  // so it is satisfied by removing every arrow -- which is how a "fix" that made
  // all N cards of a reverse context note render identically passed it. A
  // question side that cannot identify its own target is not safe, it is broken,
  // so the two properties have to be asserted together.
  const snapshot = (card) =>
    JSON.stringify({
      boxes: boxesOf(card.svg).map((b) => [b.text, Math.round(b.cx), Math.round(b.cy)]),
      dots: dotsOf(card.svg).map((d) => [Math.round(d.x), Math.round(d.y)]),
      arrows: arrowsOf(card.svg).map((a) => [
        Math.round(a.x1), Math.round(a.y1), Math.round(a.x2), Math.round(a.y2),
      ]),
    });

  for (const contextLabels of [false, true]) {
    for (const direction of ["forward", "reverse"]) {
      const seen = new Map();
      for (const activeOrdinal of [1, 2, 3, 4]) {
        const card = side({ direction, contextLabels, activeOrdinal, seed: 7 });
        const shot = snapshot(card);
        const clash = seen.get(shot);
        assert.equal(clash, undefined,
          `${direction}, contextLabels=${contextLabels}: ordinals ${clash} and ` +
          `${activeOrdinal} render an identical question side, so neither card ` +
          "says which structure it is asking about");
        seen.set(shot, activeOrdinal);
      }
    }
  }
});

test("every context label is joined to its own structure", () => {
  // The context labels are only useful if you can tell which structure each one
  // names. They keep their arrows on every side, including a reverse question
  // side where the ACTIVE box withholds its own.
  for (const direction of ["forward", "reverse"]) {
    for (const back of [false, true]) {
      const card = side({ direction, back, contextLabels: true, activeOrdinal: 2, seed: 7 });
      const arrows = arrowsOf(card.svg);
      const expected = direction === "reverse" && !back
        ? STRUCTURES.length - 1 // the active box withholds its arrow
        : STRUCTURES.length;
      assert.equal(arrows.length, expected,
        `${direction}, back=${back}: expected ${expected} arrows, got ${arrows.length}`);
      for (const structure of STRUCTURES) {
        if (direction === "reverse" && !back && structure.ord === 2) continue;
        const at = project(structure);
        assert.ok(arrows.some((a) => near(a.x2, at.x, 1e-6) && near(a.y2, at.y, 1e-6)),
          `${direction}, back=${back}: nothing points at ${structure.label}`);
      }
    }
  }
});

test("a long prompt does not squeeze the boxes that never show it", () => {
  // Only a box that flips between the prompt and its label needs clamping for
  // both. Clamping the context labels and the answer key for a prompt they can
  // never display confined them to a band around the centre and broke the
  // separation placeCenters guarantees.
  const short = { showDecoyDots: true, promptText: "?" };
  const long = { showDecoyDots: true, promptText: "Which structure is indicated here?" };
  const spread = (config) => {
    const card = side({ direction: "forward", contextLabels: true, activeOrdinal: 1,
                        seed: 7, config });
    const others = boxesOf(card.svg).filter((b) => b.text !== "?");
    const xs = others.map((b) => b.cx);
    return Math.max(...xs) - Math.min(...xs);
  };
  assert.ok(near(spread(long), spread(short), 1e-6),
    `the context labels spread ${spread(long).toFixed(1)}px with a long prompt but ` +
    `${spread(short).toFixed(1)}px with a short one, so they were clamped for a ` +
    "prompt they never show");
});

test("a tall prompt keeps its box on the image", () => {
  // The clamp is sized for the LABEL, so a prompt that wraps to more lines than
  // the label is taller than what the centre was clamped for -- and the box
  // hangs off the top or bottom of the picture, where .ro-overlay's
  // overflow: visible paints it over the rest of the card.
  const stage = { width: 360, height: 270 };
  const promptText =
    "which of the labelled structures is the arrow pointing at right now?";
  for (let seed = 1; seed <= 30; seed++) {
    const card = side({
      structures: [{ ord: 1, x: 0.5, y: 0.5, label: "Aorta" }],
      stage, seed, direction: "forward", activeOrdinal: 1,
      config: { showDecoyDots: true, showTargetDot: true, promptText },
    });
    const box = boxesOf(card.svg)[0];
    const top = box.cy - box.h / 2;
    const bottom = box.cy + box.h / 2;
    assert.ok(top >= -1e-6 && bottom <= stage.height + 1e-6,
      `seed ${seed}: the prompt box spans ${top.toFixed(1)}..${bottom.toFixed(1)} ` +
      `on a ${stage.height}px stage`);
  }
});

test("a long prompt does not reshape the boxes that never show it", () => {
  // A context label can never display promptText, so its box must be sized the
  // same whatever the prompt is. Wrapping it to the prompt's width narrowed it
  // and reflowed the label for no reason.
  const WORDY = [
    { ord: 1, x: 0.2, y: 0.3, label: "Posterior inferior cerebellar artery" },
    { ord: 2, x: 0.6, y: 0.7, label: "Superior mesenteric arterial trunk" },
    { ord: 3, x: 0.8, y: 0.2, label: "Left anterior descending branch" },
  ];
  const shape = (promptText) => {
    const card = side({
      structures: WORDY, stage: { width: 320, height: 240 },
      direction: "forward", contextLabels: true, activeOrdinal: 1, seed: 99,
      config: { showDecoyDots: true, showTargetDot: true, promptText },
    });
    return boxesOf(card.svg)
      .filter((b) => b.text !== promptText)
      .map((b) => `${b.text}:${b.w.toFixed(4)}x${b.h.toFixed(4)}`)
      .sort();
  };
  assert.deepEqual(
    shape("which structure is marked here, exactly?"),
    shape("?"),
    "a wide prompt reshaped the context labels",
  );
});

test("context labels honour the dot settings", () => {
  // The non-context path consults showDecoyDots and showTargetDot; the context
  // path drew a dot on every structure whatever the config said. Each of the
  // three outcomes is checked, so both branches of the rule are pinned rather
  // than just the all-off case.
  const at = (ordinal) => project(STRUCTURES[ordinal - 1]);
  const card = (config) =>
    side({ direction: "forward", contextLabels: true, activeOrdinal: 2, seed: 7, config });

  assert.equal(
    dotsOf(card({ showDecoyDots: false, showTargetDot: false }).svg).length, 0,
    "both off draws nothing",
  );

  const decoys = dotsOf(card({ showDecoyDots: true, showTargetDot: true }).svg);
  assert.equal(decoys.length, STRUCTURES.length, "decoy dots mark every structure");

  const lone = dotsOf(card({ showDecoyDots: false, showTargetDot: true }).svg);
  assert.equal(lone.length, 1, "without decoys only the active structure is dotted");
  assert.ok(near(lone[0].x, at(2).x, 1e-6) && near(lone[0].y, at(2).y, 1e-6),
    "and that dot is on the active structure");
});

test("the answer side agrees with the question side when the seed cannot be stored", () => {
  // Each buildCard gets its own `window`, so these are separate PAGE LOADS and
  // the in-memory mirror cannot carry the seed across - which is the real
  // front-to-back case, as opposed to the repaint tests below.
  //
  // The question side used to mint a random seed it alone could see, leaving the
  // answer side to fall back to a deterministic hash: the box moved, and a
  // "both" card could ask "name it" and answer "locate it".
  const structures = [
    { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
    { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
    { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
    { ord: 4, x: 0.35, y: 0.6, label: "Pulmonary trunk" },
  ];
  // Both durable stores are degraded together: with either one working the
  // seed simply carries, which is the separate test below. This is the case
  // where nothing can hold it and both sides must land on the same
  // deterministic fallback instead.
  for (const storage of ["unavailable", "quota"]) {
    for (const activeOrdinal of [1, 2, 3, 4]) {
      const options = {
        structures, direction: "both", activeOrdinal,
        storage, localStorage: storage, config: DOTS_ON,
      };
      const front = buildCard(options);
      front.render(true); // the minting question view
      const back = buildCard(Object.assign({}, options, { back: true }));
      back.render(false);

      const f = boxesOf(front.svg)[0];
      const b = boxesOf(back.svg)[0];
      assert.ok(near(f.cx, b.cx, 1e-6) && near(f.cy, b.cy, 1e-6),
        `${storage}, ordinal ${activeOrdinal}: the box moved from (${f.cx}, ${f.cy}) ` +
        `to (${b.cx}, ${b.cy}) between question and answer`);
      assert.equal(front.typeBox.style.display, back.typeBox.style.display,
        `${storage}, ordinal ${activeOrdinal}: the card changed direction between ` +
        `question and answer`);
    }
  }
});

test("a failed write is detected even when a previous card's seed is stored", () => {
  // SEED_KEY is one global key that every card rewrites, so from the second card
  // of a session onward something is always there. Asking "is anything stored"
  // rather than "did MY write land" reports success for a write that threw on
  // quota, and the answer side then reproduces the wrong layout entirely.
  const structures = [
    { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
    { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
    { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
    { ord: 4, x: 0.35, y: 0.6, label: "Pulmonary trunk" },
  ];
  for (const activeOrdinal of [1, 2, 3, 4]) {
    // One store shared by both page loads, holding a PREVIOUS card's seed.
    const shared = { [SEED_KEY]: "4242" };
    const options = {
      structures, direction: "both", activeOrdinal,
      storage: "quota", localStorage: "quota", store: shared, config: DOTS_ON,
    };
    const front = buildCard(options);
    front.render(true); // mints, and its write throws
    const back = buildCard(Object.assign({}, options, { back: true }));
    back.render(false);

    const f = boxesOf(front.svg)[0];
    const b = boxesOf(back.svg)[0];
    assert.ok(near(f.cx, b.cx, 1e-6) && near(f.cy, b.cy, 1e-6),
      `ordinal ${activeOrdinal}: the box moved from (${f.cx}, ${f.cy}) to ` +
      `(${b.cx}, ${b.cy}); the question side kept a seed it could not store`);
    assert.equal(front.typeBox.style.display, back.typeBox.style.display,
      `ordinal ${activeOrdinal}: the card changed direction between question and answer`);
  }
});

test("the answer side agrees when it opens in a brand-new browsing context", () => {
  // sessionStorage is per browsing CONTEXT and the in-memory mirror is per page,
  // so a client that answers in a fresh web view (AnkiMobile does) had neither
  // -- and the question side could not detect that in advance, however careful
  // its write check was. localStorage is per ORIGIN, so it carries.
  const structures = [
    { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
    { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
    { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
  ];
  for (const activeOrdinal of [1, 2, 3]) {
    const origin = {}; // localStorage: shared, as it is in a real browser
    const front = buildCard({
      structures, direction: "both", activeOrdinal,
      store: {}, localStore: origin, config: DOTS_ON,
    });
    front.render(true); // mints and stores

    // A NEW context: its own empty session store, its own window (so no
    // in-memory mirror), and the same origin-wide localStorage.
    const back = buildCard({
      structures, direction: "both", activeOrdinal, back: true,
      store: {}, localStore: origin, config: DOTS_ON,
    });
    back.render(false);

    const f = boxesOf(front.svg)[0];
    const b = boxesOf(back.svg)[0];
    assert.ok(near(f.cx, b.cx, 1e-6) && near(f.cy, b.cy, 1e-6),
      `ordinal ${activeOrdinal}: the box moved from (${f.cx}, ${f.cy}) to ` +
      `(${b.cx}, ${b.cy}) when the answer opened in a fresh context`);
    assert.equal(front.typeBox.style.display, back.typeBox.style.display,
      `ordinal ${activeOrdinal}: the card changed direction between sides`);
  }
});

test("a full session store no longer forces the deterministic fallback", () => {
  // The fallback exists for when the seed cannot be kept at all. If the durable
  // store took it, the card should keep the layout it actually minted rather
  // than collapsing to the one hash every card of this shape produces.
  const structures = [
    { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
    { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
    { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
  ];
  for (const activeOrdinal of [1, 2, 3]) {
    const origin = {};
    const front = buildCard({
      structures, direction: "both", activeOrdinal,
      storage: "quota", store: {}, localStore: origin, config: DOTS_ON,
    });
    front.render(true);

    const fallback = String(
      front.internals.hashString("" + activeOrdinal + structures.length),
    );
    assert.ok(SEED_KEY in origin, "the durable store was never written");
    assert.notEqual(origin[SEED_KEY], fallback,
      "the minted seed was discarded even though the durable store took it");

    const back = buildCard({
      structures, direction: "both", activeOrdinal, back: true,
      storage: "quota", store: {}, localStore: origin, config: DOTS_ON,
    });
    back.render(false);
    const f = boxesOf(front.svg)[0];
    const b = boxesOf(back.svg)[0];
    assert.ok(near(f.cx, b.cx, 1e-6) && near(f.cy, b.cy, 1e-6),
      `ordinal ${activeOrdinal}: the sides disagree despite a durable seed`);
  }
});

test("a previous card's durable seed is dropped when this card cannot store one", () => {
  // The same stale-value hazard as the session store, one store along: if this
  // card's write is refused and the last card's seed is left behind, the answer
  // side reproduces THAT layout instead of this one.
  const structures = [
    { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
    { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
    { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
  ];
  for (const activeOrdinal of [1, 2, 3]) {
    const origin = { [SEED_KEY]: "4242" }; // the previous card's seed
    const options = {
      structures, direction: "both", activeOrdinal,
      storage: "quota", localStorage: "quota",
      store: {}, localStore: origin, config: DOTS_ON,
    };
    const front = buildCard(options);
    front.render(true); // mints; both writes are refused

    const back = buildCard(Object.assign({}, options, { back: true }));
    back.render(false);

    const f = boxesOf(front.svg)[0];
    const b = boxesOf(back.svg)[0];
    assert.ok(near(f.cx, b.cx, 1e-6) && near(f.cy, b.cy, 1e-6),
      `ordinal ${activeOrdinal}: the box moved from (${f.cx}, ${f.cy}) to ` +
      `(${b.cx}, ${b.cy}); the answer used a previous card's durable seed`);
  }
});

test("a repaint keeps its place when no storage is available at all", () => {
  // getItem throws rather than returning null in BOTH stores, so every durable
  // path is gone. The in-memory mirror is the last one left, and it is what
  // stops a resize repaint re-minting and moving the box mid-review.
  const card = buildCard({
    structures: STRUCTURES, config: DOTS_ON,
    storage: "unavailable", localStorage: "unavailable",
  });
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

// --- cards orphaned by a deletion -------------------------------------------
// Anki keeps the card of a deleted structure until Tools > Empty Cards is run.
// Editing a note no longer renumbers the survivors (that would move review
// history onto another structure), so these gaps are deliberate and common.
//
// Verified against a real collection: such a card has NO active cloze span --
// Anki has no cloze to make active -- and Anki prints its own localised "No
// cloze N found on card ... use the Empty Cards tool" beneath our template. So
// the renderer's job is only to stop drawing over that explanation.

test("a card orphaned by a deletion draws nothing over the image", () => {
  const survivors = STRUCTURES.filter((s) => s.ord !== 2);
  const card = buildCard({ structures: survivors, noOrdinalSpan: true, seed: 7 });

  card.render(false);

  assert.equal(boxesOf(card.svg).length, 0, "it drew a card-1 prompt box anyway");
  assert.equal(arrowsOf(card.svg).length, 0);
  assert.equal(dotsOf(card.svg).length, 0);
  assert.equal(card.svg.style.display, "none", "the overlay is taken down");
});

test("an ordinal that matches no structure also draws nothing", () => {
  // The payload and the cloze field disagree, which a hand-edited note can do.
  const survivors = STRUCTURES.filter((s) => s.ord !== 2);
  const card = buildCard({ structures: survivors, activeOrdinal: 2, seed: 7 });

  card.render(false);

  assert.equal(boxesOf(card.svg).length, 0);
  assert.equal(card.svg.style.display, "none");
});

test("a repaint keeps an undrawable card blank", () => {
  // render() runs again on every resize, so the second pass must reach the
  // same decision as the first rather than drawing over it.
  const survivors = STRUCTURES.filter((s) => s.ord !== 2);
  const card = buildCard({ structures: survivors, activeOrdinal: 2, seed: 7 });

  card.render(false);
  card.render(false);

  assert.equal(card.svg.style.display, "none");
  assert.equal(boxesOf(card.svg).length, 0, "the repaint drew the card anyway");
});

test("the surviving cards of the same note are untouched by that", () => {
  const survivors = STRUCTURES.filter((s) => s.ord !== 2);
  const card = buildCard({ structures: survivors, activeOrdinal: 3, seed: 7 });

  card.render(false);

  assert.deepEqual(
    boxesOf(card.svg).map((b) => b.text),
    [PROMPT],
    "a forward question draws exactly its own prompt box",
  );
  assert.notEqual(card.svg.style.display, "none");
});

test("single-card mode is never blanked by a deletion", () => {
  // Its cloze is always c1 whatever the survivors are numbered, so the ordinal
  // legitimately matches nothing once the first structure has been deleted.
  const survivors = STRUCTURES.filter((s) => s.ord !== 1);
  const card = buildCard({
    structures: survivors,
    mode: "single",
    activeOrdinal: 1,
    seed: 7,
  });

  card.render(false);

  assert.notEqual(card.svg.style.display, "none", "a good single card was blanked");
  assert.ok(boxesOf(card.svg).length > 0);
});
