/* Campaign Command front end — KPIs, funnel, trends and the task board all come from /api/*. */
const $ = (sel) => document.querySelector(sel);
const state = { channel: "", range: 30, data: null };

const gbp = (n) => "£" + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
const num = (n) => Number(n).toLocaleString();

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`);
  return body;
}

function paintKpis(k) {
  $("#k-spend").textContent = gbp(k.spend);
  $("#k-revenue").textContent = gbp(k.revenue);
  $("#k-roas").textContent = Number(k.roas).toFixed(2) + "×";
  $("#k-ctr").textContent = Number(k.ctr).toFixed(2) + "%";
}

function paintTrend(points) {
  const host = $("#trend");
  if (!points.length) { host.innerHTML = "<p>No rows in this window.</p>"; return; }
  const W = 640, H = 220, pad = { l: 46, r: 12, t: 12, b: 26 };
  const max = Math.max(...points.map((p) => Math.max(Number(p.spend), Number(p.revenue)))) || 1;
  const x = (i) => pad.l + (i * (W - pad.l - pad.r)) / Math.max(1, points.length - 1);
  const y = (v) => pad.t + (1 - Number(v) / max) * (H - pad.t - pad.b);
  const line = (key) => points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");

  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      ${[0, .5, 1].map((f) => {
        const yy = pad.t + (1 - f) * (H - pad.t - pad.b);
        return `<line class="gridline" x1="${pad.l}" x2="${W - pad.r}" y1="${yy}" y2="${yy}"/>
                <text class="axis" x="4" y="${yy + 3}">${gbp(max * f)}</text>`;
      }).join("")}
      <path d="${line("spend")}" fill="none" stroke="#a89b8a" stroke-width="1.8" stroke-dasharray="5 4"/>
      <path d="${line("revenue")}" fill="none" stroke="#f0a33c" stroke-width="2.6"/>
      ${points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.revenue)}" r="2.2" fill="#17130f" stroke="#f0a33c" stroke-width="1.5"><title>${p.day}: ${gbp(p.revenue)} revenue · ${gbp(p.spend)} spend</title></circle>`).join("")}
    </svg>
    <p class="hint" style="margin:.4rem 0 0">Solid: revenue · dashed: spend</p>`;
}

function paintFunnel(stages) {
  const max = Math.max(...stages.map((s) => s.value)) || 1;
  $("#funnel").innerHTML = stages.map((s) => `
    <li><span>${s.stage}</span>
      <span class="bar" style="width:${Math.max(4, Math.round((s.value / max) * 100))}%"></span>
      <span class="val">${num(s.value)}</span></li>`).join("");
}

function paintChannels(rows) {
  const filtered = state.channel ? rows.filter((r) => r.channel === state.channel) : rows;
  $("#channels").innerHTML = filtered.length ? filtered.map((r) => `
    <tr><td>${r.channel}</td><td>${gbp(r.spend)}</td><td>${gbp(r.revenue)}</td>
        <td>${Number(r.roas).toFixed(2)}×</td><td>£${Number(r.cpc).toFixed(2)}</td></tr>`).join("")
    : '<tr><td colspan="5">No rows.</td></tr>';

  const host = $("#channel-bars");
  const max = Math.max(...filtered.map((r) => Number(r.revenue))) || 1;
  const W = 420, rowH = 34, H = Math.max(80, filtered.length * rowH + 16);
  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      ${filtered.map((r, i) => {
        const w = Math.max(6, (Number(r.revenue) / max) * (W - 130));
        const y = 8 + i * rowH;
        return `<text class="axis" x="0" y="${y + 14}">${r.channel}</text>
                <rect x="112" y="${y + 2}" width="${w}" height="16" rx="3" fill="#f0a33c" opacity="${0.55 + 0.45 * (1 - i / filtered.length)}"><title>${gbp(r.revenue)}</title></rect>
                <text class="axis" x="${118 + w}" y="${y + 15}">${gbp(r.revenue)}</text>`;
      }).join("")}
    </svg>`;

  const select = $("#channel");
  if (select.options.length === 1) {
    rows.forEach((r) => select.add(new Option(r.channel, r.channel)));
  }
}

function taskCard(t) {
  const due = new Date(t.due_day);
  const over = due < new Date(new Date().toDateString());
  return `<button class="task ${over && t.status !== "done" ? "due" : ""}" data-id="${t.id}" data-status="${t.status}" type="button">
    <b>${t.title}</b>
    <div class="meta"><span>${t.owner} · ${t.campaign}</span><span>${t.status === "done" ? "done" : t.due_day.slice(5)}</span></div>
    <div class="progress"><span style="width:${t.progress}%"></span></div>
  </button>`;
}

function paintTasks(rows) {
  document.querySelectorAll(".col").forEach((col) => { col.querySelector(".cards").innerHTML = ""; });
  rows.forEach((t) => {
    const col = document.querySelector(`.col[data-status="${t.status}"]`);
    col?.querySelector(".cards").insertAdjacentHTML("beforeend", taskCard(t));
  });
  $("#task-count").textContent = `${rows.filter((t) => t.status !== "done").length} open · ${rows.length} total`;
}

const NEXT = { todo: "doing", doing: "done", done: "todo" };

document.addEventListener("click", async (event) => {
  const card = event.target.closest(".task");
  if (!card) return;
  const nextStatus = NEXT[card.dataset.status];
  try {
    await api(`/api/tasks/${card.dataset.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: nextStatus }),
    });
    paintTasks((await api("/api/tasks")).rows);
  } catch (err) {
    const box = $("#error");
    box.hidden = false;
    box.textContent = `Could not move the task: ${err.message}`;
  }
});

async function load() {
  try {
    const data = await api("/api/overview");
    state.data = data;
    $("#error").hidden = true;
    $("#backend").textContent = data.backend;
    $("#backend-2").textContent = data.backend;
    paintKpis(data.kpis);
    paintTrend(data.trend || []);
    paintFunnel(data.funnel || []);
    paintChannels(data.channels || []);
    paintTasks((await api("/api/tasks")).rows);
  } catch (err) {
    const box = $("#error");
    box.hidden = false;
    box.textContent = `The dashboard could not reach its API: ${err.message}`;
  }
}

$("#channel").addEventListener("change", (e) => { state.channel = e.target.value; paintChannels(state.data.channels); });
$("#range").addEventListener("change", (e) => { state.range = Number(e.target.value); load(); });

load();
