/* Signal Room — renders the report canvas from /api/overview. */
const $ = (sel) => document.querySelector(sel);
const state = { days: 28, channel: "" };
const gbp = (n) => "£" + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });

async function api(path) {
  const res = await fetch(path);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`);
  return body;
}

function kpis(k) {
  document.querySelectorAll("[data-kpi]").forEach((node) => {
    const v = k[node.dataset.kpi];
    node.textContent = node.dataset.kpi === "ctr" ? `${v}%`
      : node.dataset.kpi === "roas" ? `${Number(v).toFixed(2)}×`
      : node.dataset.kpi === "cpl" ? `£${Number(v).toFixed(2)}`
      : gbp(v);
  });
}

function channelRows(rows) {
  const total = rows.reduce((sum, r) => sum + Number(r.revenue), 0) || 1;
  const shown = state.channel ? rows.filter((r) => r.channel === state.channel) : rows;
  $("#channel-rows").innerHTML = shown.length ? shown.map((r) => {
    const roas = Number(r.revenue) / (Number(r.spend) || 1);
    const share = (Number(r.revenue) / total) * 100;
    const tone = roas >= 3.5 ? "#e6f5f1" : roas >= 2.5 ? "#fff8e6" : "#fdecea";
    return `<tr>
      <td>${r.channel}</td>
      <td>${gbp(r.spend)}</td>
      <td>${gbp(r.revenue)}</td>
      <td><span class="heat" style="background:${tone}">${roas.toFixed(2)}×</span></td>
      <td>${Number(r.leads).toLocaleString()}</td>
      <td>${Number(r.customers).toLocaleString()}</td>
      <td><span class="share"><span class="bar" style="width:${Math.max(3, Math.round(share))}%"></span>${share.toFixed(0)}%</span></td>
    </tr>`;
  }).join("") : '<tr><td colspan="7">No rows for this filter.</td></tr>';

  const select = $("#channel");
  if (select.options.length === 1) {
    rows.forEach((r) => select.add(new Option(r.channel, r.channel)));
  }
}

function funnel(stages) {
  const max = Math.max(...stages.map((s) => s.value)) || 1;
  $("#funnel").innerHTML = stages.map((s) => `
    <li><span>${s.stage}</span><span class="bar" style="width:${Math.max(8, Math.round((s.value / max) * 100))}%">${Number(s.value).toLocaleString()}</span></li>`).join("");
}

function weekly(rows) {
  const host = $("#weeks");
  if (!rows.length) { host.innerHTML = "<p>No revenue rows.</p>"; return; }
  const buckets = [...new Set(rows.map((r) => r.bucket))].sort();
  const totals = buckets.map((b) => rows.filter((r) => r.bucket === b)
    .reduce((sum, r) => sum + Number(r.revenue), 0));
  const max = Math.max(...totals) || 1;
  const W = 420, H = 190, pad = { l: 44, r: 8, t: 10, b: 24 };
  const bw = (W - pad.l - pad.r) / buckets.length;
  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      ${[0, .5, 1].map((f) => {
        const y = pad.t + (1 - f) * (H - pad.t - pad.b);
        return `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="#d7dee8" stroke-dasharray="3 4"/>
                <text class="axis" x="2" y="${y + 3}">${gbp(max * f)}</text>`;
      }).join("")}
      ${totals.map((v, i) => {
        const h = (v / max) * (H - pad.t - pad.b);
        return `<rect class="bar-rect" x="${(pad.l + i * bw + bw * .18).toFixed(1)}"
                  y="${(H - pad.b - h).toFixed(1)}" width="${(bw * .64).toFixed(1)}"
                  height="${h.toFixed(1)}"><title>${buckets[i]}: ${gbp(v)}</title></rect>
                <text class="axis" x="${(pad.l + i * bw + bw / 2).toFixed(1)}" y="${H - 8}" text-anchor="middle">${buckets[i]}</text>`;
      }).join("")}
    </svg>`;
}

function tasks(rows) {
  const pillClass = (s) => (s === "Done" ? "done" : s === "In progress" ? "doing" : "todo");
  $("#task-rows").innerHTML = rows.map((t) => `
    <tr>
      <td>${t.title}${t.blocked_by ? `<div class="blocked">Blocked: ${t.blocked_by}</div>` : ""}</td>
      <td>${t.workstream}</td>
      <td>${t.owner}</td>
      <td><span class="pill ${pillClass(t.status)}">${t.status}</span></td>
      <td><span class="track"><span style="width:${t.progress}%"></span></span> ${t.progress}%</td>
      <td>${t.due}</td>
    </tr>`).join("");
  const open = rows.filter((t) => t.status !== "Done").length;
  $("#task-summary").textContent = `${open} open · ${rows.length} total`;
}

async function load() {
  try {
    const data = await api(`/api/overview?days=${state.days}`);
    $("#err").hidden = true;
    $("#asof").textContent = `as of ${new Date().toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
    kpis(data.kpis);
    channelRows(data.channels || []);
    funnel(data.funnel || []);
    weekly(data.weeks || []);
    tasks(data.tasks || []);
  } catch (err) {
    const box = $("#err");
    box.hidden = false;
    box.textContent = `Report failed to load: ${err.message}`;
  }
}

$("#days").addEventListener("change", (e) => { state.days = Number(e.target.value); load(); });
$("#channel").addEventListener("change", (e) => { state.channel = e.target.value; load(); });

load();
