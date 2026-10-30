# BASELINE_PERF.md — Baseline Performance Metrics

Date: 2026-10-29
Environment: Windows 11 Build 26300, RTX 3050 6GB Laptop GPU, Python 3.12.10

## 1. Local Model Benchmark (Ollama qwen3:8b)
- **Time to First Token / Cold Generation:** 16.67 seconds (Model loading into GPU/VRAM)
- **Subsequent Step Response Time:** 14 seconds (warm generation)
- **Sample Generation:** Prompt `"Reply with OK"` -> Output `"OK"`

## 2. Crown Code Bridge Headless Execution
- **Headless Distribution Size:** 167 KB (`dist-headless/headless.js`)
- **End-to-End Test (`test_crown_code.py`):**
  - Tool call `write_file`: Passed (Created `verify.txt`)
  - Tool call `terminal`: Shell recovery handled (`Get-Content` -> `type verify.txt`)
  - Process exit code: 0
  - Child process clean teardown: Verified (PASS E)
- **Overall Execution Duration:** ~42 seconds total for tool sequence write + test + cleanup.

## 3. Memory & Resource Footprint
- **Total Physical Memory:** 16,092 MB
- **Available Idle Memory:** ~3,500 MB
- **Target Idle Memory Overhead for v2 Engine:** <= legacy + 150 MB (excluding Ollama process)
