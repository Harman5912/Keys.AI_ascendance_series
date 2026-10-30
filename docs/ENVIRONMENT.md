# ENVIRONMENT.md — System & Runtime Configuration

Date: 2026-10-29
Branch: `crown-code-v2`
Baseline Tag: `pre-crown-v2`

## 1. Host Operating System & Hardware
- **Operating System:** Microsoft Windows 11 Home Single Language (Build 10.0.26300)
- **Processor / Hardware:** Lenovo Laptop (BIOS NECN47WW)
- **System Memory:** 16,092 MB RAM (~3.5 GB available)
- **GPUs:**
  1. NVIDIA GeForce RTX 3050 6GB Laptop GPU (Driver 32.0.16.1742)
  2. Intel(R) UHD Graphics (Integrated)
- **Storage:** Drive C: Used 410 GB, Free ~64.5 GB

## 2. Tool & Runtime Toolchain
- **Python:** Python 3.12.10 (venv at `.\.venv\Scripts\python.exe`)
- **Node.js:** v26.5.0
- **Git:** git version 2.55.0.windows.3
- **Local Model Server:** Ollama running at `http://127.0.0.1:11434`

## 3. Installed Local Ollama Models (Active Inventory)
- `qwen3:8b` (Primary recommended general agent model)
- `qwen3-coder:30b` (Primary recommended heavy coder model)
- `qwen2.5-coder:7b` (Search/replace edit mode model)
- `qwen2.5-coder:3b`
- `qwen3.5:4b`
- `qwen3:30b`
- `deepseek-r1:8b`
- `llama3.2-vision:latest` (Vision judge capability)
- `llava:latest`
- `tinyllama:latest`

## 4. Crown Code Runtime
- **Node Bridge Target:** `c:\Users\harma\Desktop\PROJECTS\Crown CODE`
- **Headless Distribution:** `Crown CODE\dist-headless\headless.js`
- **Keys.AI UI Framework:** Python / Tkinter GUI
