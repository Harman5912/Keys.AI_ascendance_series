/**
 * Signal Room — marketing BI report (Node + built-in SQLite).
 *
 * Power-BI-shaped: a filter pane, a matrix visual with conditional formatting,
 * a funnel, KPI tiles and the department's task list. Every visual is fed by
 * /api/*, which reads SQLite; nothing is hardcoded in the browser.
 */
const http = require("node:http");
const { readFile } = require("node:fs/promises");
const path = require("node:path");
const { DatabaseSync } = require("node:sqlite");

const PORT = Number(process.env.PORT || 5058);
const DB_PATH = path.join(__dirname, "signal_room.sqlite3");
const PUBLIC = path.join(__dirname, "public");

const db = new DatabaseSync(DB_PATH);
db.exec(`
  CREATE TABLE IF NOT EXISTS daily (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    channel TEXT NOT NULL,
    campaign TEXT NOT NULL,
    spend REAL NOT NULL,
    impressions INTEGER NOT NULL,
    clicks INTEGER NOT NULL,
    leads INTEGER NOT NULL,
    customers INTEGER NOT NULL,
    revenue REAL NOT NULL
  );
  CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    workstream TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    due TEXT NOT NULL,
    progress INTEGER NOT NULL,
    blocked_by TEXT
  );
`);

const CHANNELS = ["Paid search", "Paid social", "Email", "Organic", "Events"];
const TASKS = [
  ["Ship Q4 paid search copy", "Acquisition", "Riya", "In progress", 4, 65, ""],
  ["Creative approval: autumn social", "Brand", "Aisha", "To do", 2, 20, "Waiting on photography"],
  ["Fix /pricing conversion tracking", "Analytics", "Tom", "In progress", 1, 80, ""],
  ["Harvest newsletter build", "Lifecycle", "Ben", "To do", 6, 0, ""],
  ["Reconcile agency invoice", "Ops", "Tom", "Done", -2, 100, ""],
  ["A/B test hero CTA", "Conversion", "Aisha", "To do", 9, 10, ""],
  ["Board deck: channel review", "Reporting", "Ben", "In progress", 3, 45, "Needs Q3 numbers"],
  ["CRM import: event leads", "Lifecycle", "Riya", "Done", -1, 100, ""],
];

function seed() {
  const n = db.prepare("SELECT COUNT(*) AS n FROM daily").get().n;
  if (n > 0) return n;
  const insert = db.prepare(
    `INSERT INTO daily (day, channel, campaign, spend, impressions, clicks, leads, customers, revenue)
     VALUES (?,?,?,?,?,?,?,?,?)`);
  const insTask = db.prepare(
    `INSERT INTO tasks (title, workstream, owner, status, due, progress, blocked_by)
     VALUES (?,?,?,?,?,?,?)`);
  db.exec("BEGIN");
  const today = new Date();
  for (let d = 27; d >= 0; d -= 1) {
    const day = new Date(today.getTime() - d * 86400000).toISOString().slice(0, 10);
    CHANNELS.forEach((channel, i) => {
      const spend = 210 + i * 90 + ((d * 11) % 70);
      const roas = 2.1 + i * 0.4 + ((d % 5) - 2) * 0.1;
      const impressions = 38000 + i * 9000 + d * 260;
      const clicks = Math.round(impressions * (0.021 + i * 0.002));
      insert.run(day, channel, `${channel} · Q4`, spend,
        impressions, clicks, Math.round(clicks * 0.12),
        Math.round(clicks * 0.022), Math.round(spend * roas));
    });
  }
  for (const t of TASKS) {
    const due = new Date(today.getTime() + t[4] * 86400000).toISOString().slice(0, 10);
    insTask.run(t[0], t[1], t[2], t[3], due, t[5], t[6]);
  }
  db.exec("COMMIT");
  return db.prepare("SELECT COUNT(*) AS n FROM daily").get().n;
}

function overview(days) {
  const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
  const kpi = db.prepare(`
    SELECT SUM(spend) AS spend, SUM(revenue) AS revenue, SUM(impressions) AS impressions,
           SUM(clicks) AS clicks, SUM(leads) AS leads, SUM(customers) AS customers
    FROM daily WHERE day >= ?`).get(since);

  const channels = db.prepare(`
    SELECT channel, SUM(spend) AS spend, SUM(revenue) AS revenue,
           SUM(leads) AS leads, SUM(customers) AS customers
    FROM daily WHERE day >= ? GROUP BY channel ORDER BY revenue DESC`).all(since);

  const weeks = db.prepare(`
    SELECT channel, 'W' || ((julianday('now') - julianday(day)) / 7 + 1) AS bucket,
           SUM(revenue) AS revenue
    FROM daily WHERE day >= ? GROUP BY channel, bucket ORDER BY bucket DESC`).all(since);

  const funnel = [
    { stage: "Impressions", value: kpi.impressions || 0 },
    { stage: "Clicks", value: kpi.clicks || 0 },
    { stage: "Leads", value: kpi.leads || 0 },
    { stage: "Customers", value: kpi.customers || 0 },
  ];

  const spend = kpi.spend || 0;
  const revenue = kpi.revenue || 0;
  return {
    window: days,
    kpis: {
      spend: Math.round(spend), revenue: Math.round(revenue),
      roas: spend ? +(revenue / spend).toFixed(2) : 0,
      cpl: kpi.leads ? +(spend / kpi.leads).toFixed(2) : 0,
      ctr: kpi.impressions ? +((kpi.clicks / kpi.impressions) * 100).toFixed(2) : 0,
    },
    channels, weeks, funnel,
    tasks: db.prepare("SELECT * FROM tasks ORDER BY due").all(),
  };
}

const MIME = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript" };
const send = (res, code, body, type = "application/json") => {
  res.writeHead(code, { "Content-Type": `${type}; charset=utf-8`, "Cache-Control": "no-store" });
  res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  try {
    if (url.pathname === "/api/overview") {
      const days = Math.max(1, Math.min(28, Number(url.searchParams.get("days") || 28)));
      return send(res, 200, overview(days));
    }
    if (url.pathname === "/api/tasks") return send(res, 200, { rows: db.prepare("SELECT * FROM tasks ORDER BY due").all() });
    if (url.pathname === "/api/seed" && req.method === "POST") {
      db.exec("DELETE FROM daily; DELETE FROM tasks;");
      return send(res, 200, { inserted: seed() });
    }
    const rel = url.pathname === "/" ? "/index.html" : url.pathname;
    const file = path.join(PUBLIC, path.normalize(rel).replace(/^([/\\])+/, ""));
    if (!file.startsWith(PUBLIC)) return send(res, 403, { error: "forbidden" });
    return send(res, 200, await readFile(file), MIME[path.extname(file)] || "application/octet-stream");
  } catch (err) {
    if (err.code === "ENOENT") return send(res, 404, { error: "not found" });
    console.error("[signal-room]", err);
    return send(res, 500, { error: "internal error", detail: String(err.message || err) });
  }
});

console.log(`[signal-room] ${seed()} rows seeded`);
server.listen(PORT, "127.0.0.1", () => console.log(`[signal-room] http://127.0.0.1:${PORT}`));
