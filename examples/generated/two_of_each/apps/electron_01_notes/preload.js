const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  saveNote: (note) => ipcRenderer.invoke('notes:save', note),
  listNotes: () => ipcRenderer.invoke('notes:list')
})