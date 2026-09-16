"use strict";

// End-to-end tests of single-card mode: the interactive cycler. `render()` builds
// a control bar (progress counter, answer input, Check/Reveal/Next button), and
// these tests drive a whole review through it (typing answers, revealing,
// advancing marker by marker to the "done" state), then check the answer key on
// the back. This is the state machine the pure-helper tests never exercise.
//
// The seed is pre-set and rendered with `mint=false`, so the cycle order and the
// per-marker forward/backward assignment are reproducible; the test derives them
// from the same seed to know what each step should show and grade.

const test = require("node:test");
const assert = require("node:assert/strict");
const { buildCard, boxesOf, dotsOf, arrowsOf } = require("./dom.js");

/** The box currently showing `text`, or undefined. `c` is an openCycler result. */
const boxShowing = (c, text) => boxesOf(c.card.svg).find((b) => b.text === text);

const ALL = [
  { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
  { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
  { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
];
const SEED = 20240607;

/** Open a single-mode card's front and hand back the cycler's pieces. */
function openCycler(structures, direction, interaction, seed, config, stage) {
  // `stage` is omitted rather than passed as undefined: buildCard merges with
  // Object.assign, so an explicit undefined would wipe out its default.
  const options = {
    structures,
    mode: "single",
    direction,
    interaction,
    seed,
    config: Object.assign({ showDecoyDots: true }, config),
  };
  if (stage) options.stage = stage;
  const card = buildCard(options);
  card.render(false);
  const bar = card.ids.get("ro-cycler");
  assert.ok(bar, "render() must build the cycler bar on a single-card front");
  const I = card.internals;
  return {
    card,
    bar,
    controller: bar.__roController,
    input: bar.querySelector("#ro-input"),
    button: bar.querySelector("#ro-btn"),
    progress: bar.querySelector("#ro-progress"),
    feedback: bar.querySelector("#ro-feedback"),
    // the cycle order and per-marker direction both derive from the seed
    order: I.shuffleIndices(structures.length, I.makeRng(seed)),
    forwards: I.cyclerDirections(seed, structures.length, direction),
  };
}

for (const count of [1, 2, 3]) {
  const structures = ALL.slice(0, count).map((s, i) => Object.assign({}, s, { ord: i + 1 }));

  for (const direction of ["forward", "reverse", "both"]) {
    for (const interaction of ["type", "reveal"]) {
      test(`single card (${count} marker(s), ${direction}, ${interaction}) runs the whole cycle`, () => {
        const c = openCycler(structures, direction, interaction, SEED);
        const typeMode = interaction === "type";

        for (let step = 0; step < count; step++) {
          const structure = structures[c.order[step]];
          // A marker is typed only when it is a "name it" marker AND the note types.
          const typed = typeMode && c.forwards[step];

          assert.equal(c.progress.textContent, `${step + 1} / ${count}`, "running counter");
          assert.equal(c.button.textContent, typed ? "Check" : "Reveal", "button label");
          assert.equal(
            c.input.style.display === "none",
            !typed,
            "the answer input shows only for a typed marker",
          );

          if (typed) {
            c.input.value = structure.label.toUpperCase(); // grading ignores case
            c.button.dispatch("click");
            assert.match(c.feedback.textContent, /Correct/, "the right answer grades correct");
          } else {
            c.button.dispatch("click"); // reveal / locate
          }

          assert.equal(c.button.textContent, "Next", "after revealing, the button advances");
          c.button.dispatch("click");
        }

        assert.equal(c.progress.textContent, `${count} / ${count} ✓`, "counter reaches done");
        assert.ok(c.bar.classList.contains("ro-done"), "the bar is marked done");
        assert.match(c.button.textContent, /Done/, "the button tells you to show the answer");
      });
    }
  }
}

test("no step of a single-card cycle identifies its answer by elimination", () => {
  // The accumulating answer key arrows every structure already answered, so a
  // structure with a dot and no arrow is one still to come. On the LAST marker
  // there are none still to come, leaving exactly one un-arrowed dot: the
  // answer. Every step is checked, not just the last, so the property holds for
  // the whole cycle.
  for (const direction of ["forward", "reverse", "both"]) {
    const c = openCycler(ALL, direction, "reveal", SEED);
    for (let step = 0; step < ALL.length; step++) {
      const structure = ALL[c.order[step]];
      const target = { x: structure.x * 800, y: structure.y * 600 };
      const dots = dotsOf(c.card.svg);
      const arrows = arrowsOf(c.card.svg);
      const near = (a, b) => Math.abs(a - b) <= 1e-6;
      const unarrowed = dots.filter(
        (d) => !arrows.some((a) => near(a.x2, d.x) && near(a.y2, d.y)),
      );
      const identifies =
        unarrowed.length === 1 &&
        near(unarrowed[0].x, target.x) &&
        near(unarrowed[0].y, target.y);
      assert.ok(
        !identifies,
        `${direction}, step ${step + 1}/${ALL.length}: one un-arrowed dot and ` +
          `it is the answer, so the marker can be located by elimination`,
      );
      c.button.dispatch("click"); // reveal / locate
      c.button.dispatch("click"); // next
    }
  }
});

test("a question side never shows the label of the marker being asked about", () => {
  // The single mutation that matters most in this file: swapping cfg.promptText
  // for the structure's own label in paint()'s forward branch prints the answer
  // on the question side, and every other test in this suite still passes.
  for (const direction of ["forward", "reverse", "both"]) {
    const c = openCycler(ALL, direction, "reveal", SEED);
    for (let step = 0; step < ALL.length; step++) {
      const structure = ALL[c.order[step]];
      const forward = c.forwards[step];

      if (forward) {
        // "name this one": the box must show the prompt, never the answer.
        assert.ok(boxShowing(c, "?"),
          `${direction} step ${step + 1}: the prompt box is missing`);
        assert.equal(boxShowing(c, structure.label), undefined,
          `${direction} step ${step + 1}: the question side prints "${structure.label}", ` +
          "which is the answer");
      } else {
        // "locate this one": the label IS the question, and no arrow may point
        // at it or there would be nothing left to find.
        const box = boxShowing(c, structure.label);
        assert.ok(box, `${direction} step ${step + 1}: the label to locate is missing`);
        const target = { x: structure.x * 800, y: structure.y * 600 };
        const near = (a, b) => Math.abs(a - b) <= 1e-6;
        assert.ok(
          !arrowsOf(c.card.svg).some((a) => near(a.x2, target.x) && near(a.y2, target.y)),
          `${direction} step ${step + 1}: an arrow points straight at the marker ` +
          "the learner is being asked to find",
        );
      }
      c.button.dispatch("click"); // reveal / locate
      c.button.dispatch("click"); // next
    }
  }
});

test("revealing a marker shows that marker's label and points at it", () => {
  // Every step, not just the first: taking the current structure from
  // layout.order[0] instead of layout.order[state.idx] would keep re-asking
  // about marker one while the counter advanced.
  const c = openCycler(ALL, "forward", "reveal", SEED);
  const near = (a, b) => Math.abs(a - b) <= 1e-6;
  for (let step = 0; step < ALL.length; step++) {
    const structure = ALL[c.order[step]];
    assert.equal(boxShowing(c, structure.label), undefined,
      `step ${step + 1}: the label is showing before it was revealed`);

    c.button.dispatch("click"); // reveal

    assert.ok(boxShowing(c, structure.label),
      `step ${step + 1}: revealing did not show ${structure.label}`);
    const target = { x: structure.x * 800, y: structure.y * 600 };
    assert.ok(arrowsOf(c.card.svg).some((a) => near(a.x2, target.x) && near(a.y2, target.y)),
      `step ${step + 1}: no arrow points at ${structure.label}`);
    c.button.dispatch("click"); // next
  }
});

test("the answer key accumulates one box per answered marker", () => {
  // Each answered structure stays on screen, drawn from its OWN entry in the
  // cycle order: drawing layout.order[0] every time would repeat one structure.
  const c = openCycler(ALL, "forward", "reveal", SEED);
  for (let step = 0; step < ALL.length; step++) {
    // Spread into this realm first: `order` comes from the vm sandbox, and
    // assert.deepEqual rejects an array whose prototype is another realm's.
    const answered = [...c.order].slice(0, step).map((i) => ALL[i].label).sort();
    const shown = boxesOf(c.card.svg)
      .map((b) => b.text)
      .filter((text) => text !== "?")
      .sort();
    assert.deepEqual(shown, answered,
      `step ${step + 1}: the answer key should hold exactly the markers already answered`);
    c.button.dispatch("click");
    c.button.dispatch("click");
  }
});

test("each answered marker keeps its own grading colour", () => {
  // Deliberately mixed: answer the first right and the second wrong. Colouring
  // the whole key from results[0] would paint them the same, and a single
  // right-or-wrong run could not tell the difference.
  const c = openCycler(ALL, "forward", "type", SEED);
  const expected = new Map();
  for (const [step, correct] of [[0, true], [1, false], [2, true]]) {
    const structure = ALL[c.order[step]];
    c.input.value = correct ? structure.label : "definitely not it";
    c.button.dispatch("click"); // grade

    const box = boxShowing(c, structure.label);
    assert.ok(box, `step ${step + 1}: the label is shown once graded`);
    const want = correct ? "ro-correct" : "ro-wrong";
    assert.ok(box.classes.includes(want),
      `step ${step + 1}: expected ${want}, got ${JSON.stringify(box.classes)}`);
    expected.set(structure.label, want);
    c.button.dispatch("click"); // next
  }

  // And the colours stay put as the key accumulates.
  for (const box of boxesOf(c.card.svg)) {
    const want = expected.get(box.text);
    if (want === undefined) continue;
    assert.ok(box.classes.includes(want),
      `${box.text} lost its ${want} marking as the key grew`);
  }
});

test("a repaint keeps the cycler's progress", () => {
  // The controller is built once and reused. Rebuilding it on every paint would
  // reset the review to marker 1 whenever the window is resized.
  const c = openCycler(ALL, "forward", "reveal", SEED);
  c.button.dispatch("click");
  c.button.dispatch("click"); // one marker answered

  const controller = c.bar.__roController;
  c.card.render(false); // the resize path

  assert.equal(c.bar.__roController, controller, "the controller was rebuilt");
  assert.equal(c.progress.textContent, `2 / ${ALL.length}`, "progress was lost");
});

test("a wrong typed answer is graded wrong and still reveals the label", () => {
  const c = openCycler(ALL, "forward", "type", SEED);
  const structure = ALL[c.order[0]];
  c.input.value = "not the answer";
  c.button.dispatch("click");
  assert.match(c.feedback.textContent, /Answer:/, "a wrong answer shows the correct label");
  assert.ok(!/✓ Correct/.test(c.feedback.textContent));
  assert.ok(c.feedback.textContent.includes(structure.label));
});

test("pressing Enter in the input grades the answer instead of flipping the card", () => {
  const c = openCycler(ALL, "forward", "type", SEED);
  const structure = ALL[c.order[0]];
  let defaultPrevented = false;
  c.input.value = structure.label;
  c.input.dispatch("keydown", {
    key: "Enter",
    preventDefault() {
      defaultPrevented = true;
    },
    stopPropagation() {},
  });
  assert.ok(defaultPrevented, "Enter must not reach Anki's show-answer shortcut");
  assert.match(c.feedback.textContent, /Correct/, "Enter submits the answer");
});

test("Enter finishes the whole cycle from the keyboard", () => {
  // Enter used to call reveal() directly, so once the answer was showing it did
  // nothing at all -- and the Next button is tabindex="-1", so a keyboard-only
  // learner could not advance past the first marker.
  const c = openCycler(ALL, "forward", "type", SEED);
  const press = () =>
    c.input.dispatch("keydown", {
      key: "Enter",
      preventDefault() {},
      stopPropagation() {},
    });

  for (let step = 0; step < ALL.length; step++) {
    c.input.value = ALL[c.order[step]].label;
    press(); // grade
    assert.match(c.feedback.textContent, /Correct/, `step ${step + 1}: not graded`);
    press(); // advance
  }
  assert.equal(c.progress.textContent, `${ALL.length} / ${ALL.length} ✓`,
    "Enter never carried the cycle to the end");
  assert.match(c.button.textContent, /^Done/,
    "the bar is not in its finished state");
});

test("a held Enter does not grade and advance in one go", () => {
  // One key doing both means auto-repeat scrolls the "Answer: ..." feedback
  // past before it can be read.
  const c = openCycler(ALL, "forward", "type", SEED);
  c.input.value = ALL[c.order[0]].label;
  c.input.dispatch("keydown", { key: "Enter", preventDefault() {}, stopPropagation() {} });
  const after = c.progress.textContent;

  c.input.dispatch("keydown", {
    key: "Enter", repeat: true, preventDefault() {}, stopPropagation() {},
  });
  assert.equal(c.progress.textContent, after,
    "an auto-repeated Enter advanced past the feedback");
});

test("backward markers never ask you to type, whatever the interaction", () => {
  // reverse = "locate it": there is nothing to type, so the input stays hidden.
  for (const interaction of ["type", "reveal"]) {
    const c = openCycler(ALL, "reverse", interaction, SEED);
    assert.equal(c.input.style.display, "none");
    assert.equal(c.button.textContent, "Reveal");
    assert.ok(c.forwards.every((f) => f === false), "every reverse marker is a locate marker");
  }
});

test("single-card mode honours the target-dot setting", () => {
  // The setting says "draw a dot on the structure the arrow points at", and
  // that is exactly the set single-card mode draws -- but it consulted neither
  // dot setting, so switching dots off left the whole cycle dotted anyway.
  for (const showTargetDot of [true, false]) {
    const c = openCycler(ALL, "forward", "reveal", SEED, { showTargetDot });
    c.button.dispatch("click"); // reveal marker one
    c.button.dispatch("click"); // next
    c.button.dispatch("click"); // reveal marker two
    // Both dot sources are now in play: the accumulating answer key and the
    // current marker's own dot.
    const drawn = dotsOf(c.card.svg).length;
    if (showTargetDot) {
      assert.ok(drawn > 0, "an answered marker should be dotted");
    } else {
      assert.equal(drawn, 0, `${drawn} dots drawn with the dot setting off`);
    }
  }
});

test("the single-card answer key honours the target-dot setting", () => {
  // The back is the whole key revealed at once, so every dot on it is a target
  // dot; it used to dot every structure whatever the setting said.
  for (const showTargetDot of [true, false]) {
    const back = buildCard({
      structures: ALL,
      mode: "single",
      direction: "forward",
      interaction: "reveal",
      seed: SEED,
      back: true,
      config: { showDecoyDots: true, showTargetDot },
    });
    back.render(false);
    assert.equal(boxesOf(back.svg).length, ALL.length,
      "the answer key must label every structure whatever the dots do");
    assert.equal(dotsOf(back.svg).length, showTargetDot ? ALL.length : 0,
      `the answer key drew ${dotsOf(back.svg).length} dots with the setting ` +
      `${showTargetDot ? "on" : "off"}`);
  }
});

const LONG_PROMPT = "which structure is marked here, exactly?";

//: Long enough to wrap, on a stage small enough that the room beside a box is
//: narrower than the stage: only then does the wrap WIDTH -- the one thing
//: `flips` decides -- change the box at all.
const WORDY = [
  { ord: 1, x: 0.2, y: 0.3, label: "Posterior inferior cerebellar artery" },
  { ord: 2, x: 0.6, y: 0.7, label: "Superior mesenteric arterial trunk" },
  { ord: 3, x: 0.8, y: 0.2, label: "Left anterior descending branch" },
];
const SMALL = { width: 320, height: 240 };

test("the answer key reproduces the boxes the cycle drew", () => {
  // Only a FORWARD position ever shows the prompt, so only that one wraps to
  // the prompt's width. Wrapping them all (or none) made the same marker a
  // different shape during the cycle and on the answer key, so it visibly
  // changed size when the card was flipped. A one-character prompt hides this
  // completely, which is why every existing test missed it.
  const config = { showDecoyDots: true, showTargetDot: true, promptText: LONG_PROMPT };
  const c = openCycler(WORDY, "both", "reveal", SEED, config, SMALL);
  for (let step = 0; step < WORDY.length; step++) {
    c.button.dispatch("click"); // reveal
    c.button.dispatch("click"); // next
  }
  const front = new Map(boxesOf(c.card.svg).map((b) => [b.text, b]));
  assert.equal(front.size, WORDY.length, "the cycle did not finish");

  const back = buildCard({
    structures: WORDY, mode: "single", direction: "both",
    interaction: "reveal", seed: SEED, back: true, stage: SMALL, config,
  });
  back.render(false);

  for (const b of boxesOf(back.svg)) {
    const f = front.get(b.text);
    assert.ok(f, `the answer key is missing ${b.text}`);
    assert.ok(
      Math.abs(f.w - b.w) < 1e-6 && Math.abs(f.h - b.h) < 1e-6,
      `${b.text}: ${f.w}x${f.h} during the cycle, ${b.w}x${b.h} on the back`,
    );
  }
});

test("the back of a single card is the full answer key", () => {
  for (const direction of ["forward", "reverse", "both"]) {
    const back = buildCard({
      structures: ALL,
      mode: "single",
      direction,
      interaction: "type",
      seed: SEED,
      back: true,
      config: { showDecoyDots: true },
    });
    back.render(false);
    const boxes = boxesOf(back.svg);
    assert.equal(boxes.length, ALL.length, "every structure is labelled on the back");
    for (const box of boxes) {
      assert.ok(
        ALL.some((s) => s.label === box.text),
        `answer key drew an unexpected label: ${box.text}`,
      );
    }
  }
});
