/* KeysAI_Test_Study_Planner — frontend API client.
 *
 * Everything on the page comes from the real backend (no local fixture data):
 * a failed request is shown as a visible error state, never as empty success.
 */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = { subjects: [], filters: { q: "", status: "", subject_id: "", priority: "" } };

/* ── flash messages ─────────────────────────────────────────────────── */
let flashTimer = null;
function flash(message, kind = "ok") {
  const box = $("#flash");
  box.textContent = message;
  box.dataset.kind = kind;
  box.hidden = false;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { box.hidden = true; }, 5000);
}

function fieldError(formId, message) {
  const box = $("#" + formId + "-error");
  if (!box) return;
  box.textContent = message || "";
  box.hidden = !message;
}

async function api(path, options = {}) {
  const opts = Object.assign({ headers: {} }, options);
  if (opts.body && typeof opts.body !== "string") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error("Network error — the server could not be reached.");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON body */ }
  if (!res.ok) {
    const err = data && data.error ? data.error : {};
    const error = new Error(err.message || `Request failed (${res.status})`);
    error.status = res.status;
    error.fields = err.fields || null;
    throw error;
  }
  return data;
}

/* ── dashboard ──────────────────────────────────────────────────────── */
async function loadDashboard() {
  try {
    const d = await api("/api/dashboard");
    $("#kpi-total").textContent = d.tasks.total;
    $("#kpi-todo").textContent = d.tasks.todo;
    $("#kpi-progress").textContent = d.tasks.in_progress;
    $("#kpi-done").textContent = d.tasks.done;
    $("#kpi-overdue").textContent = d.tasks.overdue;
    $("#kpi-minutes").textContent = d.sessions.total_minutes;

    const chart = $("#minutes-chart");
    chart.innerHTML = "";
    const max = Math.max(1, ...d.minutes_by_subject.map(r => r.minutes));
    if (!d.minutes_by_subject.length) {
      chart.innerHTML = '<p class="empty">No sessions logged yet.</p>';
    }
    d.minutes_by_subject.forEach(row => {
      const line = document.createElement("div");
      line.className = "bar-line";
      line.innerHTML = `<span class="bar-name"></span><span class="bar-track">` +
        `<span class="bar-fill" style="width:${Math.round((row.minutes / max) * 100)}%"></span>` +
        `</span><span class="bar-val"></span>`;
      line.querySelector(".bar-name").textContent = row.name;
      line.querySelector(".bar-val").textContent = `${row.minutes} min`;
      chart.appendChild(line);
    });
  } catch (e) {
    flash(e.message, "error");
  }
}

/* ── subjects (used by every <select> and the task list) ────────────── */
async function loadSubjects() {
  try {
    state.subjects = await api("/api/subjects");
  } catch (e) {
    state.subjects = [];
    flash(e.message, "error");
    return;
  }
  const filterSel = $("#f-subject");
  const taskSel = $("#t-subject");
  const sessSel = $("#sess-subject");
  [filterSel, taskSel, sessSel].forEach(sel => {
    const keep = sel === filterSel ? '<option value="">All</option>' : "";
    sel.innerHTML = keep;
    state.subjects.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.name;
      sel.appendChild(opt);
    });
  });
}

/* ── task list ──────────────────────────────────────────────────────── */
function fmtDue(due, status) {
  if (!due) return '<span class="muted">—</span>';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const d = new Date(due + "T00:00:00");
  const overdue = d < today && status !== "done";
  const soon = !overdue && (d - today) / 86400000 <= 2 && status !== "done";
  const cls = overdue ? "due overdue" : (soon ? "due soon" : "due");
  const label = overdue ? `${due} (overdue)` : due;
  return `<span class="${cls}">${label}</span>`;
}

async function loadTasks() {
  const body = $("#task-rows");
  const params = new URLSearchParams();
  Object.entries(state.filters).forEach(([k, v]) => { if (v) params.set(k, v); });
  try {
    const tasks = await api("/api/tasks?" + params.toString());
    $("#task-count").textContent =
      `${tasks.length} task${tasks.length === 1 ? "" : "s"}` +
      (params.toString() ? " matching the filters" : "");
    if (!tasks.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty">No tasks match. ' +
        'Add one on the left, or clear the filters.</td></tr>';
      return;
    }
    body.innerHTML = "";
    tasks.forEach(t => {
      const tr = document.createElement("tr");
      tr.dataset.id = t.id;
      tr.innerHTML = `
        <td class="t-title"></td>
        <td class="t-subject"></td>
        <td>${fmtDue(t.due_date, t.status)}</td>
        <td><span class="pill prio-${t.priority}">${t.priority}</span></td>
        <td><span class="pill status-${t.status}">${t.status.replace("_", " ")}</span></td>
        <td class="acts">
          ${t.status !== "done" ? '<button type="button" class="ghost" data-act="complete">Done</button>' : ""}
          <button type="button" class="ghost danger" data-act="delete">Delete</button>
        </td>`;
      tr.querySelector(".t-title").textContent = t.title;
      tr.querySelector(".t-subject").textContent = t.subject_name;
      body.appendChild(tr);
    });
  } catch (e) {
    body.innerHTML = '<tr><td colspan="6" class="empty error-text"></td></tr>';
    body.querySelector(".error-text").textContent = e.message;
    $("#task-count").textContent = "Could not load tasks.";
  }
}

async function refreshAll() {
  await Promise.all([loadDashboard(), loadTasks()]);
}

/* ── filters ────────────────────────────────────────────────────────── */
$("#filters").addEventListener("input", e => {
  const el = e.target;
  if (!el.name) return;
  state.filters[el.name] = el.value.trim();
  loadTasks();
});
$("#filters").addEventListener("reset", () => {
  setTimeout(() => {
    state.filters = { q: "", status: "", subject_id: "", priority: "" };
    loadTasks();
  }, 0);
});

/* ── task actions ───────────────────────────────────────────────────── */
$("#task-rows").addEventListener("click", async e => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.closest("tr").dataset.id;
  try {
    if (btn.dataset.act === "complete") {
      await api(`/api/tasks/${id}/complete`, { method: "POST" });
      flash(`Task ${id} marked done.`);
    } else if (btn.dataset.act === "delete") {
      await api(`/api/tasks/${id}`, { method: "DELETE" });
      flash(`Task ${id} deleted.`);
    }
    await refreshAll();
  } catch (err) {
    flash(err.message, "error");
  }
});

$("#task-form").addEventListener("submit", async e => {
  e.preventDefault();
  fieldError("task-form", "");
  const f = new FormData(e.target);
  const payload = {
    title: (f.get("title") || "").toString(),
    subject_id: parseInt(f.get("subject_id"), 10),
    due_date: (f.get("due_date") || "").toString() || null,
    priority: f.get("priority"),
    notes: (f.get("notes") || "").toString(),
  };
  if (!payload.subject_id) {
    fieldError("task-form", "Choose a subject (add one first if you have none).");
    return;
  }
  try {
    await api("/api/tasks", { method: "POST", body: payload });
    e.target.reset();
    flash(`Added “${payload.title}”.`);
    await refreshAll();
  } catch (err) {
    if (err.fields) {
      fieldError("task-form", Object.values(err.fields).join(" "));
    } else {
      fieldError("task-form", err.message);
    }
  }
});

$("#subject-form").addEventListener("submit", async e => {
  e.preventDefault();
  fieldError("subject-form", "");
  const name = $("#s-name").value.trim();
  try {
    await api("/api/subjects", { method: "POST", body: { name } });
    e.target.reset();
    flash(`Subject “${name}” created.`);
    await loadSubjects();
    await refreshAll();
  } catch (err) {
    if (err.status === 409) {
      fieldError("subject-form", "That subject already exists.");
    } else if (err.fields) {
      fieldError("subject-form", Object.values(err.fields).join(" "));
    } else {
      fieldError("subject-form", err.message);
    }
  }
});

$("#session-form").addEventListener("submit", async e => {
  e.preventDefault();
  fieldError("session-form", "");
  const f = new FormData(e.target);
  const payload = {
    subject_id: parseInt(f.get("subject_id"), 10),
    minutes: parseInt(f.get("minutes"), 10),
    notes: (f.get("notes") || "").toString(),
  };
  if (!payload.subject_id) {
    fieldError("session-form", "Choose a subject first.");
    return;
  }
  try {
    await api("/api/sessions", { method: "POST", body: payload });
    e.target.reset();
    $("#sess-minutes").value = 30;
    flash(`Logged ${payload.minutes} minutes.`);
    await loadDashboard();
  } catch (err) {
    if (err.fields) {
      fieldError("session-form", Object.values(err.fields).join(" "));
    } else {
      fieldError("session-form", err.message);
    }
  }
});

/* ── boot ───────────────────────────────────────────────────────────── */
(async function init() {
  await loadSubjects();
  await refreshAll();
})();
