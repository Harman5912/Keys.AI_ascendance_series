(function () {
  "use strict";

  var CFG = window.APP || {};
  var prefix = CFG.prefix || "";
  var unit = CFG.unit || "Value";
  var banner = document.getElementById("banner");
  var rangeSelect = document.getElementById("range");
  var state = { range: "30d" };

  function text(el, value) { el.textContent = value; }

  function show(message, kind) {
    banner.textContent = message || "";
    banner.className = "banner " + (kind || "");
    banner.hidden = !message;
  }

  function num(value) {
    var n = Number(value || 0);
    if (!isFinite(n)) { return "0"; }
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  function money(value) { return prefix + num(value); }

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (resp) {
      if (!resp.ok) { throw new Error(url + " -> HTTP " + resp.status); }
      return resp.json();
    });
  }

  function empty(host, message) {
    var p = document.createElement("p");
    p.className = "empty";
    p.textContent = message;
    host.appendChild(p);
  }

  function renderKPIs(payload) {
    var host = document.getElementById("kpis");
    host.innerHTML = "";
    var items = payload.kpis || [];
    if (!items.length) { empty(host, "No figures for this range."); return; }
    items.forEach(function (kpi) {
      var card = document.createElement("article");
      card.className = "kpi";
      var label = document.createElement("p");
      label.className = "kpi-label";
      label.textContent = kpi.label;
      var value = document.createElement("p");
      value.className = "kpi-value";
      value.textContent = kpi.kind === "money" ? money(kpi.value) : num(kpi.value);
      var hint = document.createElement("p");
      hint.className = "kpi-hint";
      hint.textContent = kpi.hint || "";
      card.appendChild(label);
      card.appendChild(value);
      card.appendChild(hint);
      host.appendChild(card);
    });
  }

  function renderLine(payload) {
    var host = document.getElementById("line");
    host.innerHTML = "";
    var points = payload.series || [];
    if (!points.length) { empty(host, "No data in this range."); return; }

    var W = 640, H = 250;
    var pad = { top: 14, right: 12, bottom: 30, left: 56 };
    var values = points.map(function (p) { return Number(p.value || 0); });
    var max = Math.max.apply(null, values.concat([1]));
    var min = Math.min.apply(null, values.concat([0]));
    var span = (max - min) || 1;
    var innerW = W - pad.left - pad.right;
    var innerH = H - pad.top - pad.bottom;

    function xAt(i) { return pad.left + (i * innerW) / Math.max(points.length - 1, 1); }
    function yAt(v) { return pad.top + innerH - ((v - min) / span) * innerH; }

    var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' +
      (payload.label || "Series") + ' over time">';

    [0, 0.5, 1].forEach(function (frac) {
      var value = min + span * frac;
      var y = yAt(value);
      svg += '<line class="axis" x1="' + pad.left + '" y1="' + y + '" x2="' + (W - pad.right) + '" y2="' + y + '"/>';
      svg += '<text class="tick" x="' + (pad.left - 8) + '" y="' + (y + 4) + '" text-anchor="end">' + num(value) + "</text>";
    });

    var line = points.map(function (p, i) { return xAt(i) + "," + yAt(Number(p.value || 0)); }).join(" ");
    svg += '<polygon class="area" points="' + pad.left + "," + (pad.top + innerH) + " " + line + " " + (pad.left + innerW) + "," + (pad.top + innerH) + '"/>';
    svg += '<polyline class="stroke" points="' + line + '"/>';

    var last = points.length - 1;
    svg += '<circle class="dot" cx="' + xAt(last) + '" cy="' + yAt(values[last]) + '" r="4"/>';

    svg += '<text class="tick" x="' + pad.left + '" y="' + (H - 8) + '">' + (points[0].date || "") + "</text>";
    svg += '<text class="tick" x="' + (W - pad.right) + '" y="' + (H - 8) + '" text-anchor="end">' +
      (points[points.length - 1].date || "") + "</text>";
    svg += "</svg>";
    host.innerHTML = svg;
  }

  function renderBars(payload) {
    var host = document.getElementById("bars");
    host.innerHTML = "";
    var items = payload.breakdown || [];
    if (!items.length) { empty(host, "No categories in this range."); return; }
    var max = Math.max.apply(null, items.map(function (i) { return Number(i.value || 0); }).concat([1]));
    items.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "bar-row";

      var name = document.createElement("span");
      name.className = "bar-name";
      name.textContent = item.category;
      name.title = item.category;

      var track = document.createElement("span");
      track.className = "bar-track";
      var fill = document.createElement("span");
      fill.className = "bar-fill";
      fill.style.width = Math.max(2, (Number(item.value || 0) / max) * 100) + "%";
      track.appendChild(fill);

      var value = document.createElement("span");
      value.className = "bar-value";
      value.textContent = money(item.value);

      row.appendChild(name);
      row.appendChild(track);
      row.appendChild(value);
      host.appendChild(row);
    });
  }

  function renderStatus(payload) {
    var host = document.getElementById("status");
    host.innerHTML = "";
    var items = payload.status || [];
    if (!items.length) { empty(host, "No statuses in this range."); return; }
    items.forEach(function (item) {
      var pill = document.createElement("span");
      pill.className = "pill " + String(item.status || "").toLowerCase();
      var dot = document.createElement("span");
      dot.className = "dot";
      pill.appendChild(dot);
      pill.appendChild(document.createTextNode(item.status + " · " + num(item.records) + " (" + item.share + "%)"));
      host.appendChild(pill);
    });
  }

  function renderRows(payload) {
    var body = document.querySelector("#rows tbody");
    var note = document.getElementById("empty");
    body.innerHTML = "";
    var items = payload.rows || [];
    if (!items.length) { note.hidden = false; return; }
    note.hidden = true;
    items.forEach(function (item) {
      var tr = document.createElement("tr");
      function cell(value, className) {
        var td = document.createElement("td");
        if (className) { td.className = className; }
        td.textContent = value;
        tr.appendChild(td);
      }
      cell(item.occurred_on || "");
      cell(item.label || "");
      cell(item.category || "");
      cell(num(item.quantity), "num");
      cell(money(item.amount), "num");
      var tag = document.createElement("td");
      var span = document.createElement("span");
      span.className = "status-tag";
      span.textContent = item.status || "";
      tag.appendChild(span);
      tr.appendChild(tag);
      body.appendChild(tr);
    });
  }

  function load() {
    var q = "?range=" + encodeURIComponent(state.range);
    show("Loading…", "busy");
    return Promise.all([
      getJSON("/api/kpis" + q),
      getJSON("/api/series" + q),
      getJSON("/api/breakdown" + q),
      getJSON("/api/status" + q),
      getJSON("/api/rows")
    ]).then(function (results) {
      renderKPIs(results[0]);
      renderLine(results[1]);
      renderBars(results[2]);
      renderStatus(results[3]);
      renderRows(results[4]);
      show("", "");
    }).catch(function (err) {
      show("Could not load the dashboard: " + err.message + ". Is the seeded database present (python seed.py)?", "error");
    });
  }

  function bind() {
    if (rangeSelect) {
      rangeSelect.addEventListener("change", function () {
        state.range = rangeSelect.value;
        load();
      });
    }
    var refresh = document.getElementById("refresh");
    if (refresh) { refresh.addEventListener("click", load); }
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
