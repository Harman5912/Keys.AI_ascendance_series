/** The only surface the renderer can reach. */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("fieldnotes", {
  list: () => ipcRenderer.invoke("notes:list"),
  save: (note) => ipcRenderer.invoke("notes:save", note),
  toggle: (id) => ipcRenderer.invoke("notes:toggle", id),
});
