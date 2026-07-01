/*
 * Randomized Image Occlusion — editor canvas.
 *
 * Runs inside the dialog's AnkiWebView. Lets the user drop numbered markers on
 * an image; each marker is one structure (one future card). All coordinates are
 * stored normalized (0..1 of the image), so they are resolution-independent.
 *
 * Python <-> JS contract:
 *   JS  -> Py : pycmd("ro:ready")            once the page is interactive
 *               pycmd("ro:count:<n>")        whenever the marker count changes
 *   Py  -> JS : ROEditor.setImage(dataUrl, markers?)
 *                                            show an image; markers (optional,
 *                                            [{x, y, label}, ...]) pre-populate
 *                                            it for editing, else it starts empty
 *               ROEditor.getMarkers()        -> [{x, y, label}, ...]
 */
window.ROEditor = (function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var markers = [];
  // Active marker drag, or null: { index, pointerId, moved }.
  var drag = null;
  // Set briefly when a drag ends so the trailing image "click" (if the platform
  // synthesises one) does not drop a spurious new marker.
  var suppressNextImageClick = false;

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

  function renderOverlay() {
    var img = el("ed-img");
    var svg = el("ed-overlay");
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (!img || img.style.display === "none" || !img.clientWidth) return;

    var ox = img.offsetLeft;
    var oy = img.offsetTop;
    var w = img.clientWidth;
    var h = img.clientHeight;

    markers.forEach(function (marker, index) {
      var cx = ox + marker.x * w;
      var cy = oy + marker.y * h;

      // One <g> per marker so it is a single grab target. The overlay itself is
      // pointer-transparent (see marker.css) so clicks on bare image add markers;
      // each group re-enables pointer events so its dot can be dragged.
      var dragging = drag !== null && drag.index === index;
      var group = svgEl("g", {
        class: dragging ? "ed-marker ed-marker-dragging" : "ed-marker",
      });
      // Transparent, generously sized hit area so the small dot is easy to grab.
      group.appendChild(svgEl("circle", { class: "ed-marker-hit", cx: cx, cy: cy, r: 16 }));
      group.appendChild(svgEl("circle", { class: "ed-marker-dot", cx: cx, cy: cy, r: 11 }));
      var text = svgEl("text", {
        class: "ed-marker-label",
        x: cx,
        y: cy,
        "text-anchor": "middle",
        "dominant-baseline": "central",
      });
      text.textContent = String(index + 1);
      group.appendChild(text);

      group.addEventListener("pointerdown", makeMarkerPointerDown(index));
      svg.appendChild(group);
    });
  }

  function renderList() {
    var list = el("ed-list");
    if (!list) return;
    list.innerHTML = "";
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
    var input = document.querySelector('.ed-row-input[data-index="' + index + '"]');
    if (input) input.focus();
  }

  // ---- interaction ----------------------------------------------------------

  function clamp01(v) {
    return Math.max(0, Math.min(1, v));
  }

  /** Map viewport client coordinates to a normalized (0..1) point on the image. */
  function pointToNormalized(clientX, clientY) {
    var img = el("ed-img");
    if (!img) return null;
    var rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return {
      x: clamp01((clientX - rect.left) / rect.width),
      y: clamp01((clientY - rect.top) / rect.height),
    };
  }

  function onImageClick(event) {
    // A drag that ended over the image can be followed by a click; ignore it so
    // repositioning a marker never also creates a new one.
    if (suppressNextImageClick) {
      suppressNextImageClick = false;
      return;
    }
    var pos = pointToNormalized(event.clientX, event.clientY);
    if (!pos) return;
    markers.push({ x: pos.x, y: pos.y, label: "" });
    render();
    notifyCount();
    focusInput(markers.length - 1);
  }

  // ---- dragging a marker to reposition it -----------------------------------

  function makeMarkerPointerDown(index) {
    return function (event) {
      // One drag at a time: ignore a second pointer pressed mid-drag (e.g. a
      // second finger), which would otherwise overwrite `drag` and orphan the
      // first pointer's window listeners.
      if (drag !== null) return;
      // Primary button / touch / pen only (ignore right- and middle-click).
      if (event.button != null && event.button !== 0) return;
      // Stop the image from also treating this as click-to-add, and suppress the
      // browser's native image drag-ghost.
      event.preventDefault();
      event.stopPropagation();
      startDrag(index, event.pointerId);
    };
  }

  function startDrag(index, pointerId) {
    drag = { index: index, pointerId: pointerId, moved: false };
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
    if (!drag || event.pointerId !== drag.pointerId) return;
    // The dragged marker can vanish mid-drag (deleted from the list), leaving a
    // stale index; drop the drag rather than write past the array.
    if (drag.index < 0 || drag.index >= markers.length) {
      cancelDrag();
      return;
    }
    var pos = pointToNormalized(event.clientX, event.clientY);
    if (!pos) return;
    drag.moved = true;
    markers[drag.index].x = pos.x;
    markers[drag.index].y = pos.y;
    renderOverlay(); // only positions change; the label rows are untouched
  }

  function onDragEnd(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    var moved = drag.moved;
    cancelDrag();
    if (moved) suppressNextImageClick = true;
    renderOverlay();
  }

  // ---- public API (called from Python) --------------------------------------

  function normalizeMarkers(list) {
    if (!Array.isArray(list)) return [];
    return list.map(function (m) {
      return {
        x: clamp01(Number(m.x) || 0),
        y: clamp01(Number(m.y) || 0),
        label: m.label == null ? "" : String(m.label),
      };
    });
  }

  function setImage(dataUrl, initialMarkers) {
    var img = el("ed-img");
    var empty = el("ed-empty");
    // Editing re-opens a note with its existing markers; creating passes none.
    markers = normalizeMarkers(initialMarkers);
    if (empty) empty.style.display = "none";
    img.onload = function () {
      render();
    };
    img.style.display = "block";
    img.src = dataUrl;
    // Render the list now (it needs no image geometry) so pre-loaded labels show
    // immediately; the overlay dots follow once the image reports its size.
    render();
    notifyCount();
  }

  function getMarkers() {
    return markers.map(function (m) {
      return { x: m.x, y: m.y, label: (m.label || "").trim() };
    });
  }

  function markInvalid(indices) {
    (indices || []).forEach(function (index) {
      var input = document.querySelector('.ed-row-input[data-index="' + index + '"]');
      if (input) input.classList.add("ed-invalid");
    });
  }

  // ---- wiring ---------------------------------------------------------------

  function init() {
    var img = el("ed-img");
    if (img) img.addEventListener("click", onImageClick);
    window.addEventListener("resize", renderOverlay);
    // Keep the overlay aligned when the dialog/stage/image resizes or the image
    // finishes laying out (more reliable than window 'resize' alone).
    var stage = el("ed-stage");
    if (stage && typeof ResizeObserver === "function") {
      new ResizeObserver(function () {
        renderOverlay();
      }).observe(stage);
    }
    renderList();
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
  };
})();
