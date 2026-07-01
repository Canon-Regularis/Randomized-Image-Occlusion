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
    for (var key in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, key)) {
        node.setAttribute(key, attrs[key]);
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
      svg.appendChild(svgEl("circle", { class: "ed-marker-dot", cx: cx, cy: cy, r: 11 }));
      var text = svgEl("text", {
        class: "ed-marker-label",
        x: cx,
        y: cy,
        "text-anchor": "middle",
        "dominant-baseline": "central",
      });
      text.textContent = String(index + 1);
      svg.appendChild(text);
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

  function onImageClick(event) {
    var img = el("ed-img");
    if (!img) return;
    var rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var x = clamp01((event.clientX - rect.left) / rect.width);
    var y = clamp01((event.clientY - rect.top) / rect.height);
    markers.push({ x: x, y: y, label: "" });
    render();
    notifyCount();
    focusInput(markers.length - 1);
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
