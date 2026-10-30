# syntax=docker/dockerfile:1
# ==========================================================================
# Keys.ai — Windows containerization attempt
# --------------------------------------------------------------------------
# IMPORTANT (see INSTALL.md): Keys.ai is a Windows-native desktop automation
# agent (PyQt6 GUI, pywinauto/pywin32, WASAPI loopback audio, WhatsApp
# Desktop control). Windows containers have NO interactive desktop session,
# so the agent itself cannot *execute* inside a container — but this image
# delivers the two things that ARE valuable and honest:
#
#   1. BUILD stage — a reproducible packaging environment: pinned Windows
#      Server Core + Python 3.12 + the exact requirements.txt + Playwright
#      Chromium, then PyInstaller produces the same dist/KeysAI executable
#      every single time ("consistent runtime" for packaging/CI).
#
#   2. RUNTIME stage — a slim image holding the built exe, the Playwright
#      browsers (PLAYWRIGHT_BROWSERS_PATH pinned to C:\ms-playwright) and a
#      config volume, ready to copy onto any Windows host with a desktop
#      session (docker cp / volumes), where the app actually runs.
#
# Requirements: Docker Desktop with "Windows containers" enabled
# (Linux containers cannot run Windows software).
# Build:  docker build --target build --tag keysai/build .
# ==========================================================================

FROM python:3.12-windowsservercore-ltsc2022 AS build

ENV PLAYWRIGHT_BROWSERS_PATH=C:\ms-playwright \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Dependencies first (layer cache wins)
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt && \
    python -m pip install --no-cache-dir pyinstaller && \
    python -m playwright install chromium

# 2) Source + build the distributable
COPY . .
RUN pyinstaller --noconfirm keysai.spec && dir /b dist

# --------------------------------------------------------------------------
FROM mcr.microsoft.com/windows/servercore:ltsc2022 AS runtime

ENV PLAYWRIGHT_BROWSERS_PATH=C:\ms-playwright
WORKDIR /app

# Built exe + browser binaries. NOTE: config is NOT copied from the build
# stage — real API keys / OAuth secrets must never live in an image.
# The config VOLUME below is mounted with the host's own keys at runtime.
COPY --from=build /app/dist /app/dist
COPY --from=build C:/ms-playwright C:/ms-playwright

VOLUME ["C:\\app\\config"]

CMD ["cmd", "/c", "echo Keys.ai built OK - copy /app/dist to a Windows host with a desktop session and run it there (see INSTALL.md)."]
