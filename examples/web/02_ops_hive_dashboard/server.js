/**
 * Ops Hive — support-desk operations dashboard.
 *
 * Zero npm dependencies: Node's built-in http server and built-in SQLite
 * (`node:sqlite`, Node 22+). All numbers come from SQL; the browser only
 * draws what the API returns.
 */
const http = require("node:http");
const { readFile } = require("node:fs/promises");
const path = require("node:path");
const { DatabaseSync } = require("node:sqlite");

const PORT = Number(process.env.PORT || 5056);
const DB_PATH = path.join(__dirname, "ops_hive.sqlite3");
const PUBLIC = path.join(__dirname, "public");

const db = new DatabaseSync(DB_PATH);
db.exec(`
  CREATE TABLE IF NOT EXISTS tickets (
    id                INTEGER PRIMARY KEY,
    channel           TEXT    NOT NULL,
    priority          TEXT    NOT NULL,
    opened_at         TEXT    NOT NULL,
    resolved_at       TEXT,
    first_response_m  INTEGER NOT NULL
  );
`);

const channels = ["email", "chat", "phone"];
const priorities = ["P1", "P2", "P3"];

function seed() {
  const count = db.prepare("SELECT COUNT(*) AS n FROM tickets").get().n;
  if (count > 0) return count;

  const insert = db.prepare(
    `INSERT INTO tickets (channel, priority, opened_at, resolved_at, first_response_m)
     VALUES (?, ?, ?, ?, ?)`);
  const now = Date.now();
  db.exec("BEGIN");
  for (let i = 0; i < 220; i += 1) {
    const opened = new Date(now - i * 37 * 60 * 1000);
    const priority = priorities[i % priorities.length];
    const base = priority === "P1" ? 6 : priority === "P2" ? 24 : 90;
    const response = Math.max(1, Math.round(base + ((i * 13) % 40) - 12));
    const resolved = i % 7 === 0 ? null
      : new Date(opened.getTime() + (30 + (i % 12) * 25) * 60 * 1000).toISOString();
    insert.run(channels[i % 3], priority, opened.toISOString(), resolved, response);
  }
  db.exec("COMMIT");
  return db.prepare("SELECT COUNT(*) AS n FROM tickets").get().n;
}

function stats() {
  const totals = db.prepare(`
    SELECT
      COUNT(*)                                                    AS total,
      SUM(CASE WHEN resolved_at IS NULL THEN 1 ELSE 0 END)        AS open,
      ROUND(AVG(first_response_m), 1)                             AS avg_response,
      SUM(CASE WHEN priority = 'P1' AND first_response_m > 15
               THEN 1 ELSE 0 END)                                 AS sla_breaches
    FROM tickets`).get();

  const byChannel = db.prepare(`
    SELECT channel, COUNT(*) AS n,
           ROUND(AVG(first_response_m), 1) AS avg_response
    FROM tickets GROUP BY channel ORDER BY n DESC`).all();

  const byHour = db.prepare(`
    SELECT substr(opened_at, 12, 2) || ':00' AS hour, COUNT(*) AS n
    FROM tickets GROUP BY hour ORDER BY hour`).all();

  return { ...totals, byChannel, byHour };
}

function latest() {
  return db.prepare(`
    SELECT id, channel, priority, opened_at, resolved_at, first_response_m
    FROM tickets ORDER BY opened_at DESC LIMIT 12`).all();
}

const MIME = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript" };

function send(res, status, body, type = "application/json") {
  res.writeHead(status, { "Content-Type": `${type}; charset=utf-8`, "Cache-Control": "no-store" });
  res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  try {
    if (url.pathname === "/api/stats") return send(res, 200, stats());
    if (url.pathname === "/api/tickets") return send(res, 200, { rows: latest() });
    if (url.pathname === "/api/seed" && req.method === "POST") {
      db.exec("DELETE FROM tickets");
      return send(res, 200, { inserted: seed() });
    }

    const rel = url.pathname === "/" ? "/index.html" : url.pathname;
    const file = path.join(PUBLIC, path.normalize(rel).replace(/^([/\\])+/, ""));
    if (!file.startsWith(PUBLIC)) return send(res, 403, { error: "forbidden" });
    const data = await readFile(file);
    return send(res, 200, data, MIME[path.extname(file)] || "application/octet-stream");
  } catch (err) {
    if (err.code === "ENOENT") return send(res, 404, { error: "not found" });
    console.error("[ops-hive]", err);
    return send(res, 500, { error: "internal error", detail: String(err.message || err) });
  }
});

const seeded = seed();
server.listen(PORT, "127.0.0.1", () => {
  console.log(`[ops-hive] ${seeded} ticket rows in ${path.basename(DB_PATH)}`);
  console.log(`[ops-hive] http://127.0.0.1:${PORT}`);
});
