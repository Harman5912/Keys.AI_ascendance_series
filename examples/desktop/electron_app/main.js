/**
 * Field Notes — Electron main process.
 *
 * The renderer never touches Node: it asks through `window.fieldnotes`, which
 * preload.js exposes over a narrow contextBridge. Notes persist to a JSON file
 * in the app's userData folder.
 */
const { app, BrowserWindow, ipcMain } = require("electron");
const path = require("node:path");
const fs = require("node:fs/promises");

const NOTES_FILE = () => path.join(app.getPath("userData"), "notes.json");

async function readNotes() {
  try {
    return JSON.parse(await fs.readFile(NOTES_FILE(), "utf-8"));
  } catch (err) {
    if (err.code === "ENOENT") return [];
    throw new Error(`Could not read notes: ${err.message}`);
  }
}

async function writeNotes(notes) {
  await fs.mkdir(path.dirname(NOTES_FILE()), { recursive: true });
  await fs.writeFile(NOTES_FILE(), JSON.stringify(notes, null, 2), "utf-8");
  return notes;
}

function registerIpc() {
  ipcMain.handle("notes:list", async () => ({ ok: true, notes: await readNotes() }));

  ipcMain.handle("notes:save", async (_event, note) => {
    const text = String(note?.text || "").trim();
    if (!text) return { ok: false, error: "A note needs some text." };
    const notes = await readNotes();
    notes.unshift({ id: Date.now(), text, done: false, at: new Date().toISOString() });
    return { ok: true, notes: await writeNotes(notes) };
  });

  ipcMain.handle("notes:toggle", async (_event, id) => {
    const notes = (await readNotes()).map((n) =>
      n.id === id ? { ...n, done: !n.done } : n);
    return { ok: true, notes: await writeNotes(notes) };
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 900,
    height: 640,
    minWidth: 520,
    title: "Field Notes",
    backgroundColor: "#101418",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(() => {
  registerIpc();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
