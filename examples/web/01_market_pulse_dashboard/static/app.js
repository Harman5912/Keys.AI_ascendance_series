/* Market Pulse front end — everything on this page comes from the API. */
const $ = (sel) => document.querySelector(sel);
const state = { symbol: "BTC", days: 30 };

const money = (n) => "$" + Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
const compact = (n) => {
  const v = Number(n);
  if (v >= 1e9) return (v / 1e9).toFixed(1) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return String(v);
};

async function getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.error || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function showBanner(text) {
  const el = $("#banner");
  el.hidden = !text;
  el.textContent = text || "";
}

function renderKpis(payload) {
  const host = $("#overview");
  host.innerHTML = "";
  if (payload.empty) {
    host.innerHTML = '<p class="empty">The table is empty. POST /api/seed inserts 30 days of sample rows.</p>';
    return;
  }
  for (const row of payload.rows) {
    const up = Number(row.change_pct) >= 0;
    const card = document.createElement("article");
    card.className = "kpi";
    card.innerHTML = `
      <p class="sym">${row.symbol}</p>
      <p class="val">${money(row.price)}</p>
      <p class="delta ${up ? "up" : "down"}">${up ? "▲" : "▼"} ${Math.abs(row.change_pct)}% over the window</p>`;
    host.append(card);
  }
  document.querySelectorAll(".rail a").forEach((a) =>
    a.classList.toggle("is-current", a.getAttribute("href") === "#overview"));
  $("#backend").textContent = payload.backend;
  $("#backend-2").textContent = payload.backend;
  if (payload.backend === "sqlite") {
    showBanner("Running on the SQLite fallback: MySQL was not reachable, so the numbers are the bundled sample rows.");
  } else {
    showBanner("");
  }
}

function renderLine(points) {
  const host = $("#trend-chart");
  $("#trend-empty").hidden = points.length > 0;
  if (!points.length) { host.innerHTML = ""; return; }

  const W = 760, H = 240, pad = { l: 54, r: 14, t: 14, b: 28 };
  const prices = points.map((p) => Number(p.price));
  const min = Math.min(...prices), max = Math.max(...prices);
  const span = max - min || 1;
  const x = (i) => pad.l + (i * (W - pad.l - pad.r)) / Math.max(1, points.length - 1);
  const y = (v) => pad.t + (1 - (v - min) / span) * (H - pad.t - pad.b);

  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(p.price)).toFixed(1)}`).join(" ");
  const area = `${path} L${x(points.length - 1).toFixed(1)},${H - pad.b} L${x(0).toFixed(1)},${H - pad.b} Z`;
  const ticks = [0, 0.5, 1].map((f) => min + span * f);
  const labels = points.filter((_, i) => i % Math.ceil(points.length / 5) === 0);

  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#35d6c0" stop-opacity=".35"/>
          <stop offset="100%" stop-color="#35d6c0" stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${ticks.map((t) => `<line class="grid-line" x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}"/>
        <text class="axis-label" x="8" y="${y(t) + 4}">${money(Math.round(t))}</text>`).join("")}
      <path d="${area}" fill="url(#fill)"/>
      <path d="${path}" fill="none" stroke="#35d6c0" stroke-width="2.5" stroke-linejoin="round"/>
      ${points.map((p, i) => `<circle cx="${x(i)}" cy="${y(Number(p.price))}" r="2.4" fill="#0b1020" stroke="#35d6c0" stroke-width="1.6"><title>${p.day}: ${money(p.price)}</title></circle>`).join("")}
      ${labels.map((p) => `<text class="axis-label" x="${x(points.indexOf(p))}" y="${H - 8}" text-anchor="middle">${p.day.slice(5)}</text>`).join("")}
    </svg>`;
}

function renderBars(points) {
  const host = $("#volume-chart");
  $("#volume-empty").hidden = points.length > 0;
  if (!points.length) { host.innerHTML = ""; return; }

  const W = 760, H = 170, pad = { l: 54, r: 10, t: 10, b: 24 };
  const max = Math.max(...points.map((p) => Number(p.volume))) || 1;
  const bw = (W - pad.l - pad.r) / points.length;

  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="barFill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#f5b544"/><stop offset="100%" stop-color="#8a5a12"/>
      </linearGradient></defs>
      ${[0, 0.5, 1].map((f) => {
        const yy = pad.t + (1 - f) * (H - pad.t - pad.b);
        return `<line class="grid-line" x1="${pad.l}" x2="${W - pad.r}" y1="${yy}" y2="${yy}"/>
                <text class="axis-label" x="8" y="${yy + 4}">${compact(max * f)}</text>`;
      }).join("")}
      ${points.map((p, i) => {
        const h = (Number(p.volume) / max) * (H - pad.t - pad.b);
        const xx = pad.l + i * bw + bw * 0.18;
        return `<rect class="bar" x="${xx.toFixed(1)}" y="${(H - pad.b - h).toFixed(1)}"
                 width="${(bw * 0.64).toFixed(1)}" height="${h.toFixed(1)}" rx="3">
                 <title>${p.day}: ${compact(p.volume)}</title></rect>`;
      }).join("")}
    </svg>`;
}

function renderRows(points) {
  const body = $("#rows-body");
  if (!points.length) {
    body.innerHTML = '<tr><td colspan="5">No rows.</td></tr>';
    return;
  }
  const first = Number(points[0].price);
  body.innerHTML = points.slice(-8).reverse().map((p) => {
    const change = ((Number(p.price) - first) / first) * 100;
    return `<tr>
      <td>${state.symbol}</td>
      <td>${p.day}</td>
      <td>${money(p.price)}</td>
      <td>${compact(p.volume)}</td>
      <td class="${change >= 0 ? "up" : "down"}">${change.toFixed(2)}%</td>
    </tr>`;
  }).join("");
}

async function loadSeries() {
  $("#trend-chart").innerHTML = '<p class="loading">Loading series…</p>';
  try {
    const data = await getJSON(`/api/series?symbol=${state.symbol}&days=${state.days}`);
    renderLine(data.points || []);
    renderRows(data.points || []);
  } catch (err) {
    $("#trend-chart").innerHTML = `<p class="empty">Could not load the series: ${err.message}</p>`;
    $("#rows-body").innerHTML = `<tr><td colspan="5">Could not load rows: ${err.message}</td></tr>`;
  }
}

async function loadVolume() {
  try {
    const data = await getJSON("/api/volume?days=14");
    renderBars(data.points || []);
  } catch (err) {
    $("#volume-chart").innerHTML = `<p class="empty">Could not load volume: ${err.message}</p>`;
  }
}

async function loadKpis() {
  try {
    renderKpis(await getJSON("/api/kpis"));
  } catch (err) {
    $("#overview").innerHTML = `<p class="empty">Could not load the summary: ${err.message}</p>`;
  }
}

$("#symbol").addEventListener("change", (e) => { state.symbol = e.target.value; loadSeries(); });
$("#days").addEventListener("change", (e) => { state.days = Number(e.target.value); loadSeries(); });

Promise.all([loadKpis(), loadSeries(), loadVolume()]);
