/* OPS/HIVE front end — draws only what /api/* returns. */
const kpiNodes = document.querySelectorAll("[data-kpi]");
const rowsBody = document.getElementById("rows");
const errBox = document.getElementById("err");

function showError(message) {
  errBox.hidden = !message;
  errBox.textContent = message || "";
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function paintKpis(stats) {
  const values = {
    total: stats.total ?? 0,
    open: stats.open ?? 0,
    avg_response: `${stats.avg_response ?? 0}m`,
    sla_breaches: stats.sla_breaches ?? 0,
  };
  kpiNodes.forEach((node) => {
    node.textContent = values[node.dataset.kpi] ?? "–";
  });
}

function paintHourly(points) {
  const host = document.getElementById("hourly");
  if (!points.length) { host.innerHTML = "<p>No tickets in the table.</p>"; return; }

  const W = 620, H = 220, pad = { l: 32, r: 8, t: 8, b: 26 };
  const max = Math.max(...points.map((p) => p.n)) || 1;
  const bw = (W - pad.l - pad.r) / points.length;
  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      ${[0, 0.5, 1].map((f) => {
        const y = pad.t + (1 - f) * (H - pad.t - pad.b);
        return `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="#e0dccf" stroke-dasharray="3 5"/>
                <text class="axis" x="4" y="${y + 3}">${Math.round(max * f)}</text>`;
      }).join("")}
      ${points.map((p, i) => {
        const h = (p.n / max) * (H - pad.t - pad.b);
        return `<rect class="hbar" x="${(pad.l + i * bw + bw * 0.15).toFixed(1)}"
                  y="${(H - pad.b - h).toFixed(1)}" width="${(bw * 0.7).toFixed(1)}"
                  height="${h.toFixed(1)}"><title>${p.hour}: ${p.n} tickets</title></rect>
                ${i % 3 === 0 ? `<text class="axis" x="${(pad.l + i * bw + bw / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle">${p.hour.slice(0, 2)}</text>` : ""}`;
      }).join("")}
    </svg>`;
}

function paintChannels(channels) {
  const host = document.getElementById("channels");
  const max = Math.max(...channels.map((c) => c.avg_response)) || 1;
  host.innerHTML = channels.map((c) => {
    const pct = Math.round((c.avg_response / max) * 100);
    const slow = c.avg_response > 30 ? "slow" : "";
    return `<li><span>${c.channel}</span><span class="meter"><span class="${slow}" style="width:${pct}%"></span></span><span>${c.avg_response}m · ${c.n}</span></li>`;
  }).join("");
}

function paintRows(rows) {
  if (!rows.length) { rowsBody.innerHTML = '<tr><td colspan="6">No tickets yet.</td></tr>'; return; }
  rowsBody.innerHTML = rows.map((r) => {
    const opened = new Date(r.opened_at).toLocaleString(undefined, {
      month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });
    const state = r.resolved_at ? "resolved" : "open";
    return `<tr>
      <td>#${r.id}</td>
      <td>${r.channel}</td>
      <td><span class="pill ${r.priority === "P1" ? "p1" : ""}">${r.priority}</span></td>
      <td>${opened}</td>
      <td>${r.first_response_m}m</td>
      <td><span class="pill ${state === "open" ? "open" : ""}">${state}</span></td>
    </tr>`;
  }).join("");
}

async function load() {
  try {
    const [stats, tickets] = await Promise.all([api("/api/stats"), api("/api/tickets")]);
    showError("");
    paintKpis(stats);
    paintHourly(stats.byHour || []);
    paintChannels(stats.byChannel || []);
    paintRows(tickets.rows || []);
  } catch (err) {
    showError(`The dashboard could not reach its API: ${err.message}`);
    rowsBody.innerHTML = '<tr><td colspan="6">No data — the API call failed.</td></tr>';
  }
}

load();
