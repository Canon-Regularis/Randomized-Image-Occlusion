/*
 * Editor canvas. Runs in the dialog's AnkiWebView.
 *
 * The user drops numbered markers on an image; each marker is one structure,
 * and one future card. Coordinates are stored normalized (0..1 of the image),
 * so they are independent of both display resolution and zoom level.
 *
 * Zoom is a CSS transform on the image; the SVG overlay is not transformed. A
 * transform does not affect layout boxes, so offsetLeft/offsetWidth give
 * un-zoomed geometry (used for pan bounds) and getBoundingClientRect() gives
 * on-screen geometry (used for pointer mapping). Marker dots are drawn in
 * overlay coordinates, so they keep a constant on-screen size at any zoom.
 *
 * Python <-> JS contract:
 *   JS  -> Py : pycmd("ro:ready")            once the page is interactive
 *               pycmd("ro:count:<n>")        whenever the marker count changes
 *               pycmd("ro:zoom:<z>")         throttled, whenever zoom changes
 *               pycmd("ro:textfocus:<0|1>")  when a label field gains/loses focus,
 *                                            so Ctrl+V can mean "paste text" there
 *               pycmd("ro:broken:<0|1>")     when the image starts or stops being
 *                                            unloadable, so a paste over labels can
 *                                            be confirmed rather than silent
 *   Py  -> JS : ROEditor.setImage(dataUrl, markers?)
 *                                            show an image; markers (optional,
 *                                            [{x, y, label}, ...]) pre-populate
 *                                            it for editing, else it starts empty
 *               ROEditor.getMarkers()        -> [{x, y, label}, ...]
 *               ROEditor.markInvalid([i])    flag rows that need a label
 *               ROEditor.setZoom(z)          restore the remembered zoom level
 */
window.ROEditor = (function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";

  // 1x is "fitted", i.e. exactly how the image is laid out with no transform at
  // all, so the editor is pixel-identical to its pre-zoom self until the user
  // zooms. Going below it would only add empty space around an image that is
  // already fully visible, so MIN_ZOOM is the fit.
  var MIN_ZOOM = 1;
  var MAX_ZOOM = 8;
  var ZOOM_STEP = 1.25;
  // Multiplier per pixel of wheel delta. Continuous rather than notched so a
  // precision trackpad, which reports many small deltas, moves smoothly.
  var WHEEL_RATE = 1.0015;
  var WHEEL_LINE_PX = 16;
  var WHEEL_PAGE_PX = 400;
  var ZOOM_EPSILON = 0.0005;
  var ZOOM_NOTIFY_MS = 250;
  var REVEAL_MARGIN = 24;

  var markers = [];
  // Active marker drag, or null: { index, pointerId, moved }.
  var drag = null;
  // Set briefly when a drag ends so the trailing image "click" (if the platform
  // synthesises one) does not drop a spurious new marker.
  var suppressNextImageClick = false;

  // --- view state ---
  var zoom = 1;
  var panX = 0;
  var panY = 0;
  // Active pan gesture, or null: { pointerId, startX, startY, originX, originY, moved }.
  var pan = null;
  // Index of the marker the arrow keys nudge, or -1.
  var selected = -1;
  var spaceHeld = false;
  // Last pointer position over the stage, for the crosshair guides.
  var pointerClient = null;
  var zoomTimer = null;
  var zoomPending = false;
  // Whether a label field currently has focus. Reported to Python so its
  // window-wide Ctrl+V can step aside and let the field paste text instead.
  var textFocused = false;
  //: Set when the <img> reports an error. The markers are deliberately KEPT --
  //: on the Browser edit path they are the only surviving record of the note --
  //: but nothing can be saved without a picture to attach them to, so the count
  //: the dialog grades Save on is reported as zero until a good image arrives.
  var imageBroken = false;
  // The zoom currently written into the DOM, which is what the image's measured
  // rect reflects. setPan runs after `zoom` has been updated but before the new
  // transform is applied, so it needs the old one to recover the layout size.
  var appliedZoom = 1;
  var resizeFrame = null;

  function el(id) {
    return document.getElementById(id);
  }

  function send(message) {
    if (typeof pycmd === "function") {
      pycmd(message);
    }
  }

  function notifyCount() {
    send("ro:count:" + markers.length);
  }

  /**
   * Whether the stage is showing a usable picture.
   *
   * Its own message, because reporting a broken image as "zero markers" was a
   * lie with a second victim: replace_image_prompt() asks "the N markers you
   * have placed will be removed" only when N > 0, so a zero disarmed the one
   * confirmation standing between a stray Ctrl+V and the loss of every label.
   */
  function notifyBroken() {
    send("ro:broken:" + (imageBroken ? "1" : "0"));
  }

  // ---- pure geometry (exported on _internals for tests) ---------------------

  function clamp01(v) {
    return Math.max(0, Math.min(1, v));
  }

  function clampZoom(z) {
    if (typeof z !== "number" || !isFinite(z)) return MIN_ZOOM;
    return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));
  }

  /** A wheel delta in CSS pixels, whatever unit the platform reported it in. */
  function normalizeWheelDelta(delta, mode) {
    if (typeof delta !== "number" || !isFinite(delta)) return 0;
    if (mode === 1) return delta * WHEEL_LINE_PX;
    if (mode === 2) return delta * WHEEL_PAGE_PX;
    return delta;
  }

  /**
   * The pan that keeps a point fixed on screen while the zoom changes.
   *
   * `offset` is the point's distance from the image's *rendered* left/top edge,
   * so the whole calculation is a delta between two getBoundingClientRect
   * readings and never has to know where the stage's border or padding is.
   */
  function zoomAt(offset, currentPan, currentZoom, nextZoom) {
    return currentPan + offset * (1 - nextZoom / currentZoom);
  }

  /**
   * Keep the scaled image covering the viewport: when it is larger, bound the
   * pan so no gap can open at either edge; when it is not (only possible at
   * MIN_ZOOM), pin it to its centred layout position, which is a pan of 0.
   *
   * Applied per axis, so an image that overflows in one direction only still
   * pans freely in that direction.
   */
  function clampPan(value, content, viewport, layout) {
    if (content >= viewport) {
      var bounded = Math.max(viewport - layout - content, Math.min(-layout, value));
      // `-layout` is a negative zero when the image sits at the origin; hand
      // back a plain 0 so callers comparing the pan to zero need not know.
      return bounded === 0 ? 0 : bounded;
    }
    return (viewport - content) / 2 - layout;
  }

  /** Arrow-key nudge distance, in screen pixels. */
  function nudgeStep(bigStep) {
    return bigStep ? 10 : 1;
  }

  // ---- view helpers ---------------------------------------------------------

  /** True once an image is loaded and has a laid-out size. */
  function imageReady() {
    var img = el("ed-img");
    if (!img || img.style.display === "none") return false;
    var rect = img.getBoundingClientRect();
    return !!(rect.width && rect.height);
  }

  function schedule(callback) {
    if (typeof window.requestAnimationFrame === "function") {
      return window.requestAnimationFrame(callback);
    }
    return window.setTimeout(callback, 16);
  }

  function setStageClass(name, on) {
    var stage = el("ed-stage");
    if (stage && stage.classList) stage.classList.toggle(name, on);
  }

  function focusStage() {
    var stage = el("ed-stage");
    if (stage && typeof stage.focus === "function") stage.focus();
  }

  function applyTransform() {
    var img = el("ed-img");
    if (img) {
      img.style.transform =
        "translate(" + panX + "px, " + panY + "px) scale(" + zoom + ")";
      appliedZoom = zoom;
    }
    updateZoomUi();
    renderOverlay();
    renderCrosshair();
  }

  function setPan(x, y) {
    var img = el("ed-img");
    var stage = el("ed-stage");
    if (!img || !stage) return;
    var base = layoutSize(img);
    panX = clampPan(x, base.width * zoom, stage.clientWidth, img.offsetLeft);
    panY = clampPan(y, base.height * zoom, stage.clientHeight, img.offsetTop);
    applyTransform();
  }

  /**
   * The image's un-zoomed size, sub-pixel.
   *
   * offsetWidth/offsetHeight are unaffected by the transform but are rounded to
   * integers, while everything else here measures with getBoundingClientRect().
   * At 8x, half a pixel of disagreement becomes four, leaving a sliver of the
   * image unreachable or opening a gap at its edge. Dividing the measured rect
   * by the zoom currently applied keeps the pan bounds in the same space as the
   * drawing and hit-testing.
   */
  function layoutSize(img) {
    var rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height || !appliedZoom) {
      return { width: img.offsetWidth, height: img.offsetHeight };
    }
    return { width: rect.width / appliedZoom, height: rect.height / appliedZoom };
  }

  function centrePan() {
    var img = el("ed-img");
    var stage = el("ed-stage");
    if (!img || !stage) return;
    var base = layoutSize(img);
    setPan(
      (stage.clientWidth - base.width * zoom) / 2 - img.offsetLeft,
      (stage.clientHeight - base.height * zoom) / 2 - img.offsetTop
    );
  }

  function zoomTo(next, clientX, clientY) {
    var img = el("ed-img");
    var stage = el("ed-stage");
    if (!img || !stage || !imageReady()) return;
    next = clampZoom(next);
    if (Math.abs(next - zoom) < ZOOM_EPSILON) return;
    var rect = img.getBoundingClientRect();
    // Buttons and keys have no cursor to anchor on, so they anchor on the
    // middle of what is actually visible: the stage, not the image, which may
    // be mostly off-screen when zoomed.
    var base = stage.getBoundingClientRect();
    var ax = clientX == null ? base.left + base.width / 2 : clientX;
    var ay = clientY == null ? base.top + base.height / 2 : clientY;
    var nextX = zoomAt(ax - rect.left, panX, zoom, next);
    var nextY = zoomAt(ay - rect.top, panY, zoom, next);
    zoom = next;
    setPan(nextX, nextY);
    notifyZoom();
  }

  function stepZoom(direction) {
    zoomTo(direction > 0 ? zoom * ZOOM_STEP : zoom / ZOOM_STEP, null, null);
  }

  function resetZoom() {
    if (Math.abs(zoom - MIN_ZOOM) < ZOOM_EPSILON) return;
    zoom = MIN_ZOOM;
    centrePan();
    notifyZoom();
  }

  function notifyZoom() {
    updateZoomUi();
    // Leading-edge throttle. A wheel gesture produces dozens of changes and
    // the config needs only the settled level, but the first change is reported
    // immediately so a close mid-gesture still persists a level.
    if (zoomTimer !== null) {
      zoomPending = true; // still inside the window; report the settled level later
      return;
    }
    send("ro:zoom:" + zoom.toFixed(4));
    zoomTimer = window.setTimeout(function () {
      zoomTimer = null;
      if (!zoomPending) return;
      zoomPending = false;
      notifyZoom();
    }, ZOOM_NOTIFY_MS);
  }

  function updateZoomUi() {
    var level = el("ed-zoom-level");
    if (level) level.textContent = Math.round(zoom * 100) + "%";
    var atMin = zoom <= MIN_ZOOM + ZOOM_EPSILON;
    var atMax = zoom >= MAX_ZOOM - ZOOM_EPSILON;
    setDisabled(el("ed-zoom-out"), atMin);
    setDisabled(el("ed-zoom-fit"), atMin);
    setDisabled(el("ed-zoom-in"), atMax);
  }

  // Takes the element, not an id, so that every id literal in this file sits
  // inside a lookup the cross-file invariant test can find.
  function setDisabled(button, disabled) {
    if (button) button.disabled = disabled;
  }

  /** Pan just enough to bring marker `index` inside the visible stage. */
  function revealMarker(index) {
    var img = el("ed-img");
    var stage = el("ed-stage");
    if (!img || !stage || !imageReady()) return;
    if (index < 0 || index >= markers.length) return;
    var rect = img.getBoundingClientRect();
    var base = stage.getBoundingClientRect();
    var mx = rect.left + markers[index].x * rect.width;
    var my = rect.top + markers[index].y * rect.height;
    var dx = 0;
    var dy = 0;
    if (mx < base.left + REVEAL_MARGIN) dx = base.left + REVEAL_MARGIN - mx;
    else if (mx > base.right - REVEAL_MARGIN) dx = base.right - REVEAL_MARGIN - mx;
    if (my < base.top + REVEAL_MARGIN) dy = base.top + REVEAL_MARGIN - my;
    else if (my > base.bottom - REVEAL_MARGIN) dy = base.bottom - REVEAL_MARGIN - my;
    if (dx || dy) setPan(panX + dx, panY + dy);
  }

  // ---- rendering ------------------------------------------------------------

  function svgEl(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    if (attrs) {
      for (var key in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, key)) {
          node.setAttribute(key, attrs[key]);
        }
      }
    }
    return node;
  }

  function clear(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  /**
   * The overlay's own rect *is* the coordinate system its children are drawn
   * in (it is absolutely positioned at the stage's padding box), so measuring
   * against it needs no knowledge of the stage's border width.
   */
  function overlayRect() {
    var svg = el("ed-overlay");
    return svg ? svg.getBoundingClientRect() : null;
  }

  function renderOverlay() {
    var img = el("ed-img");
    var group = el("ed-markers");
    if (!group) return;
    clear(group);
    if (!imageReady()) return;
    var base = overlayRect();
    if (!base) return;

    // The image's rect reflects the zoom transform, so normalized coordinates
    // land on what is actually on screen at any zoom. Using getBoundingClientRect
    // on both sides also removes the sub-pixel drift the old offsetLeft/
    // clientWidth version had against pointToNormalized().
    var rect = img.getBoundingClientRect();
    var ox = rect.left - base.left;
    var oy = rect.top - base.top;
    var w = rect.width;
    var h = rect.height;

    markers.forEach(function (marker, index) {
      var cx = ox + marker.x * w;
      var cy = oy + marker.y * h;

      // One <g> per marker so it is a single grab target. The overlay itself is
      // pointer-transparent (see marker.css) so clicks on bare image add markers;
      // each group re-enables pointer events so its dot can be dragged.
      var classes = "ed-marker";
      if (drag !== null && drag.index === index) classes += " ed-marker-dragging";
      if (index === selected) classes += " ed-marker-selected";
      var node = svgEl("g", { class: classes });
      // Transparent, generously sized hit area so the small dot is easy to grab.
      // These radii are screen pixels and deliberately do NOT scale with the
      // zoom: the overlay sits outside the transform, so a dot is exactly as
      // easy to hit at 8x as at 1x.
      node.appendChild(svgEl("circle", { class: "ed-marker-hit", cx: cx, cy: cy, r: 16 }));
      node.appendChild(svgEl("circle", { class: "ed-marker-dot", cx: cx, cy: cy, r: 11 }));
      var text = svgEl("text", {
        class: "ed-marker-label",
        x: cx,
        y: cy,
        "text-anchor": "middle",
        "dominant-baseline": "central",
      });
      text.textContent = String(index + 1);
      node.appendChild(text);

      node.addEventListener("pointerdown", makeMarkerPointerDown(index));
      group.appendChild(node);
    });
  }

  /** Full-stage guide lines through the pointer, so the drop point is exact. */
  function renderCrosshair() {
    var group = el("ed-crosshair");
    if (!group) return;
    clear(group);
    // Hidden while panning: the pointer is moving the picture, not choosing a
    // point on it.
    if (!pointerClient || pan !== null || !imageReady()) return;
    var img = el("ed-img");
    var rect = img.getBoundingClientRect();
    var x = pointerClient.x;
    var y = pointerClient.y;
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return;
    var base = overlayRect();
    if (!base) return;
    var cx = x - base.left;
    var cy = y - base.top;
    group.appendChild(
      svgEl("line", { class: "ed-crosshair-line", x1: 0, y1: cy, x2: base.width, y2: cy })
    );
    group.appendChild(
      svgEl("line", { class: "ed-crosshair-line", x1: cx, y1: 0, x2: cx, y2: base.height })
    );
  }

  function renderList() {
    var list = el("ed-list");
    if (!list) return;
    list.innerHTML = "";
    // Clearing the list destroys whichever label input had focus, and a
    // destroyed input never fires blur. Without this the flag stuck at "a text
    // field is focused" and Ctrl+V image paste stayed disabled for the rest of
    // the session.
    reportTextFocus();
    if (!markers.length) {
      var placeholder = document.createElement("div");
      placeholder.className = "ed-empty-row";
      placeholder.textContent = "No markers yet — click the image to add one.";
      list.appendChild(placeholder);
      return;
    }
    markers.forEach(function (marker, index) {
      var row = document.createElement("div");
      row.className = "ed-row";

      var num = document.createElement("div");
      num.className = "ed-row-num";
      num.textContent = String(index + 1);

      var input = document.createElement("input");
      input.className = "ed-row-input";
      input.type = "text";
      input.placeholder = "Label for marker " + (index + 1);
      input.value = marker.label || "";
      input.setAttribute("data-index", String(index));
      input.addEventListener("input", function () {
        markers[index].label = input.value;
        input.classList.remove("ed-invalid");
      });

      var del = document.createElement("button");
      del.className = "ed-row-del";
      del.type = "button";
      del.textContent = "×";
      del.title = "Remove this marker";
      del.addEventListener("click", function () {
        // Any in-flight drag indexes into the array we're about to shrink, so
        // end it first to avoid a stale index (e.g. a touch drag + tap-delete).
        cancelDrag();
        markers.splice(index, 1);
        // The selection is an index into the same array, so it shifts too.
        if (selected === index) selected = -1;
        else if (selected > index) selected -= 1;
        render();
        notifyCount();
      });

      row.appendChild(num);
      row.appendChild(input);
      row.appendChild(del);
      list.appendChild(row);
    });
  }

  function render() {
    renderOverlay();
    renderList();
  }

  function focusInput(index) {
    // Deliberately does NOT pan to reveal the marker: its only caller is the
    // click that just placed one, which is by definition already on screen, and
    // panning would slide the picture out from under a stationary cursor.
    // markInvalid() reveals explicitly, because those markers may be anywhere.
    var input = document.querySelector('.ed-row-input[data-index="' + index + '"]');
    if (input) input.focus();
  }

  // ---- interaction ----------------------------------------------------------

  /** Map viewport client coordinates to a normalized (0..1) point on the image. */
  function pointToNormalized(clientX, clientY) {
    var img = el("ed-img");
    if (!img) return null;
    // getBoundingClientRect() reflects the zoom transform, so this is already
    // correct at every zoom level with no extra arithmetic.
    var rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return {
      x: clamp01((clientX - rect.left) / rect.width),
      y: clamp01((clientY - rect.top) / rect.height),
    };
  }

  /**
   * Whether a point is on the visible image. When zoomed, the image overflows
   * the stage and the overflow is clipped, so being inside the image rect is
   * not sufficient; the point must also be inside the visible area.
   *
   * The clip test is redundant for the current caller, which uses the result
   * only to arm the click latch, and a pointerdown always clears that latch
   * first. Kept for correctness of the predicate.
   */
  function isOverImage(clientX, clientY) {
    var img = el("ed-img");
    // The overlay's rect, not the stage's: `overflow: hidden` clips to the
    // PADDING box, one pixel inside the stage's border, and the overlay is
    // positioned to that same box. Measuring the stage's border box instead
    // counts a point on the border as being on the image.
    var s = overlayRect();
    if (!img || !s || !imageReady()) return false;
    var r = img.getBoundingClientRect();
    return (
      clientX >= Math.max(r.left, s.left) &&
      clientX <= Math.min(r.right, s.right) &&
      clientY >= Math.max(r.top, s.top) &&
      clientY <= Math.min(r.bottom, s.bottom)
    );
  }

  function onImageClick(event) {
    // A drag that ended over the image can be followed by a click; ignore it so
    // repositioning a marker (or panning) never also creates a new one.
    if (suppressNextImageClick) {
      suppressNextImageClick = false;
      return;
    }
    var pos = pointToNormalized(event.clientX, event.clientY);
    if (!pos) return;
    markers.push({ x: pos.x, y: pos.y, label: "" });
    selected = markers.length - 1;
    render();
    notifyCount();
    focusInput(markers.length - 1);
  }

  // ---- dragging a marker to reposition it -----------------------------------

  function capturePointer(node, pointerId) {
    // Guarantees the matching pointerup even if the pointer leaves the window.
    // Without it a lost release strands the gesture, and a stranded `drag`
    // blocks every later drag AND pan.
    if (!node || typeof node.setPointerCapture !== "function") return;
    try {
      node.setPointerCapture(pointerId);
    } catch (err) {
      /* not capturable on this platform; the window listeners still cover us */
    }
  }

  function makeMarkerPointerDown(index) {
    return function (event) {
      // One gesture at a time: ignore a second pointer pressed mid-drag (e.g. a
      // second finger), which would otherwise overwrite `drag` and orphan the
      // first pointer's window listeners, and never start a marker drag on top
      // of a pan.
      if (drag !== null || pan !== null) return;
      // Primary button / touch / pen only (ignore right- and middle-click).
      if (event.button != null && event.button !== 0) return;
      // Space arms panning, so a primary press belongs to the pan gesture.
      if (spaceHeld) return;
      // Suppress the native image drag-ghost and keep the press off the stage.
      // The second is defensive: onStagePointerDown ignores a bare primary
      // press today, but this is what would stop a marker drag also starting a
      // pan if that changed.
      event.preventDefault();
      event.stopPropagation();
      // A fresh gesture makes any leftover latch stale (see onDragEnd).
      suppressNextImageClick = false;
      selected = index;
      focusStage();
      startDrag(index, event);
    };
  }

  function startDrag(index, event) {
    drag = { index: index, pointerId: event.pointerId };
    // Capture on the stage, not the dot: renderOverlay() destroys and rebuilds
    // the marker's <g> on every move, and capture dies with the element it was
    // taken on, so capturing the dot would buy nothing.
    capturePointer(el("ed-stage"), event.pointerId);
    // Track on window (not the dot) so the drag follows the pointer even off the
    // dot, and keeps working across the overlay being rebuilt on every move.
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragEnd);
    window.addEventListener("pointercancel", onDragEnd);
    renderOverlay(); // reflect the "dragging" state
  }

  /** Tear down an active drag and its window listeners. Safe to call anytime. */
  function cancelDrag() {
    if (!drag) return;
    drag = null;
    window.removeEventListener("pointermove", onDragMove);
    window.removeEventListener("pointerup", onDragEnd);
    window.removeEventListener("pointercancel", onDragEnd);
  }

  function onDragMove(event) {
    // `drag.index` cannot be stale here: the only two things that shrink
    // `markers` (the row delete button and setImage) both cancelDrag() first,
    // and both are covered by tests, so there is no window in which a drag
    // outlives its marker.
    if (!drag || event.pointerId !== drag.pointerId) return;
    var pos = pointToNormalized(event.clientX, event.clientY);
    if (!pos) return;
    markers[drag.index].x = pos.x;
    markers[drag.index].y = pos.y;
    renderOverlay(); // only positions change; the label rows are untouched
  }

  function onDragEnd(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    var overImage = isOverImage(event.clientX, event.clientY);
    cancelDrag();
    // Defensive. The hit circle is a sibling of #ed-img, so a click dispatches
    // at #ed-stage and never reaches onImageClick; renderOverlay() has also
    // removed the pressed circle by now. Covers platforms that synthesise a
    // click anyway. A stale latch is cleared on the next pointerdown.
    if (overImage) suppressNextImageClick = true;
    renderOverlay();
  }

  // ---- panning the zoomed image ---------------------------------------------

  function onStagePointerDown(event) {
    // Every click is preceded by its own pointerdown, so a latch still armed at
    // this point belongs to an earlier gesture and must not eat this one. This
    // runs before the button test on purpose: a bare primary press (plain
    // click-to-add) returns below without starting a pan, and that is exactly
    // the press whose click a stale latch would swallow.
    suppressNextImageClick = false;
    if (drag !== null || pan !== null) return;
    var button = event.button == null ? 0 : event.button;
    // Middle and right are free (marker drag already ignores them), and Space
    // arms the primary button. The bare primary button always means "place a
    // marker", so click-to-add is never a drag-versus-click race.
    if (!(button === 1 || button === 2 || (button === 0 && spaceHeld))) return;
    event.preventDefault();
    startPan(event);
  }

  function startPan(event) {
    pan = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: panX,
      originY: panY,
    };
    suppressNextImageClick = false;
    capturePointer(el("ed-stage"), event.pointerId);
    setStageClass("ed-panning", true);
    window.addEventListener("pointermove", onPanMove);
    window.addEventListener("pointerup", onPanEnd);
    window.addEventListener("pointercancel", onPanEnd);
    renderCrosshair();
  }

  /** Tear down an active pan and its window listeners. Safe to call anytime. */
  function endPan() {
    if (!pan) return;
    pan = null;
    setStageClass("ed-panning", false);
    window.removeEventListener("pointermove", onPanMove);
    window.removeEventListener("pointerup", onPanEnd);
    window.removeEventListener("pointercancel", onPanEnd);
  }

  function onPanMove(event) {
    if (!pan || event.pointerId !== pan.pointerId) return;
    setPan(
      pan.originX + (event.clientX - pan.startX),
      pan.originY + (event.clientY - pan.startY)
    );
  }

  function onPanEnd(event) {
    if (!pan || event.pointerId !== pan.pointerId) return;
    var overImage = isOverImage(event.clientX, event.clientY);
    endPan();
    // Defensive. Middle and right buttons release as auxclick, not click, and
    // the Space+primary case holds pointer capture on #ed-stage, which
    // retargets the compatibility mouse events there. No click is expected.
    // Unconditional, not "only if it moved": a press with Space held (or on a
    // marker) means pan/drag whatever distance it covers, so the click that
    // follows is never a placement. A 2px Space-pan used to drop a stray marker.
    if (overImage) suppressNextImageClick = true;
    renderCrosshair();
  }

  function onContextMenu(event) {
    // Right-drag pans, so the menu would fire on every pan release.
    event.preventDefault();
  }

  // ---- zooming --------------------------------------------------------------

  function onWheel(event) {
    // preventDefault unconditionally, loaded or not. An unhandled wheel
    // scrolls the page, and QtWebEngine maps ctrl+wheel to its own page zoom,
    // which would rescale the editor and invalidate the marker geometry.
    event.preventDefault();
    if (!imageReady() || drag !== null || pan !== null) return;
    var px = normalizeWheelDelta(event.deltaY, event.deltaMode);
    if (!px) return;
    zoomTo(zoom * Math.pow(WHEEL_RATE, -px), event.clientX, event.clientY);
  }

  function onWindowWheel(event) {
    // A ctrl+wheel anywhere else on the page is still QtWebEngine page zoom.
    if (event.ctrlKey || event.metaKey) event.preventDefault();
  }

  // ---- keyboard -------------------------------------------------------------

  function isTextField(node) {
    if (!node) return false;
    return node.tagName === "INPUT" || node.tagName === "TEXTAREA";
  }

  function isButton(node) {
    return !!node && node.tagName === "BUTTON";
  }

  function onKeyDown(event) {
    // Mid-composition an IME owns every key.
    if (event.isComposing) return;
    // Modified keys belong to the browser and to Anki (Ctrl+F, Ctrl+Z, ...).
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    // Label fields must keep their own '+', '-', '0' and arrow keys. Note that
    // focusInput() parks focus in one after every marker is added, so the wheel
    // and the toolbar are the always-available zoom routes.
    if (isTextField(document.activeElement)) return;

    var key = event.key;
    if (key === "+" || key === "=") {
      event.preventDefault();
      stepZoom(1);
      return;
    }
    if (key === "-" || key === "_") {
      event.preventDefault();
      stepZoom(-1);
      return;
    }
    if (key === "0") {
      event.preventDefault();
      resetZoom();
      return;
    }
    if (key === " " || key === "Spacebar") {
      // Space is how a keyboard user presses a focused button. Swallowing it
      // here meant tabbing to zoom-in or a row's delete button and pressing
      // Space did nothing at all -- it armed pan-ready instead.
      if (isButton(document.activeElement)) return;
      event.preventDefault(); // Space would otherwise scroll the panel
      if (!spaceHeld) {
        spaceHeld = true;
        setStageClass("ed-pan-ready", true);
      }
      return;
    }

    var dx = 0;
    var dy = 0;
    if (key === "ArrowLeft") dx = -1;
    else if (key === "ArrowRight") dx = 1;
    else if (key === "ArrowUp") dy = -1;
    else if (key === "ArrowDown") dy = 1;
    else return;
    if (selected < 0 || selected >= markers.length) return;
    event.preventDefault();
    var step = nudgeStep(event.shiftKey);
    nudgeSelected(dx * step, dy * step);
  }

  /**
   * Tell Python whether a label field has focus.
   *
   * Checked on the next tick because focusout fires before focus has settled on
   * whatever comes next, and because renderList() destroys and rebuilds the
   * rows, so the element that had focus can vanish without a blur at all.
   */
  function reportTextFocus() {
    window.setTimeout(function () {
      var focused = isTextField(document.activeElement);
      if (focused === textFocused) return;
      textFocused = focused;
      send("ro:textfocus:" + (focused ? "1" : "0"));
    }, 0);
  }

  function onKeyUp(event) {
    if (event.key === " " || event.key === "Spacebar") releaseSpace();
  }

  /**
   * Stop treating Space as held.
   *
   * keyup alone is insufficient: switching applications with Space held sends
   * the keyup elsewhere, leaving spaceHeld set. A later marker press would then
   * bail out of makeMarkerPointerDown, bubble to the stage, and pan instead of
   * moving the marker. Also called on blur and visibilitychange.
   */
  function releaseSpace() {
    if (!spaceHeld) return;
    spaceHeld = false;
    setStageClass("ed-pan-ready", false);
  }

  /**
   * Move the selected marker by a distance in *screen* pixels, which is the
   * point of pairing this with zoom: at 8x one key press moves it an eighth of
   * an image pixel, finer than any click could be.
   */
  function nudgeSelected(dxPx, dyPx) {
    var img = el("ed-img");
    if (!img || !imageReady()) return;
    var rect = img.getBoundingClientRect();
    var marker = markers[selected];
    marker.x = clamp01(marker.x + dxPx / rect.width);
    marker.y = clamp01(marker.y + dyPx / rect.height);
    renderOverlay();
  }

  // ---- pointer tracking / resize --------------------------------------------

  function onStagePointerMove(event) {
    pointerClient = { x: event.clientX, y: event.clientY };
    renderCrosshair();
  }

  function onStagePointerLeave() {
    pointerClient = null;
    renderCrosshair();
  }

  function onStageResize() {
    // Coalesced into one frame: a drag-resize of the dialog fires this
    // continuously, and each pass re-measures and re-renders the overlay.
    if (resizeFrame !== null) return;
    resizeFrame = schedule(function () {
      resizeFrame = null;
      // The viewport changed, so the pan bounds moved with it.
      setPan(panX, panY);
    });
  }

  // ---- public API (called from Python) --------------------------------------

  function normalizeMarkers(list) {
    if (!Array.isArray(list)) return [];
    return list.map(function (m) {
      // `ord` is the marker's EXISTING Anki cloze ordinal, present only when the
      // note is being edited. It is carried through untouched so the save can
      // give each surviving structure back the card -- and the review history --
      // it already had. A marker added here has none, and Python assigns one.
      var ord = Number(m.ord);
      return {
        x: clamp01(Number(m.x) || 0),
        y: clamp01(Number(m.y) || 0),
        label: m.label == null ? "" : String(m.label),
        ord: isFinite(ord) && ord >= 1 ? Math.floor(ord) : null,
      };
    });
  }

  function setImage(dataUrl, initialMarkers) {
    var img = el("ed-img");
    var empty = el("ed-empty");
    // Tear down gestures and view state before swapping the image. setImage()
    // can be called mid-drag, and a surviving gesture would write through a
    // stale marker index.
    cancelDrag();
    endPan();
    suppressNextImageClick = false;
    selected = -1;
    pointerClient = null;
    releaseSpace();
    // `zoom` deliberately survives: replacing the picture should not throw away
    // the magnification the user is working at, nor resurrect the level the
    // dialog happened to open with after they have asked for Fit.
    panX = 0;
    panY = 0;

    // Editing re-opens a note with its existing markers; creating passes none.
    markers = normalizeMarkers(initialMarkers);
    imageBroken = false;
    if (empty) empty.style.display = "none";
    img.onload = function () {
      img.onerror = null;
      // Only now is the laid-out size known, so this is where the view can be
      // centred and the pan clamped against real dimensions.
      centrePan();
      render();
    };
    // A file the webview cannot decode -- a truncated download, a .png that is
    // really something else, an SVG the engine rejects -- used to leave the
    // canvas blank and inert with the empty-state hint already hidden, so the
    // dialog looked ready and simply did nothing for ever after.
    img.onerror = function () {
      img.onload = null;
      img.onerror = null;
      imageBroken = true;
      img.style.display = "none";
      if (empty) {
        empty.textContent =
          "That image could not be displayed. Choose or paste another one.";
        empty.style.display = "";
      }
      // Keeps the marker rows (the note's data) while clearing the overlay,
      // because renderOverlay() bails after it has cleared.
      render();
      notifyCount();
      notifyBroken();
    };
    img.style.display = "block";
    img.src = dataUrl;
    // Render the list now (it needs no image geometry) so pre-loaded labels show
    // immediately; the overlay dots follow once the image reports its size.
    applyTransform();
    renderList();
    notifyCount();
    notifyBroken();
  }

  function getMarkers() {
    // Deliberately untouched by zoom and pan: the view transform never writes
    // back into the model.
    return markers.map(function (m) {
      return {
        x: m.x,
        y: m.y,
        label: (m.label || "").trim(),
        ord: m.ord == null ? null : m.ord,
      };
    });
  }

  function markInvalid(indices) {
    var list = indices || [];
    list.forEach(function (index) {
      var input = document.querySelector('.ed-row-input[data-index="' + index + '"]');
      if (input) input.classList.add("ed-invalid");
    });
    // Zoomed in, the offending marker may be off-screen; show the first one.
    if (list.length) revealMarker(list[0]);
  }

  /** Restore the zoom level remembered in the add-on config. */
  function setZoom(value) {
    zoom = clampZoom(Number(value));
    if (imageReady()) centrePan();
    else applyTransform();
  }

  // ---- wiring ---------------------------------------------------------------

  function bindButton(button, handler) {
    if (!button) return;
    button.addEventListener("click", function () {
      handler();
      // Hand focus back to the canvas so the shortcut and arrow-nudge keys keep
      // working after a click on the toolbar.
      focusStage();
    });
  }

  function init() {
    var img = el("ed-img");
    var stage = el("ed-stage");
    if (img) img.addEventListener("click", onImageClick);
    if (stage) {
      // passive:false so preventDefault() actually suppresses the page's own
      // scroll/zoom response.
      stage.addEventListener("wheel", onWheel, { passive: false });
      stage.addEventListener("pointerdown", onStagePointerDown);
      stage.addEventListener("pointermove", onStagePointerMove);
      stage.addEventListener("pointerleave", onStagePointerLeave);
      stage.addEventListener("contextmenu", onContextMenu);
    }
    bindButton(el("ed-zoom-in"), function () {
      stepZoom(1);
    });
    bindButton(el("ed-zoom-out"), function () {
      stepZoom(-1);
    });
    bindButton(el("ed-zoom-fit"), resetZoom);

    window.addEventListener("resize", onStageResize);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    // A keyup that lands in another application never reaches us, so treat
    // losing the page as releasing every key we track.
    window.addEventListener("blur", releaseSpace);
    document.addEventListener("visibilitychange", releaseSpace);
    // focusin/focusout bubble, so one pair of listeners covers every label row,
    // including rows that do not exist yet.
    document.addEventListener("focusin", reportTextFocus);
    document.addEventListener("focusout", reportTextFocus);
    window.addEventListener("wheel", onWindowWheel, { passive: false });
    // Keep the overlay aligned when the dialog/stage/image resizes or the image
    // finishes laying out (more reliable than window 'resize' alone).
    if (stage && typeof ResizeObserver === "function") {
      new ResizeObserver(onStageResize).observe(stage);
    }
    renderList();
    updateZoomUi();
    // Tell Python we are ready to receive an image. pycmd is injected by Anki's
    // webview bootstrap; retry briefly in case it is not defined yet.
    var tries = 0;
    (function announce() {
      if (typeof pycmd === "function") {
        send("ro:ready");
      } else if (tries++ < 20) {
        window.setTimeout(announce, 25);
      }
    })();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  return {
    setImage: setImage,
    getMarkers: getMarkers,
    markInvalid: markInvalid,
    setZoom: setZoom,
    // Pure helpers plus a state peek, for the Node tests; render.js exposes its
    // own internals the same way.
    _internals: {
      clamp01: clamp01,
      clampZoom: clampZoom,
      clampPan: clampPan,
      zoomAt: zoomAt,
      nudgeStep: nudgeStep,
      normalizeWheelDelta: normalizeWheelDelta,
      MIN_ZOOM: MIN_ZOOM,
      MAX_ZOOM: MAX_ZOOM,
      ZOOM_STEP: ZOOM_STEP,
      state: function () {
        return { zoom: zoom, panX: panX, panY: panY, selected: selected };
      },
    },
  };
})();
