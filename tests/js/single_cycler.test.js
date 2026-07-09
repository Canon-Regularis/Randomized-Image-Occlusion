"use strict";

// End-to-end tests of single-card mode: the interactive cycler. `render()` builds
// a control bar (progress counter, answer input, Check/Reveal/Next button), and
// these tests drive a whole review through it — typing answers, revealing,
// advancing marker by marker to the "done" state — then check the answer key on
// the back. This is the state machine the pure-helper tests never exercise.
//
// The seed is pre-set and rendered with `mint=false`, so the cycle order and the
// per-marker forward/backward assignment are reproducible; the test derives them
// from the same seed to know what each step should show and grade.

const test = require("node:test");
const assert = require("node:assert/strict");
const { buildCard, boxesOf } = require("./dom.js");

const ALL = [
  { ord: 1, x: 0.2, y: 0.3, label: "Aorta" },
  { ord: 2, x: 0.6, y: 0.7, label: "Vena cava" },
  { ord: 3, x: 0.8, y: 0.2, label: "Left atrium" },
];
const SEED = 20240607;

/** Open a single-mode card's front and hand back the cycler's pieces. */
function openCycler(structures, direction, interaction, seed) {
  const card = buildCard({
    structures,
    mode: "single",
    direction,
    interaction,
    seed,
    config: { showDecoyDots: true },
  });
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

test("backward markers never ask you to type, whatever the interaction", () => {
  // reverse = "locate it": there is nothing to type, so the input stays hidden.
  for (const interaction of ["type", "reveal"]) {
    const c = openCycler(ALL, "reverse", interaction, SEED);
    assert.equal(c.input.style.display, "none");
    assert.equal(c.button.textContent, "Reveal");
    assert.ok(c.forwards.every((f) => f === false), "every reverse marker is a locate marker");
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
