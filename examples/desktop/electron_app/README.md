# Field Notes — Electron desktop application

A working Electron app with the security defaults the recipe requires:
`contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, and a
narrow `contextBridge` in `preload.js` — the renderer cannot reach Node.

## Run it

```bash
cd examples/desktop/electron_app
npm install
npm start
```

Static checks without launching a window:

```bash
node --check main.js && node --check preload.js && node --check renderer/app.js
```

Notes are stored in `app.getPath("userData")/notes.json`, so they survive a
restart.

## Files

| File | Purpose |
| --- | --- |
| `main.js` | window creation, IPC handlers (`notes:list/save/toggle`) |
| `preload.js` | the only API the renderer sees |
| `renderer/` | the UI — plain HTML/CSS/JS, no bundler |
