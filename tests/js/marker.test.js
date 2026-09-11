"use strict";

// Behaviour of the editor canvas: zoom, pan, marker placement and the gesture
// interactions between them. Before this suite marker.js had a single test -
// that it parses, so these also lock down the pre-existing click/drag rules
// that the zoom work had to leave intact.

const test = require("node:test");
const assert = require("node:assert/strict");

const { buildEditor } = require("./marker_dom.js");

const PNG = "data:image/png;base64,AA==";

/** An editor with an image already loaded and laid out. */
function loaded(opts) {
  const h = buildEditor(opts);
  h.api.setImage(PNG, (opts && opts.markers) || null);
  h.load();
  return h;
}

/** Where a client point falls on the image, normalized 0..1. */
function norm(h, x, y) {
  const r = h.els.img.getBoundingClientRect();
  return { x: (x - r.left) / r.width, y: (y - r.top) / r.height };
}

const near = (a, b, tol) => Math.abs(a - b) <= (tol === undefined ? 1e-9 : tol);

/** The label field for one marker row. */
const rowInput = (h, index) =>
  h.document.querySelector(`.ed-row-input[data-index="${index}"]`);

/** Type into a label field the way a user does. */
function type(h, index, text) {
  const input = rowInput(h, index);
  input.value = text;
  input.dispatch("input", {});
  return input;
}

/**
 * Markers as plain objects in *this* realm.
 *
 * getMarkers() builds them inside the vm sandbox, so they carry that realm's
 * Object.prototype and deepEqual rejects them as "not reference-equal" however
 * identical their contents.
 */
const plain = (markers) => markers.map((m) => ({ x: m.x, y: m.y, label: m.label }));

/** The count messages sent to Python, most recent last. */
const counts = (h) =>
  h.sent.filter((m) => m.startsWith("ro:count:")).map((m) => Number(m.slice(9)));

// ---------------------------------------------------------------- pure maths

test("clampZoom holds the range and rejects junk", () => {
  const i = buildEditor().api._internals;
  assert.equal(i.clampZoom(0.1), i.MIN_ZOOM);
  assert.equal(i.clampZoom(99), i.MAX_ZOOM);
  assert.equal(i.clampZoom(2.5), 2.5);
  // Anything unusable falls back to the fitted view rather than to an extreme:
  // a NaN or an infinity means something upstream is broken, and the safe
  // answer is the view the user can definitely make sense of.
  assert.equal(i.clampZoom(NaN), i.MIN_ZOOM);
  assert.equal(i.clampZoom(Infinity), i.MIN_ZOOM);
  assert.equal(i.clampZoom("2"), i.MIN_ZOOM);
});

test("normalizeWheelDelta converts every deltaMode to pixels", () => {
  const i = buildEditor().api._internals;
  assert.equal(i.normalizeWheelDelta(100, 0), 100);
  assert.equal(i.normalizeWheelDelta(3, 1), 48); // lines
  assert.equal(i.normalizeWheelDelta(2, 2), 800); // pages
  assert.equal(i.normalizeWheelDelta(NaN, 0), 0);
});

test("zoomAt keeps the anchored point where it was", () => {
  const i = buildEditor().api._internals;
  // A point 120px from the image's left edge, zooming 1x -> 3x.
  const p = i.zoomAt(120, 0, 1, 3);
  // After the zoom that same image point sits 360px from the edge, so the pan
  // must pull it back by the 240px difference.
  assert.equal(p, -240);
  assert.equal(i.zoomAt(120, 0, 1, 1), 0); // no zoom change, no pan change
});

test("clampPan covers the viewport, and centres when it cannot", () => {
  const i = buildEditor().api._internals;
  // Content 1600 wide in an 800 viewport laid out at 0: pan may range -800..0.
  assert.equal(i.clampPan(0, 1600, 800, 0), 0);
  assert.equal(i.clampPan(-2000, 1600, 800, 0), -800);
  assert.equal(i.clampPan(500, 1600, 800, 0), 0);
  // Content smaller than the viewport is pinned to its centred layout spot,
  // which for a flex-centred image is a pan of exactly 0.
  assert.equal(i.clampPan(300, 400, 800, 200), 0);
});

test("nudgeStep is one screen pixel, ten with Shift", () => {
  const i = buildEditor().api._internals;
  assert.equal(i.nudgeStep(false), 1);
  assert.equal(i.nudgeStep(true), 10);
});

// ------------------------------------------------------- coordinates vs zoom

test("pointToNormalized is invariant under zoom", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const target = { x: 0.32, y: 0.71 };

  let p = h.pointAt(target.x, target.y);
  h.clickImage(p.x, p.y);
  const atFit = h.api.getMarkers()[0];

  h.api.setZoom(4);
  p = h.pointAt(target.x, target.y);
  h.clickImage(p.x, p.y);
  const atZoom = h.api.getMarkers()[1];

  assert.ok(near(atFit.x, target.x, 1e-9) && near(atFit.y, target.y, 1e-9));
  assert.ok(near(atZoom.x, atFit.x, 1e-9), `${atZoom.x} vs ${atFit.x}`);
  assert.ok(near(atZoom.y, atFit.y, 1e-9), `${atZoom.y} vs ${atFit.y}`);
});

test("zoom and pan do not mutate stored marker coordinates", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.25, 0.4);
  h.clickImage(p.x, p.y);
  const before = JSON.stringify(h.api.getMarkers());

  h.wheel(400, 300, -300);
  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 250, clientY: 180 });
  h.fire("pointerup", { clientX: 250, clientY: 180 });

  assert.ok(h.state().zoom > 1, "the wheel should have zoomed");
  assert.equal(JSON.stringify(h.api.getMarkers()), before);
});

test("wheel zoom holds the point under the cursor fixed", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const cursor = { x: 480, y: 200 };
  const before = norm(h, cursor.x, cursor.y);

  h.wheel(cursor.x, cursor.y, -400);
  const after = norm(h, cursor.x, cursor.y);

  assert.ok(h.state().zoom > 1.2, `zoom was ${h.state().zoom}`);
  assert.ok(near(before.x, after.x, 1e-9), `${before.x} vs ${after.x}`);
  assert.ok(near(before.y, after.y, 1e-9), `${before.y} vs ${after.y}`);
});

test("pan is zero at MIN_ZOOM for every image shape", () => {
  for (const image of [
    { width: 800, height: 600 }, // fills the stage
    { width: 400, height: 300 }, // letterboxed on both axes
    { width: 800, height: 120 }, // very wide
    { width: 120, height: 600 }, // very tall
  ]) {
    const h = loaded({ stage: { width: 800, height: 600 }, image });
    h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
    h.fire("pointermove", { clientX: 20, clientY: 20 });
    h.fire("pointerup", { clientX: 20, clientY: 20 });
    const s = h.state();
    assert.equal(s.panX, 0, `panX for ${image.width}x${image.height}`);
    assert.equal(s.panY, 0, `panY for ${image.width}x${image.height}`);
  }
});

test("pan is clamped so the image covers the viewport", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2); // 1600x1200 of content in an 800x600 viewport

  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 9000, clientY: 9000 });
  h.fire("pointerup", { clientX: 9000, clientY: 9000 });

  // The visible region is the stage's PADDING box; `overflow:hidden` clips
  // there, one pixel inside the border, not its border box.
  const r = h.els.img.getBoundingClientRect();
  const visible = h.visibleRect();
  assert.ok(r.left <= visible.left, `left edge ${r.left} left a gap`);
  assert.ok(r.top <= visible.top, `top edge ${r.top} left a gap`);
  assert.ok(r.right >= visible.right, `right edge ${r.right} left a gap`);
  assert.ok(r.bottom >= visible.bottom, `bottom edge ${r.bottom} left a gap`);
});

test("overlay geometry at MIN_ZOOM matches the pre-zoom renderer", () => {
  // The old renderer placed a dot at offsetLeft + x*clientWidth. A 400x300
  // image centred in an 800x600 stage puts the middle of the image at (400,300)
  // in overlay space, and that must still be exactly true.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400, height: 300 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  assert.deepEqual(h.dots(), [{ x: 400, y: 300 }]);
});

// -------------------------------------------------------- gesture interplay

test("pan released off-image leaves the click latch clear", () => {
  // Regression: the suppression flag used to be armed on any moved gesture but
  // only ever cleared by a click on the image, so a gesture that ended anywhere
  // else latched it and ate the user's next genuine placement.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);

  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 300, clientY: 250 });
  h.fire("pointerup", { clientX: 5000, clientY: 5000 }); // released off the image

  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  assert.equal(h.api.getMarkers().length, 1, "the next click must still place a marker");
});

test("marker drag released off-image leaves the click latch clear", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  let p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);

  h.on(h.groups()[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.fire("pointermove", { clientX: p.x + 40, clientY: p.y + 40 });
  h.fire("pointerup", { clientX: 5000, clientY: 5000 });

  p = h.pointAt(0.2, 0.2);
  h.clickImage(p.x, p.y);
  assert.equal(h.api.getMarkers().length, 2);
});

test("space pan released on-image suppresses the trailing click", () => {
  // Only a PRIMARY-button release can be followed by a click, so this is the one
  // pan gesture where the click-suppression latch has anything to suppress.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);

  h.key(" ");
  h.on(h.els.stage, "pointerdown", { button: 0, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 360, clientY: 280 });
  h.release(h.els.img, { button: 0, clientX: 360, clientY: 280 });
  h.keyUp(" ");

  assert.equal(h.api.getMarkers().length, 0);
});

test("non-primary pan does not set the click latch", () => {
  // Regression: the latch used to be armed after ANY pan that ended over the
  // image. Middle and right buttons release as `auxclick`, never `click`, so
  // nothing could ever consume it and the user's next click was eaten.
  for (const button of [1, 2]) {
    const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
    h.api.setZoom(2);

    h.on(h.els.stage, "pointerdown", { button, clientX: 400, clientY: 300 });
    h.fire("pointermove", { clientX: 360, clientY: 280 });
    h.release(h.els.stage, { button, clientX: 360, clientY: 280 });

    const p = h.pointAt(0.5, 0.5);
    h.on(h.els.img, "pointerdown", { button: 0, clientX: p.x, clientY: p.y });
    h.release(h.els.img, { button: 0, clientX: p.x, clientY: p.y });
    assert.equal(h.api.getMarkers().length, 1, `button ${button} ate the next click`);
  }
});

test("marker drag does not set the click latch", () => {
  // Regression: a marker press lands inside #ed-overlay, a sibling of #ed-img,
  // so its click resolves to #ed-stage and never reaches onImageClick. Arming
  // the latch there left it stuck and ate the next marker the user placed.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const first = h.pointAt(0.5, 0.5);
  h.clickImage(first.x, first.y);

  const to = h.pointAt(0.6, 0.6);
  h.on(h.groups()[0], "pointerdown", { clientX: first.x, clientY: first.y });
  h.fire("pointermove", { clientX: to.x, clientY: to.y });
  h.release(h.els.stage, { button: 0, clientX: to.x, clientY: to.y });

  const second = h.pointAt(0.2, 0.2);
  h.on(h.els.img, "pointerdown", { button: 0, clientX: second.x, clientY: second.y });
  h.release(h.els.img, { button: 0, clientX: second.x, clientY: second.y });
  assert.equal(h.api.getMarkers().length, 2, "the drag ate the next placement");
});

test("sub-threshold middle press does not set the click latch", () => {
  // At fit zoom a pan moves nothing on screen, so a 1px wobble left the latch
  // armed with no visual cue that any gesture had happened.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });

  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 401, clientY: 300 });
  h.release(h.els.stage, { button: 1, clientX: 401, clientY: 300 });

  const p = h.pointAt(0.3, 0.3);
  h.on(h.els.img, "pointerdown", { button: 0, clientX: p.x, clientY: p.y });
  h.release(h.els.img, { button: 0, clientX: p.x, clientY: p.y });
  assert.equal(h.api.getMarkers().length, 1);
});

test("sub-threshold space pan does not place a marker", () => {
  // A press with Space held means pan, however far it travels. Suppressing the
  // trailing click only when the gesture "moved far enough" let a 2px pan fall
  // through to click-to-add and plant a marker the user never asked for.
  for (const distance of [0, 1, 2, 40]) {
    const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
    h.api.setZoom(2);
    h.els.stage.focus();
    h.key(" ");

    h.on(h.els.stage, "pointerdown", { button: 0, clientX: 400, clientY: 300 });
    h.fire("pointermove", { clientX: 400 + distance, clientY: 300 });
    h.release(h.els.img, { button: 0, clientX: 400 + distance, clientY: 300 });
    h.keyUp(" ");

    assert.equal(h.api.getMarkers().length, 0, `a ${distance}px Space-pan placed a marker`);
  }
});

test("bare primary press places a marker and does not pan", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);
  const before = h.state();

  h.on(h.els.stage, "pointerdown", { button: 0, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 200, clientY: 150 });
  h.fire("pointerup", { clientX: 200, clientY: 150 });

  assert.equal(h.state().panX, before.panX, "a primary drag must not pan");
  h.clickImage(200, 150);
  assert.equal(h.api.getMarkers().length, 1);
});

test("space arms panning on the primary button", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);

  const before = h.state().panX;
  h.key(" ");
  h.on(h.els.stage, "pointerdown", { button: 0, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 340, clientY: 300 });
  h.fire("pointerup", { clientX: 340, clientY: 300 });
  h.keyUp(" ");

  assert.equal(h.state().panX, before - 60);
  assert.ok(h.els.stage._classes.has("ed-pan-ready") === false, "the cursor hint must clear");
});

test("blur with space held clears spaceHeld", () => {
  // Regression: the keyup lands in whichever application the user switched to,
  // so spaceHeld stayed true. makeMarkerPointerDown then bailed before its
  // stopPropagation(), the press bubbled to the stage, and repositioning a
  // marker panned the picture instead of moving the marker.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.api.setZoom(2);

  h.els.stage.focus(); // Space is ignored while a label field has focus
  h.key(" ");
  assert.ok(
    h.els.stage._classes.has("ed-pan-ready"),
    "precondition: Space must actually have armed panning",
  );
  h.fire("blur", {}); // switched away; the keyup never arrives
  assert.equal(h.els.stage._classes.has("ed-pan-ready"), false, "blur must disarm it");
  const panBefore = h.state().panX;

  const to = h.pointAt(0.6, 0.6);
  h.on(h.groups()[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.fire("pointermove", { clientX: to.x, clientY: to.y });
  h.fire("pointerup", { clientX: to.x, clientY: to.y });

  assert.equal(h.state().panX, panBefore, "the picture must not have panned");
  assert.ok(near(h.api.getMarkers()[0].x, 0.6, 1e-9), "the marker must have moved");
});

test("setImage preserves the current zoom", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2); // what the dialog restores from config on open

  h.els.stage.focus();
  h.key("+"); // and then the user zooms in further themselves
  const chosen = h.state().zoom;
  assert.ok(chosen > 2);

  h.api.setImage(PNG, null); // "Replace image…"
  h.load();
  assert.equal(h.state().zoom, chosen, "a new picture must not reset the zoom");
});

test("setImage preserves a reset to MIN_ZOOM", () => {
  // Regression: setImage restored the level the dialog OPENED at, so pressing
  // Fit and then replacing the image jumped straight back to the old zoom.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(4);
  h.els.stage.focus();
  h.key("0");
  assert.equal(h.state().zoom, 1);

  h.api.setImage(PNG, null);
  h.load();
  assert.equal(h.state().zoom, 1, "Fit must not be undone by loading a picture");
});

test("marker drag maps coordinates correctly while zoomed", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  let p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.api.setZoom(4);

  p = h.pointAt(0.5, 0.5);
  const target = h.pointAt(0.52, 0.55);
  h.on(h.groups()[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.fire("pointermove", { clientX: target.x, clientY: target.y });
  h.fire("pointerup", { clientX: target.x, clientY: target.y });

  const m = h.api.getMarkers()[0];
  assert.ok(near(m.x, 0.52, 1e-9), `x was ${m.x}`);
  assert.ok(near(m.y, 0.55, 1e-9), `y was ${m.y}`);
});

test("wheel is ignored during a marker drag", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);

  h.on(h.groups()[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.wheel(p.x, p.y, -400);
  assert.equal(h.state().zoom, 1, "zooming mid-drag would slide the marker off the cursor");
  h.fire("pointerup", { clientX: p.x, clientY: p.y });

  h.wheel(p.x, p.y, -400);
  assert.ok(h.state().zoom > 1, "and it works again once the drag ends");
});

test("second pointer cannot start a drag during a pan", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.api.setZoom(2);

  h.on(h.els.stage, "pointerdown", { button: 1, pointerId: 1, clientX: 400, clientY: 300 });
  h.on(h.groups()[0], "pointerdown", { pointerId: 2, clientX: p.x, clientY: p.y });

  const dragging = h.groups().some((g) => g._classes.has("ed-marker-dragging"));
  assert.equal(dragging, false);
});

test("wheel is preventDefaulted before an image loads", () => {
  // The guard used to return before preventDefault(), so an early wheel fell
  // through to the page, and QtWebEngine reads ctrl+wheel as its own page zoom,
  // which would scale the editor out from under every coordinate on it.
  const h = buildEditor(); // deliberately no setImage/load
  let prevented = 0;
  h.on(h.els.stage, "wheel", {
    clientX: 400, clientY: 300, deltaY: -100, deltaMode: 0,
    preventDefault: () => { prevented += 1; },
  });
  assert.equal(prevented, 1);
  assert.equal(h.state().zoom, 1, "and it must not zoom with nothing to zoom");
});

test("wheel is preventDefaulted to block QtWebEngine page zoom", () => {
  const h = loaded();
  let prevented = 0;
  h.on(h.els.stage, "wheel", {
    clientX: 400, clientY: 300, deltaY: -100, deltaMode: 0,
    preventDefault: () => { prevented += 1; },
  });
  assert.equal(prevented, 1);
});

// ------------------------------------------------------------------ keyboard

test("zoom keys are ignored while a text field has focus", () => {
  const h = loaded();
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y); // focusInput() parks focus in the new label field
  assert.equal(h.document.activeElement.tagName, "INPUT");

  // Only "+"; pressing "0" as well would reset the zoom and the assertion
  // would hold whether or not the guard did anything.
  h.key("+");
  assert.equal(h.state().zoom, 1, "typing in a label must never zoom");
});

test("modified keys are not handled", () => {
  const h = loaded();
  let prevented = 0;
  const spy = { preventDefault: () => { prevented += 1; } };
  h.key("f", Object.assign({ ctrlKey: true }, spy)); // Ctrl+F = find in page
  h.key("+", Object.assign({ ctrlKey: true }, spy));
  h.key("+", Object.assign({ isComposing: true }, spy)); // mid-IME
  assert.equal(prevented, 0);
  assert.equal(h.state().zoom, 1);
});

test("plus, minus and zero zoom in, out and to fit", () => {
  const h = loaded();
  h.els.stage.focus();

  h.key("+");
  const zoomedIn = h.state().zoom;
  assert.ok(zoomedIn > 1, `+ should zoom in, got ${zoomedIn}`);

  h.key("+");
  assert.ok(h.state().zoom > zoomedIn);

  h.key("-");
  assert.ok(near(h.state().zoom, zoomedIn, 1e-9));

  h.key("0");
  assert.equal(h.state().zoom, 1);
});

test("arrow keys nudge the selected marker one screen pixel", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400, height: 300 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  // Grabbing the dot selects it and moves focus off the label field.
  h.on(h.groups()[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.fire("pointerup", { clientX: p.x, clientY: p.y });

  h.key("ArrowRight");
  assert.ok(near(h.api.getMarkers()[0].x, 0.5 + 1 / 400, 1e-9));

  h.key("ArrowDown", { shiftKey: true });
  assert.ok(near(h.api.getMarkers()[0].y, 0.5 + 10 / 300, 1e-9));
});

test("nudge clamps at the image edge", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400, height: 300 } });
  const p = h.pointAt(0, 0);
  h.clickImage(p.x, p.y);
  h.on(h.groups()[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.fire("pointerup", { clientX: p.x, clientY: p.y });

  for (let n = 0; n < 5; n += 1) h.key("ArrowLeft", { shiftKey: true });
  const m = h.api.getMarkers()[0];
  assert.equal(m.x, 0);
  assert.equal(m.y, 0);
});

test("arrow keys are ignored with no selection", () => {
  const h = loaded();
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.els.stage.focus();
  h.api.setImage(PNG, [{ x: 0.5, y: 0.5, label: "a" }]); // resets the selection
  h.load();
  h.key("ArrowRight");
  assert.equal(h.api.getMarkers()[0].x, 0.5);
});

// ------------------------------------------------------------- lifecycle

test("setImage resets view state and cancels gestures", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.api.setZoom(4);

  // A pan and a marker drag both left mid-gesture, as "Replace image…" can do.
  h.on(h.groups()[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.api.setImage(PNG, null);
  h.load();

  const s = h.state();
  assert.equal(s.zoom, 4, "the remembered zoom level survives a new image");
  assert.equal(s.selected, -1);
  assert.equal(h.api.getMarkers().length, 0);
  // Re-centred, so the new picture is never parked off-screen.
  const r = h.els.img.getBoundingClientRect();
  const stage = h.els.stage._rect;
  assert.ok(near(r.left + r.width / 2, stage.left + stage.width / 2, 1e-9));
  assert.ok(near(r.top + r.height / 2, stage.top + stage.height / 2, 1e-9));

  // The abandoned drag must not still be writing through to a marker.
  const q = h.pointAt(0.25, 0.25);
  h.clickImage(q.x, q.y);
  h.fire("pointermove", { clientX: h.pointAt(0.9, 0.9).x, clientY: h.pointAt(0.9, 0.9).y });
  assert.ok(near(h.api.getMarkers()[0].x, 0.25, 1e-9));
});

test("setImage keeps the restored zoom in the prefill flow", () => {
  const h = buildEditor({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(3); // what the dialog pushes from config on ro:ready

  // The edit flow hands over the markers before the image has loaded.
  h.api.setImage(PNG, [
    { x: 0.25, y: 0.25, label: "one" },
    { x: 0.75, y: 0.5, label: "two" },
  ]);
  assert.equal(h.dots().length, 0, "no geometry is known until the image loads");

  h.load();
  assert.equal(h.state().zoom, 3);
  // JSON, not deepEqual: these objects are minted inside the vm sandbox, so
  // they carry its Object.prototype and deepStrictEqual rejects them on realm.
  assert.equal(
    JSON.stringify(h.api.getMarkers()),
    JSON.stringify([
      { x: 0.25, y: 0.25, label: "one" },
      { x: 0.75, y: 0.5, label: "two" },
    ]),
  );
  // Both dots are drawn, and at 3x they are 3x further apart on screen.
  const dots = h.dots();
  assert.equal(dots.length, 2);
  assert.ok(near(dots[1].x - dots[0].x, 0.5 * 800 * 3, 1e-6));
});

test("deleting a marker shifts the selection index", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  for (const n of [0.2, 0.5, 0.8]) {
    const p = h.pointAt(n, n);
    h.clickImage(p.x, p.y);
  }
  // Select the last marker, then delete the first.
  const p = h.pointAt(0.8, 0.8);
  h.on(h.groups()[2], "pointerdown", { clientX: p.x, clientY: p.y });
  h.fire("pointerup", { clientX: p.x, clientY: p.y });
  assert.equal(h.state().selected, 2);

  h.document.querySelector('.ed-row-input[data-index="0"]');
  const rows = h.els.list.childNodes;
  rows[0].childNodes.find((c) => c._classes.has("ed-row-del")).dispatch("click");

  assert.equal(h.state().selected, 1, "the selection shifts down with the array");
  h.key("ArrowRight");
  assert.ok(h.api.getMarkers()[1].x > 0.8, "and still nudges the marker the user picked");
});

// ---------------------------------------------------------------- reporting

test("focus transitions emit ro:textfocus", () => {
  // Python uses this to stand its window-wide Ctrl+V down, so that typing a
  // label and pressing Ctrl+V pastes text instead of trying to replace the image.
  const h = loaded();
  h.sent.length = 0;

  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y); // focusInput() puts focus in the new label field
  h.runTimers();
  assert.deepEqual(
    h.sent.filter((m) => m.startsWith("ro:textfocus:")),
    ["ro:textfocus:1"],
  );

  h.sent.length = 0;
  h.blurAll();
  h.runTimers();
  assert.deepEqual(
    h.sent.filter((m) => m.startsWith("ro:textfocus:")),
    ["ro:textfocus:0"],
  );
});

test("focus changes within text fields are not reported", () => {
  // The rows are destroyed and rebuilt constantly; reporting every churn would
  // make the shortcut flap on and off.
  const h = loaded();
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.runTimers();
  h.sent.length = 0;

  h.focus(h.document.querySelector('.ed-row-input[data-index="0"]'));
  h.runTimers();
  assert.deepEqual(h.sent.filter((m) => m.startsWith("ro:textfocus:")), []);
});

test("toolbar readout and buttons track the zoom", () => {
  const h = loaded();
  assert.equal(h.els.zoomLevel.textContent, "100%");
  assert.equal(h.els.zoomOut.disabled, true, "cannot zoom out below the fit");
  assert.equal(h.els.zoomIn.disabled, false);

  h.els.zoomIn.dispatch("click");
  assert.equal(h.els.zoomLevel.textContent, "125%");
  assert.equal(h.els.zoomOut.disabled, false);

  h.els.zoomFit.dispatch("click");
  assert.equal(h.els.zoomLevel.textContent, "100%");
  assert.equal(h.els.zoomFit.disabled, true);
});

test("zoom is reported immediately then throttled", () => {
  const h = loaded();
  const zooms = () => h.sent.filter((m) => m.startsWith("ro:zoom:"));
  h.sent.length = 0;

  h.wheel(400, 300, -100);
  assert.equal(zooms().length, 1, "the first change reports at once");
  h.wheel(400, 300, -100);
  h.wheel(400, 300, -100);
  assert.equal(zooms().length, 1, "the rest of the gesture is throttled");

  h.runTimers();
  const reported = zooms();
  assert.equal(reported.length, 2, "and the settled level follows");
  const last = Number(reported[reported.length - 1].slice("ro:zoom:".length));
  assert.ok(near(last, h.state().zoom, 1e-4), `reported ${last}, actual ${h.state().zoom}`);
});

test("first zoom change is reported before the throttle window", () => {
  // The report used to be trailing-edge only, so a zoom followed by an
  // immediate close sent nothing at all and the level was silently not saved.
  const h = loaded();
  h.sent.length = 0;
  h.wheel(400, 300, -200);
  assert.ok(
    h.sent.some((m) => m.startsWith("ro:zoom:")),
    "no ro:zoom before the throttle window elapsed",
  );
});

test("markInvalid pans an off-screen marker into view", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.05, 0.05);
  h.clickImage(p.x, p.y);

  h.api.setZoom(4);
  // Park the view on the opposite corner, so marker 0 is far off-screen.
  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: -9000, clientY: -9000 });
  h.fire("pointerup", { clientX: -9000, clientY: -9000 });

  const r0 = h.els.img.getBoundingClientRect();
  const before = { x: r0.left + 0.05 * r0.width, y: r0.top + 0.05 * r0.height };
  const stage = h.els.stage._rect;
  assert.ok(before.x < stage.left || before.y < stage.top, "precondition: off-screen");

  h.api.markInvalid([0]);

  const r1 = h.els.img.getBoundingClientRect();
  const after = { x: r1.left + 0.05 * r1.width, y: r1.top + 0.05 * r1.height };
  assert.ok(
    after.x >= stage.left && after.x <= stage.right &&
    after.y >= stage.top && after.y <= stage.bottom,
    `marker still off-screen at ${after.x},${after.y}`,
  );
});

test("crosshair follows the pointer only over the image", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400, height: 300 } });
  const p = h.pointAt(0.5, 0.5);

  h.on(h.els.stage, "pointermove", { clientX: p.x, clientY: p.y });
  assert.equal(h.crosshairLines(), 2);

  h.on(h.els.stage, "pointermove", { clientX: 5, clientY: 5 }); // letterbox, not the image
  assert.equal(h.crosshairLines(), 0);

  h.on(h.els.stage, "pointermove", { clientX: p.x, clientY: p.y });
  h.on(h.els.stage, "pointerleave", {});
  assert.equal(h.crosshairLines(), 0);
});

test("window resize re-clamps the pan", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);
  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 100, clientY: 100 });
  h.fire("pointerup", { clientX: 100, clientY: 100 });
  assert.ok(h.state().panX < 0);

  // The stage grows past the scaled image, so the only legal pan is centred.
  h.resizeStage(2000, 1600);
  h.fire("resize", {});
  h.runTimers();

  const r = h.els.img.getBoundingClientRect();
  const visible = h.visibleRect();
  assert.ok(
    near(r.left + r.width / 2, visible.left + visible.width / 2, 1e-9),
    "re-centred in x",
  );
  assert.ok(
    near(r.top + r.height / 2, visible.top + visible.height / 2, 1e-9),
    "re-centred in y",
  );
  assert.ok(r.left >= visible.left && r.right <= visible.right, "and fully visible again");
});

// ------------------------------------------------------- labels and the list

test("label input updates the marker label", () => {
  const h = loaded();
  const p = h.pointAt(0.4, 0.6);
  h.clickImage(p.x, p.y);

  type(h, 0, "Aorta");
  assert.equal(h.api.getMarkers()[0].label, "Aorta");
});

test("getMarkers trims labels and returns a copy", () => {
  const h = loaded();
  const p = h.pointAt(0.4, 0.6);
  h.clickImage(p.x, p.y);
  type(h, 0, "  Left atrium  ");

  assert.equal(h.api.getMarkers()[0].label, "Left atrium");

  // A copy: mutating what the caller got must not reach into the canvas.
  const taken = h.api.getMarkers();
  taken[0].label = "clobbered";
  taken[0].x = 0.99;
  assert.equal(h.api.getMarkers()[0].label, "Left atrium");
  assert.ok(near(h.api.getMarkers()[0].x, 0.4));
});

test("markInvalid flags rows, and input clears the flag", () => {
  const h = loaded();
  const a = h.pointAt(0.3, 0.3);
  const b = h.pointAt(0.7, 0.7);
  h.clickImage(a.x, a.y);
  h.clickImage(b.x, b.y);
  type(h, 0, "named");

  h.api.markInvalid([1]);
  assert.equal(rowInput(h, 0)._classes.has("ed-invalid"), false, "row 0 is fine");
  assert.equal(rowInput(h, 1)._classes.has("ed-invalid"), true, "row 1 is flagged");

  type(h, 1, "n");
  assert.equal(rowInput(h, 1)._classes.has("ed-invalid"), false, "typing clears it");
});

test("markInvalid tolerates missing and out-of-range indices", () => {
  const h = loaded();
  h.clickImage(h.pointAt(0.5, 0.5).x, h.pointAt(0.5, 0.5).y);
  assert.doesNotThrow(() => h.api.markInvalid());
  assert.doesNotThrow(() => h.api.markInvalid([]));
  assert.doesNotThrow(() => h.api.markInvalid([99]));
});

test("empty list renders a placeholder row", () => {
  const h = loaded();
  assert.equal(h.els.list.childNodes.length, 1);
  assert.ok(h.els.list.childNodes[0]._classes.has("ed-empty-row"));

  h.clickImage(h.pointAt(0.5, 0.5).x, h.pointAt(0.5, 0.5).y);
  assert.equal(h.els.list.childNodes.length, 1);
  assert.ok(h.els.list.childNodes[0]._classes.has("ed-row"), "now a real row");
});

test("rows and dots number from 1 and show prefilled labels", () => {
  const h = loaded({
    markers: [
      { x: 0.2, y: 0.2, label: "first" },
      { x: 0.8, y: 0.8, label: "second" },
    ],
  });

  assert.deepEqual(
    h.els.list.childNodes.map((row) => row.childNodes[0].textContent),
    ["1", "2"],
    "row numbers are 1-based",
  );
  assert.deepEqual(
    [rowInput(h, 0).value, rowInput(h, 1).value],
    ["first", "second"],
    "existing labels appear in the fields",
  );
  assert.deepEqual(
    h.els.markerGroup.childNodes.map(
      (g) => g.childNodes.find((c) => c.tagName === "text").textContent,
    ),
    ["1", "2"],
    "dot labels are 1-based too",
  );
});

test("deleting the selected marker clears the selection", () => {
  const h = loaded();
  const a = h.pointAt(0.3, 0.3);
  h.clickImage(a.x, a.y);
  // Grab it so it is genuinely selected, not merely the most recent.
  h.on(h.els.markerGroup.childNodes[0], "pointerdown", { clientX: a.x, clientY: a.y });
  h.fire("pointerup", { clientX: a.x, clientY: a.y });
  assert.equal(h.state().selected, 0);

  h.els.list.childNodes[0].childNodes
    .find((c) => c._classes.has("ed-row-del"))
    .dispatch("click");

  assert.equal(h.state().selected, -1, "the selection cannot point at a deleted marker");
});

// -------------------------------------------------- the ro:count contract

test("marker count changes emit ro:count", () => {
  const h = loaded();
  h.sent.length = 0;

  h.clickImage(h.pointAt(0.3, 0.3).x, h.pointAt(0.3, 0.3).y);
  h.clickImage(h.pointAt(0.6, 0.6).x, h.pointAt(0.6, 0.6).y);
  assert.deepEqual(counts(h), [1, 2], "placing reports the new count");

  h.els.list.childNodes[0].childNodes
    .find((c) => c._classes.has("ed-row-del"))
    .dispatch("click");
  assert.deepEqual(counts(h), [1, 2, 1], "deleting reports it too");

  h.sent.length = 0;
  h.api.setImage(PNG, [{ x: 0.5, y: 0.5, label: "a" }]);
  h.load();
  assert.deepEqual(counts(h), [1], "and so does loading a new image");
});

// ------------------------------------------------------- untrusted prefill

test("setImage sanitises prefill markers", () => {
  // Prefill comes from a note payload, which can be hand-edited or written by
  // an older version, so it is not to be trusted.
  const h = buildEditor();
  h.api.setImage(PNG, [
    { x: 5, y: -3, label: "out of range" },
    { x: "abc", y: null, label: null },
    { x: 0.5, y: 0.5 },
    // A number rather than a string: without the coercion this reaches
    // getMarkers()'s .trim() and throws, which would break Save outright.
    { x: 0.25, y: 0.75, label: 42 },
  ]);
  h.load();

  assert.deepEqual(plain(h.api.getMarkers()), [
    { x: 1, y: 0, label: "out of range" },
    { x: 0, y: 0, label: "" },
    { x: 0.5, y: 0.5, label: "" },
    { x: 0.25, y: 0.75, label: "42" },
  ]);
});

test("setImage ignores a non-array prefill", () => {
  const h = buildEditor();
  assert.doesNotThrow(() => h.api.setImage(PNG, "not an array"));
  h.load();
  assert.equal(h.api.getMarkers().length, 0);
});

// ------------------------------------------------------------- zoom limits

test("zoom is clamped to MAX_ZOOM on every route", () => {
  // clampZoom is unit-tested, but nothing proved it was wired into the paths
  // that change the zoom.
  const h = loaded();
  h.els.stage.focus();
  for (let i = 0; i < 40; i += 1) h.key("+");
  assert.equal(h.state().zoom, 8, "+ cannot climb past the maximum");

  for (let i = 0; i < 40; i += 1) h.wheel(400, 300, -200);
  assert.equal(h.state().zoom, 8, "nor can the wheel");

  for (let i = 0; i < 40; i += 1) h.key("-");
  assert.equal(h.state().zoom, 1, "and - stops at the fitted view");
});

test("setZoom clamps out-of-range and non-numeric input", () => {
  // The value arrives from config.json, which the user can edit by hand.
  for (const [given, expected] of [
    [500, 8], // absurdly large clamps to the ceiling
    [-10, 1],
    [0, 1],
    ["4", 4], // a numeric string is still a usable level
    ["nonsense", 1],
    // Non-finite is treated as junk rather than as "infinitely zoomed", falling
    // back to the fitted view; the same call the Python side makes.
    [NaN, 1],
    [Infinity, 1],
    [-Infinity, 1],
    [null, 1],
    [undefined, 1],
  ]) {
    const h = loaded();
    h.api.setZoom(given);
    assert.equal(h.state().zoom, expected, `setZoom(${String(given)})`);
  }
});

test("zoom-in button is disabled at MAX_ZOOM", () => {
  const h = loaded();
  h.els.stage.focus();
  assert.equal(h.els.zoomIn.disabled, false);

  h.api.setZoom(8);
  assert.equal(h.els.zoomIn.disabled, true, "nothing left to zoom into");
  assert.equal(h.els.zoomOut.disabled, false);
  assert.equal(h.els.zoomFit.disabled, false);
});

// ------------------------------------------------- pan bounds when letterboxed

test("clampPan accounts for a letterboxed image's layout offset", () => {
  // A letterboxed image sits inset from the stage's origin. Every other pan
  // test uses a stage-filling image, where that offset is zero and a clamp that
  // ignored it would look correct.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400, height: 600 } });
  h.api.setZoom(4); // 1600x2400 of content in an 800x600 viewport

  for (const [x, y] of [[9000, 9000], [-9000, -9000], [9000, -9000]]) {
    h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
    h.fire("pointermove", { clientX: x, clientY: y });
    h.fire("pointerup", { clientX: x, clientY: y });

    const r = h.els.img.getBoundingClientRect();
    const v = h.visibleRect();
    assert.ok(r.left <= v.left + 1e-9, `left gap panning to ${x},${y}`);
    assert.ok(r.right >= v.right - 1e-9, `right gap panning to ${x},${y}`);
    assert.ok(r.top <= v.top + 1e-9, `top gap panning to ${x},${y}`);
    assert.ok(r.bottom >= v.bottom - 1e-9, `bottom gap panning to ${x},${y}`);
  }
});

test("centrePan centres a letterboxed image when zoomed", () => {
  // At fit zoom clampPan pins the pan itself, which masks whether centrePan
  // accounts for the image's inset. Zoomed in, it is centrePan that decides.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400, height: 600 } });
  h.api.setZoom(4);

  const r = h.els.img.getBoundingClientRect();
  const v = h.visibleRect();
  assert.ok(
    near(r.left + r.width / 2, v.left + v.width / 2, 1e-9),
    `image centre ${r.left + r.width / 2} vs visible centre ${v.left + v.width / 2}`,
  );
});

test("resetZoom re-centres a letterboxed image", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400, height: 600 } });
  h.api.setZoom(4);
  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 40, clientY: 40 });
  h.fire("pointerup", { clientX: 40, clientY: 40 });
  assert.ok(h.state().panX !== 0);

  h.els.stage.focus();
  h.key("0");

  const r = h.els.img.getBoundingClientRect();
  const v = h.visibleRect();
  assert.equal(h.state().zoom, 1);
  assert.ok(
    near(r.left + r.width / 2, v.left + v.width / 2, 1e-9),
    "Fit must re-centre, not just reset the scale",
  );
});

// ------------------------------------------- gestures the mock can now reach

test("marker press with space held pans instead of dragging", () => {
  // Space means "pan" whatever is under the pointer. makeMarkerPointerDown must
  // bail BEFORE stopPropagation, so the press still reaches the stage.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.api.setZoom(2);

  const before = plain(h.api.getMarkers())[0];
  const panBefore = h.state().panX;

  h.els.stage.focus();
  h.key(" ");
  h.on(h.els.markerGroup.childNodes[0], "pointerdown", { button: 0, clientX: p.x, clientY: p.y });
  h.fire("pointermove", { clientX: p.x - 60, clientY: p.y });
  h.release(h.els.img, { button: 0, clientX: p.x - 60, clientY: p.y });
  h.keyUp(" ");

  assert.deepEqual(plain(h.api.getMarkers())[0], before, "the marker must not have moved");
  assert.equal(h.state().panX, panBefore - 60, "the picture panned instead");
});

test("a marker press does not also start a pan", () => {
  // The press has to stop propagating, or the stage would begin a gesture too.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.api.setZoom(2);
  const panBefore = h.state().panX;

  h.on(h.els.markerGroup.childNodes[0], "pointerdown", { button: 0, clientX: p.x, clientY: p.y });
  h.fire("pointermove", { clientX: p.x - 60, clientY: p.y });
  h.fire("pointerup", { clientX: p.x - 60, clientY: p.y });

  assert.equal(h.state().panX, panBefore, "the picture must not have moved");
  assert.ok(h.api.getMarkers()[0].x < 0.5, "only the marker moved");
});

test("isOverImage excludes points clipped outside the stage", () => {
  // Zoomed in, the image overflows the stage and the overflow is clipped away.
  // A release out there is not on anything the user can see, so it must not
  // suppress the click that follows.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);

  const r = h.els.img.getBoundingClientRect();
  const v = h.visibleRect();
  const outside = { x: v.left - 100, y: 300 };
  assert.ok(outside.x > r.left && outside.x < r.right, "precondition: inside the image rect");
  assert.ok(outside.x < v.left, "precondition: outside the visible area");

  h.els.stage.focus();
  h.key(" ");
  h.on(h.els.stage, "pointerdown", { button: 0, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: outside.x, clientY: outside.y });
  // Released out in the clipped region: the browser dispatches no click on the
  // image there, so end the gesture without one.
  h.fire("pointerup", { clientX: outside.x, clientY: outside.y });
  h.keyUp(" ");

  const q = h.pointAt(0.5, 0.5);
  h.on(h.els.img, "pointerdown", { button: 0, clientX: q.x, clientY: q.y });
  h.release(h.els.img, { button: 0, clientX: q.x, clientY: q.y });
  assert.equal(h.api.getMarkers().length, 1, "the next click must still place a marker");
});

test("gesture teardown stops responding to pointermove", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.api.setZoom(2);

  // A pan that has ended must not keep panning.
  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 380, clientY: 300 });
  h.release(h.els.stage, { button: 1, clientX: 380, clientY: 300 });
  const afterPan = h.state().panX;
  h.fire("pointermove", { clientX: 100, clientY: 300 });
  assert.equal(h.state().panX, afterPan, "a stale pan listener kept panning");

  // And a drag that has ended must not keep dragging.
  h.on(h.els.markerGroup.childNodes[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.fire("pointermove", { clientX: p.x + 10, clientY: p.y });
  h.fire("pointerup", { clientX: p.x + 10, clientY: p.y });
  const afterDrag = plain(h.api.getMarkers())[0];
  h.fire("pointermove", { clientX: h.pointAt(0.9, 0.9).x, clientY: h.pointAt(0.9, 0.9).y });
  assert.deepEqual(
    plain(h.api.getMarkers())[0],
    afterDrag,
    "a stale drag listener kept moving it",
  );
});

test("arrow keys move in the direction they name", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.on(h.els.markerGroup.childNodes[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.fire("pointerup", { clientX: p.x, clientY: p.y });

  const at = () => plain(h.api.getMarkers())[0];
  const start = at();
  h.key("ArrowUp");
  assert.ok(at().y < start.y, "up decreases y");
  h.key("ArrowDown");
  assert.ok(near(at().y, start.y), "down undoes it");
  h.key("ArrowLeft");
  assert.ok(at().x < start.x, "left decreases x");
  h.key("ArrowRight");
  assert.ok(near(at().x, start.x), "right undoes it");
});

// ----------------------------------------------------- browser-level guards

test("ctrl+wheel is preventDefaulted outside the stage too", () => {
  // QtWebEngine reads ctrl+wheel as its own page zoom, which would scale the
  // whole editor out from under every coordinate on it.
  const h = loaded();
  let prevented = 0;
  const spy = {
    preventDefault: () => {
      prevented += 1;
    },
  };

  h.on(h.els.list, "wheel", Object.assign({ deltaY: -100, deltaMode: 0, ctrlKey: true }, spy));
  assert.ok(prevented > 0, "a ctrl+wheel over the label panel must still be swallowed");

  prevented = 0;
  h.on(h.els.list, "wheel", Object.assign({ deltaY: -100, deltaMode: 0 }, spy));
  assert.equal(prevented, 0, "but a plain wheel there is left alone, so the list scrolls");
});

test("contextmenu is preventDefaulted on the stage", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);
  let prevented = 0;

  h.on(h.els.stage, "pointerdown", { button: 2, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 360, clientY: 280 });
  h.release(h.els.stage, {
    button: 2,
    clientX: 360,
    clientY: 280,
    preventDefault: () => {
      prevented += 1;
    },
  });

  assert.ok(prevented > 0, "the menu would have covered the canvas mid-pan");
});

test("ResizeObserver re-clamps the pan", () => {
  // The production route: a panel relayout or the image finishing layout
  // resizes the stage without the window ever firing `resize`.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  assert.deepEqual(
    h.observedNodes().map((n) => n.attributes.id),
    ["ed-stage"],
    "the stage is what gets observed",
  );

  h.api.setZoom(2);
  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 100, clientY: 100 });
  h.fire("pointerup", { clientX: 100, clientY: 100 });
  assert.ok(h.state().panX < 0);

  h.resizeStage(2000, 1600);
  h.triggerResizeObserver();
  h.runTimers();

  const r = h.els.img.getBoundingClientRect();
  const v = h.visibleRect();
  assert.ok(near(r.left + r.width / 2, v.left + v.width / 2, 1e-9), "re-centred");
});

test("resetZoom reports the fitted level", () => {
  const h = loaded();
  h.els.stage.focus();
  h.key("+");
  h.runTimers();
  h.sent.length = 0;

  h.key("0");
  h.runTimers();
  const zooms = h.sent.filter((m) => m.startsWith("ro:zoom:")).map((m) => Number(m.slice(8)));
  assert.ok(zooms.length > 0, "returning to Fit must be saved, not just applied");
  assert.equal(zooms[zooms.length - 1], 1);
});

// ------------------------------------------------- the remaining fine detail

test("layoutSize measures sub-pixel, not from rounded offsetWidth", () => {
  // offsetWidth is a rounded integer; the rendered box is not. Half a pixel of
  // disagreement becomes four at 8x; enough to strand a sliver of the image
  // out of reach. A fractional image size is what makes the two differ.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400.4, height: 300.6 } });
  h.api.setZoom(8);

  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: -9000, clientY: -9000 });
  h.fire("pointerup", { clientX: -9000, clientY: -9000 });

  // Panned hard left, the image's right edge should come to rest exactly on the
  // visible right edge. Measuring from the rounded offsetWidth stops it short.
  const r = h.els.img.getBoundingClientRect();
  const v = h.visibleRect();
  assert.ok(
    near(r.right, v.right, 1e-9),
    `the far edge stops ${(r.right - v.right).toFixed(2)}px out of reach`,
  );
});

test("pointToNormalized clamps a click past the image edge", () => {
  // The click target is the image, so the pointer is over it, but rounding and
  // the border mean the computed fraction can sit a hair outside 0..1, and a
  // marker outside the image is rejected by the domain layer on save.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 400, height: 300 } });
  const r = h.els.img.getBoundingClientRect();

  h.clickImage(r.left - 40, r.top - 40);
  h.clickImage(r.right + 40, r.bottom + 40);

  for (const m of plain(h.api.getMarkers())) {
    assert.ok(m.x >= 0 && m.x <= 1, `x ${m.x} is outside the image`);
    assert.ok(m.y >= 0 && m.y <= 1, `y ${m.y} is outside the image`);
  }
});

test("non-primary marker press pans instead of dragging", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  h.api.setZoom(2);

  const before = plain(h.api.getMarkers())[0];
  const panBefore = h.state().panX;

  h.on(h.els.markerGroup.childNodes[0], "pointerdown", { button: 1, clientX: p.x, clientY: p.y });
  h.fire("pointermove", { clientX: p.x - 60, clientY: p.y });
  h.fire("pointerup", { clientX: p.x - 60, clientY: p.y });

  assert.deepEqual(plain(h.api.getMarkers())[0], before, "the marker must not have moved");
  assert.equal(h.state().panX, panBefore - 60, "the picture panned instead");
});

test("right button pans", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);
  const before = h.state().panX;

  h.on(h.els.stage, "pointerdown", { button: 2, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 340, clientY: 300 });
  h.fire("pointerup", { clientX: 340, clientY: 300 });

  assert.equal(h.state().panX, before - 60, "a right-drag must actually pan");
});

test("deleting a dragged marker cancels the drag", () => {
  // The drag holds an index into an array that is about to shrink; carrying on
  // would write past the end of it.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const a = h.pointAt(0.3, 0.3);
  const b = h.pointAt(0.7, 0.7);
  h.clickImage(a.x, a.y);
  h.clickImage(b.x, b.y);

  h.on(h.els.markerGroup.childNodes[1], "pointerdown", { clientX: b.x, clientY: b.y });
  // The row disappears from under the drag.
  h.els.list.childNodes[1].childNodes
    .find((c) => c._classes.has("ed-row-del"))
    .dispatch("click");

  assert.doesNotThrow(() => {
    h.fire("pointermove", { clientX: h.pointAt(0.9, 0.9).x, clientY: h.pointAt(0.9, 0.9).y });
  });
  const left = plain(h.api.getMarkers());
  assert.equal(left.length, 1);
  assert.ok(near(left[0].x, 0.3), "the surviving marker must not have been dragged");
});

test("setImage cancels a pan in flight", () => {
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.api.setZoom(2);
  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  h.fire("pointermove", { clientX: 380, clientY: 300 });

  h.api.setImage(PNG, null); // "Replace image…" mid-gesture
  h.load();
  const after = h.state().panX;

  h.fire("pointermove", { clientX: 100, clientY: 300 });
  assert.equal(h.state().panX, after, "the abandoned pan kept panning the new image");
});

test("gesture teardown removes its window listeners", () => {
  // Each handler guards on its own gesture being live, so a leak has no
  // symptom; it just accumulates for as long as the dialog is open.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  const p = h.pointAt(0.5, 0.5);
  h.clickImage(p.x, p.y);
  const baseline = h.listenerCount("pointermove");

  for (let i = 0; i < 5; i += 1) {
    h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
    h.fire("pointermove", { clientX: 390, clientY: 300 });
    h.fire("pointerup", { clientX: 390, clientY: 300 });

    h.on(h.els.markerGroup.childNodes[0], "pointerdown", { clientX: p.x, clientY: p.y });
    h.fire("pointermove", { clientX: p.x + 5, clientY: p.y });
    h.fire("pointerup", { clientX: p.x + 5, clientY: p.y });
  }

  assert.equal(
    h.listenerCount("pointermove"),
    baseline,
    "ten finished gestures left listeners behind",
  );
});

test("wheel deltaMode line and page scale to the pixel equivalent", () => {
  const inPixels = loaded();
  inPixels.wheel(400, 300, -48, { deltaMode: 0 });

  const inLines = loaded();
  inLines.wheel(400, 300, -3, { deltaMode: 1 }); // 3 lines x 16px

  assert.ok(inLines.state().zoom > 1, "a line-mode wheel must zoom at all");
  assert.ok(
    near(inLines.state().zoom, inPixels.state().zoom, 1e-9),
    `lines ${inLines.state().zoom} vs pixels ${inPixels.state().zoom}`,
  );

  const inPages = loaded();
  inPages.wheel(400, 300, -1, { deltaMode: 2 });
  assert.ok(inPages.state().zoom > inLines.state().zoom, "a page is a bigger step than a line");
});

test("setImage clears spaceHeld", () => {
  // Replacing the picture is a fresh start; carrying pan mode across it would
  // mean the first drag on the new image moved the picture, not the marker.
  const h = loaded({ stage: { width: 800, height: 600 }, image: { width: 800, height: 600 } });
  h.els.stage.focus();
  h.key(" ");
  assert.ok(h.els.stage._classes.has("ed-pan-ready"), "precondition: Space is held");

  h.api.setImage(PNG, [{ x: 0.5, y: 0.5, label: "one" }]);
  h.load();
  assert.equal(h.els.stage._classes.has("ed-pan-ready"), false, "pan mode must be cleared");

  const p = h.pointAt(0.5, 0.5);
  const panBefore = h.state().panX;
  h.on(h.els.markerGroup.childNodes[0], "pointerdown", { button: 0, clientX: p.x, clientY: p.y });
  h.fire("pointermove", { clientX: h.pointAt(0.7, 0.5).x, clientY: p.y });
  h.fire("pointerup", { clientX: h.pointAt(0.7, 0.5).x, clientY: p.y });

  assert.equal(h.state().panX, panBefore, "the picture must not have panned");
  assert.ok(h.api.getMarkers()[0].x > 0.6, "the marker moved instead");
});

// ---- drag, pan, nudge and crosshair -----------------------------------------
//
// These functions had no mutation entry at all: setPan, startDrag, onDragMove,
// onDragEnd, startPan, nudgeSelected, renderCrosshair and onStageResize were 26
// of marker.js's 65 functions that nothing pinned.

const TWO = [
  { x: 0.25, y: 0.25, label: "one" },
  { x: 0.75, y: 0.75, label: "two" },
];

test("dragging a marker moves that marker, not the first one", () => {
  const h = loaded({ markers: TWO });
  const from = h.pointAt(0.75, 0.75);
  const to = h.pointAt(0.5, 0.5);

  h.on(h.groups()[1], "pointerdown", { clientX: from.x, clientY: from.y });
  h.fire("pointermove", { clientX: to.x, clientY: to.y });
  h.release(h.els.stage, { button: 0, clientX: to.x, clientY: to.y });

  const markers = plain(h.api.getMarkers());
  assert.ok(near(markers[0].x, 0.25, 1e-6) && near(markers[0].y, 0.25, 1e-6),
    `marker one moved to (${markers[0].x}, ${markers[0].y}); the wrong one was dragged`);
  assert.ok(near(markers[1].x, 0.5, 1e-6) && near(markers[1].y, 0.5, 1e-6),
    "marker two did not follow the pointer");
});

test("a second finger does not steer an in-flight drag", () => {
  // Pointer events interleave on a touch screen. A move carrying a different
  // pointerId belongs to another finger and must be ignored, or a two-finger
  // gesture would fling the marker being dragged.
  const h = loaded({ markers: TWO });
  const from = h.pointAt(0.25, 0.25);

  h.on(h.groups()[0], "pointerdown", { pointerId: 1, clientX: from.x, clientY: from.y });
  const other = h.pointAt(0.9, 0.9);
  h.fire("pointermove", { pointerId: 2, clientX: other.x, clientY: other.y });

  let markers = plain(h.api.getMarkers());
  assert.ok(near(markers[0].x, 0.25, 1e-6), "another pointer's move dragged the marker");

  // ...and nor does its release end the drag.
  h.fire("pointerup", { pointerId: 2, clientX: other.x, clientY: other.y });
  const to = h.pointAt(0.4, 0.4);
  h.fire("pointermove", { pointerId: 1, clientX: to.x, clientY: to.y });
  markers = plain(h.api.getMarkers());
  assert.ok(near(markers[0].x, 0.4, 1e-6),
    "another pointer's release ended the drag early");
});

test("the stage is marked while panning and unmarked after", () => {
  // The class is what switches the cursor and suppresses hover affordances.
  const h = loaded({ markers: TWO });
  h.api.setZoom(4);
  assert.ok(!h.els.stage._classes.has("ed-panning"), "not panning yet");

  h.on(h.els.stage, "pointerdown", { button: 1, clientX: 400, clientY: 300 });
  assert.ok(h.els.stage._classes.has("ed-panning"), "a pan should mark the stage");

  h.fire("pointerup", { clientX: 400, clientY: 300 });
  assert.ok(!h.els.stage._classes.has("ed-panning"), "the mark outlived the pan");
});

test("a nudge cannot push a marker off the image", () => {
  const h = loaded({ markers: [{ x: 0.999, y: 0.999, label: "edge" }] });
  h.on(h.groups()[0], "pointerdown", { clientX: h.pointAt(0.999, 0.999).x, clientY: h.pointAt(0.999, 0.999).y });
  h.release(h.els.stage, { button: 0, clientX: h.pointAt(0.999, 0.999).x, clientY: h.pointAt(0.999, 0.999).y });

  for (let i = 0; i < 20; i += 1) {
    h.key("ArrowRight", { shiftKey: true });
    h.key("ArrowDown", { shiftKey: true });
  }

  const [marker] = plain(h.api.getMarkers());
  assert.ok(marker.x <= 1 && marker.y <= 1,
    `nudging pushed the marker to (${marker.x}, ${marker.y}), off the image`);
  assert.ok(marker.x >= 0 && marker.y >= 0);
});

test("a nudge redraws the marker where it moved to", () => {
  const h = loaded({ markers: [{ x: 0.5, y: 0.5, label: "mid" }] });
  const p = h.pointAt(0.5, 0.5);
  h.on(h.groups()[0], "pointerdown", { clientX: p.x, clientY: p.y });
  h.release(h.els.stage, { button: 0, clientX: p.x, clientY: p.y });
  const before = h.dots()[0];

  for (let i = 0; i < 10; i += 1) h.key("ArrowRight", { shiftKey: true });

  const after = h.dots()[0];
  assert.ok(after.x > before.x + 1,
    `the dot stayed at x=${before.x} while the marker moved, so the overlay was not redrawn`);
});

test("the crosshair follows the pointer and hides while panning", () => {
  const h = loaded({ markers: TWO });
  const p = h.pointAt(0.5, 0.5);
  h.on(h.els.stage, "pointermove", { clientX: p.x, clientY: p.y });
  assert.equal(h.crosshairLines(), 2, "a horizontal and a vertical guide");

  h.api.setZoom(4);
  h.on(h.els.stage, "pointerdown", { button: 1, clientX: p.x, clientY: p.y });
  assert.equal(h.crosshairLines(), 0,
    "the crosshair should hide while the picture is being moved, not the point chosen");

  h.fire("pointerup", { clientX: p.x, clientY: p.y });
  h.on(h.els.stage, "pointermove", { clientX: p.x, clientY: p.y });
  assert.equal(h.crosshairLines(), 2, "the crosshair should come back after the pan");
});

test("the crosshair is drawn in overlay coordinates", () => {
  // The overlay sits one border-pixel inside the stage, so client coordinates
  // used verbatim would put the guides off by that much at every zoom level.
  const h = loaded({ markers: TWO });
  const p = h.pointAt(0.25, 0.75);
  h.on(h.els.stage, "pointermove", { clientX: p.x, clientY: p.y });

  const base = h.visibleRect();
  const lines = h.els.crosshair.childNodes;
  const horizontal = lines.find((l) => Number(l.attributes.y1) === Number(l.attributes.y2));
  const vertical = lines.find((l) => Number(l.attributes.x1) === Number(l.attributes.x2));
  assert.ok(horizontal && vertical, "both guides are drawn");
  assert.ok(near(Number(horizontal.attributes.y1), p.y - base.top, 1e-6),
    "the horizontal guide is not at the pointer, in overlay space");
  assert.ok(near(Number(vertical.attributes.x1), p.x - base.left, 1e-6),
    "the vertical guide is not at the pointer, in overlay space");
});

test("a burst of resizes is coalesced into one pass", () => {
  const h = loaded({ markers: TWO });
  h.api.setZoom(4);
  h.runTimers();

  // Dragging a dialog edge fires this continuously; each pass re-measures and
  // re-renders, so doing the work per event makes the resize crawl.
  for (let i = 0; i < 5; i += 1) h.triggerResizeObserver();
  assert.equal(h.runTimers(), 1, "five resize events should schedule one pass");

  // ...and the next burst must schedule again. Failing to release the pending
  // frame would coalesce the resize away permanently, so the pan bounds would
  // never be re-measured after the first resize of the session.
  for (let i = 0; i < 3; i += 1) h.triggerResizeObserver();
  assert.equal(h.runTimers(), 1, "a later burst scheduled no pass at all");

  // Coalescing is an optimisation, not a licence to skip the re-bound.
  const markers = plain(h.api.getMarkers());
  assert.ok(near(markers[0].x, 0.25, 1e-6) && near(markers[0].y, 0.25, 1e-6));
});
