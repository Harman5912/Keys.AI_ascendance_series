"""
core/blueprint_engine.py — Blueprint Synthesizer & Master Prompt Generator.

Synthesizes Stage 1 requirements, Stage 2 research assets, and design tokens into
a deterministic BLUEPRINT.json and a fortified Master Prompt for Crown Code.

Pipeline Step 3:
  Requirements + Research Harvest -> BLUEPRINT.json + Fortified Master Prompt
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from core.build_recipes import detect_stacks, recipe_block


class BlueprintEngine:
    """Compiles specifications into deterministic execution blueprints and prompts."""

    def __init__(self, workspace: Path, player=None):
        self.workspace = Path(workspace).resolve()
        self.player = player

    def _notify(self, icon: str, message: str) -> None:
        if self.player:
            try:
                fn = getattr(self.player, "creation_event", None)
                if fn:
                    fn(icon, message)
            except Exception:
                pass
        try:
            print(f"[BlueprintEngine] {icon} {message}")
        except Exception:
            try:
                safe_msg = f"[BlueprintEngine] {message}".encode("ascii", errors="replace").decode("ascii")
                print(safe_msg)
            except Exception:
                pass

    def synthesize(self, task: str, requirements: str = "",
                   research_result: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate BLUEPRINT.json and return the master execution prompt."""
        self._notify("📐", "Synthesizing Architecture Blueprint & Master Prompt...")

        research = research_result or {}
        tokens = research.get("tokens", {})
        icons = research.get("icons", [])
        images = research.get("images", [])

        # Detect stacks & recipes
        stacks = detect_stacks(task)
        recipe = recipe_block(stacks)

        # Build target file manifest based on task and stack
        manifest = self._generate_manifest(task, stacks, icons, images)

        blueprint_data = {
            "task": task,
            "requirements": requirements,
            "stacks": stacks,
            "design_tokens": tokens,
            "assets": {
                "icons": icons,
                "images": images,
            },
            "manifest": manifest,
            "verification_command": self._verification_command(stacks),
        }

        # Write BLUEPRINT.json to workspace
        blueprint_file = self.workspace / "BLUEPRINT.json"
        blueprint_file.write_text(json.dumps(blueprint_data, indent=2), encoding="utf-8")
        self._notify("📑", "Saved BLUEPRINT.json in workspace")

        # Generate Master Prompt
        master_prompt = self._build_master_prompt(task, requirements, blueprint_data, recipe)
        explanation = self.explain_master_prompt(blueprint_data, master_prompt)
        return {
            "blueprint": blueprint_data,
            "blueprint_path": str(blueprint_file),
            "master_prompt": master_prompt,
            "explanation": explanation,
        }

    def explain_master_prompt(self, blueprint: dict[str, Any], master_prompt: str) -> str:
        """Format an exhaustive, human-readable breakdown of what the master prompt contains."""
        task = blueprint.get("task", "")
        manifest = [item.get("path") for item in blueprint.get("manifest", [])]
        icons = [Path(p).stem for p in blueprint.get("assets", {}).get("icons", [])]
        tokens = blueprint.get("design_tokens", {})
        stacks = blueprint.get("stacks", [])

        lines = [
            "=" * 78,
            "[BLUEPRINT] ARCHITECTURAL SPECIFICATION & MASTER INSTRUCTION PROMPT",
            "=" * 78,
            f"* Target Objective : {task}",
            f"* Stacks & Tools   : {', '.join(stacks) if stacks else 'Modern Web (HTML5/Tailwind/JS)'}",
            f"* Design Palette   : Primary {tokens.get('primary', '#3B82F6')}, Dark Slate {tokens.get('background', '#0F172A')}",
            f"* Target Files     : {', '.join(manifest)}",
            f"* Harvested SVGs   : {', '.join(icons[:8]) if icons else 'standard vector icons'}",
        ]

        if "harman" in task.lower() or "harman" in master_prompt.lower():
            lines.extend([
                "* Subject Profile  : Harman Sadhwani (Creator of Keys.ai | Lead AI Architect)",
                "* Showcased Work   : Keys.ai, ReviewBot, Drop of Hope, BharatHealth",
                "* Core Skillset    : Python, TypeScript, React, PyTorch, PySide6, Local LLMs, Agentic Systems",
                "* Aesthetic Spec   : Modern Dark Glassmorphism, Interactive Dynamic Filters, Animated Counters",
            ])

        lines.extend([
            "* Execution Mode   : Bespoke Autonomous Local Model (NO PRESET DESIGN TEMPLATES)",
            "=" * 78,
        ])
        summary_str = "\n".join(lines)
        self._notify("[*]", f"Master Prompt ready ({len(master_prompt)} chars) - target: {', '.join(manifest)}")
        return summary_str

    def _generate_manifest(self, task: str, stacks: list[str],
                           icons: list[str], images: list[str]) -> list[dict[str, str]]:
        """Determine target files to create based on project domain."""
        task_lower = task.lower()
        manifest = []

        # 1. Games (Python / Pygame / Arcade)
        if any(w in task_lower for w in ("game", "pygame", "arcade", "shooter", "snake", "pong", "platformer", "puzzle")):
            manifest.append({"path": "main.py", "role": "Game launch entry point, Pygame init, display setup and main game loop"})
            manifest.append({"path": "game.py", "role": "Game engine state, player/entities, physics update, collision and scoring logic"})
            manifest.append({"path": "constants.py", "role": "Window dimensions, FPS, design token color constants, and keybinding configs"})
            manifest.append({"path": "requirements.txt", "role": "Python dependencies (pygame>=2.5.0)"})
            manifest.append({"path": "test_game.py", "role": "Headless unit tests verifying state, player movement, score tracking and restart"})
        # 2. Android / Mobile Apps
        elif any(w in task_lower for w in ("android", "apk", "kotlin", "jetpack compose", "compose", "mobile app")):
            manifest.append({"path": "app/build.gradle.kts", "role": "Gradle build script with Android & Compose dependencies"})
            manifest.append({"path": "app/src/main/AndroidManifest.xml", "role": "Android application package and activity manifest"})
            manifest.append({"path": "app/src/main/java/com/example/app/MainActivity.kt", "role": "MainActivity with Jetpack Compose UI"})
            manifest.append({"path": "app/src/main/java/com/example/app/ui/Theme.kt", "role": "Material 3 theme, typography and color tokens"})
            manifest.append({"path": "test_app.py", "role": "Automated verification test validating project structure and components"})
        # 3. Python Desktop Apps (PyQt6 / Tkinter)
        elif "python-desktop" in stacks or "pyqt" in task_lower or "desktop" in task_lower:
            manifest.append({"path": "main.py", "role": "Application entry point and main event loop"})
            manifest.append({"path": "ui.py", "role": "UI layout, widgets, and theme bindings"})
            manifest.append({"path": "requirements.txt", "role": "Python dependencies"})
            manifest.append({"path": "test_app.py", "role": "Automated verification test"})
        # 4. Backend APIs / Fullstack
        elif "fastapi" in task_lower or "backend" in task_lower or "api" in task_lower:
            manifest.append({"path": "main.py", "role": "FastAPI backend server and API routes"})
            manifest.append({"path": "requirements.txt", "role": "Server dependencies"})
            manifest.append({"path": "static/index.html", "role": "Interactive front-end dashboard"})
            manifest.append({"path": "static/app.js", "role": "Front-end data fetching and chart rendering"})
            manifest.append({"path": "test_api.py", "role": "Endpoint verification tests"})
        # 5. React / Vite Apps
        elif "react" in task_lower or "vite" in task_lower:
            manifest.append({"path": "package.json", "role": "Project dependencies and scripts"})
            manifest.append({"path": "index.html", "role": "HTML entry point"})
            manifest.append({"path": "src/main.tsx", "role": "React DOM mount"})
            manifest.append({"path": "src/App.tsx", "role": "Core component and dashboard layout"})
            manifest.append({"path": "src/index.css", "role": "Tailwind and theme styles"})
        # 6. Personal Portfolios / Developer Showcase
        elif any(w in task_lower for w in ("portfolio", "resume", "cv", "harman")):
            manifest.append({"path": "index.html", "role": "Complete bespoke single-page portfolio layout with Hero, About, Projects, Skills, and Contact"})
            manifest.append({"path": "styles.css", "role": "Custom glassmorphism styling, glowing hover effects, keyframes animations, and token variables"})
            manifest.append({"path": "app.js", "role": "Interactive project filtering, smooth scroll, contact form handler, and live stat counters"})
            manifest.append({"path": "test_app.py", "role": "Automated headless validation verifying sections, links, and asset integrity"})
        # 7. Websites / Landing Pages / Web Apps
        else:
            manifest.append({"path": "index.html", "role": "Complete interactive responsive layout with Tailwind CDN"})
            manifest.append({"path": "app.js", "role": "Client application logic, navigation, and state management"})
            manifest.append({"path": "styles.css", "role": "Custom styling, animations, and design tokens"})
            manifest.append({"path": "test_app.py", "role": "Automated headless validation script"})

        return manifest

    def _verification_command(self, stacks: list[str]) -> str:
        if "react" in stacks:
            return "npm run build"
        if "python-desktop" in stacks or "fastapi" in stacks:
            return "python -m py_compile main.py"
        return "python -c \"import os; assert os.path.exists('main.py') or os.path.exists('index.html') or os.path.exists('app'), 'Missing build artifact'\""

    def _build_master_prompt(self, task: str, requirements: str,
                             blueprint: dict[str, Any], recipe: str) -> str:
        """Compose the local-model fortified master instruction prompt."""
        manifest_md = "\n".join(f"- `{item['path']}`: {item['role']}" for item in blueprint["manifest"])
        icons_md = "\n".join(f"  - `{icon}`" for icon in blueprint["assets"]["icons"])
        tokens = blueprint["design_tokens"]

        # Rich portfolio context if applicable
        portfolio_context = ""
        if "harman" in task.lower() or "harman" in requirements.lower():
            portfolio_context = """
================================================================================
SUBJECT PROFILE CONTEXT: HARMAN SADHWANI
================================================================================
Identity: Harman Sadhwani
Role: Lead AI & Systems Architect | Creator of Keys.ai
Tagline: Architecting autonomous computer agents, screen-understanding vision systems, and robust multi-agent engineering workflows.
Bio: Full-stack AI systems engineer with deep expertise in Python, PyTorch, local LLM orchestration (Ollama/vLLM), desktop automation, and clean architectural design. Creator of Keys.ai.

FEATURED PROJECTS TO SHOWCASE IN THE PORTFOLIO:
1. Keys.ai (Flagship Desktop AI Agent)
   - Description: Autonomous desktop AI assistant and screen-understanding computer agent with Gemini Live affective audio, local Ollama execution, and self-healing automation.
   - Stack: Python 3.12, PySide6, OpenCV, Gemini Live API, Ollama, LangChain Deep Agents.
   - Highlights: Screen perception, voice takeover, autonomous software development, multi-agent orchestration.
   - Tags: ["AI Agent", "Python", "Computer Vision", "Desktop OS"]

2. ReviewBot (Automated Code Quality Gate)
   - Description: AI-powered automated GitHub PR review and quality enforcement bot with multi-model consensus, AST static analysis, and security scanning.
   - Stack: TypeScript, Node.js, GitHub REST/GraphQL API, Docker, FastAPI.
   - Tags: ["DevOps", "Code Review", "Security", "GitHub App"]

3. Drop of Hope (Community Blood Matching Platform)
   - Description: Real-time emergency blood donation platform connecting nearby donors with hospital urgent requests via geospatial matching and instant SMS/WhatsApp alerts.
   - Stack: React, Next.js, FastAPI, PostgreSQL, WebSockets, Leaflet Maps.
   - Tags: ["Social Impact", "Healthcare", "Full-Stack", "Real-Time"]

4. BharatHealth (AI Clinical Management Ecosystem)
   - Description: AI-assisted clinical diagnosis support and electronic health record management designed for rural and urban clinic accessibility.
   - Stack: Python, PyTorch, React Native, SQLite WAL, Whisper Audio.
   - Tags: ["Healthcare AI", "Diagnostics", "Mobile", "Edge Computing"]

TECHNICAL SKILLS TO DISPLAY:
- AI & Machine Learning: Gemini Live API, Ollama, PyTorch, HuggingFace, Autonomous Agents, Prompt Architecture
- Systems & Desktop: Python 3.12, PyQt6 / Tkinter, Windows Automation, Multi-threading, AsyncIO
- Web & Full-Stack: TypeScript, React, Next.js, Tailwind CSS, FastAPI, WebSockets
- DevOps & Tooling: Git, Docker, Linux, CI/CD, Pytest, Playwright
================================================================================
"""

        prompt = f"""You are Crown Code, an elite senior software engineer.

TASK OBJECTIVE:
{task}
{portfolio_context}

CONFIRMED REQUIREMENTS:
The user chose to start without answering the clarifying questions.
{requirements or 'Build a production-ready, feature-complete implementation matching the objective.'}

AVAILABLE ASSETS (ALREADY DOWNLOADED IN WORKSPACE):
- Vector Icons (use these via <img> or inline SVG):
{icons_md or '  - None'}
- Design Tokens (from assets/design_tokens.json):
  - Primary Color: {tokens.get('primary', '#3B82F6')}
  - Background: {tokens.get('background', '#0F172A')}
  - Surface/Card: {tokens.get('surface', '#1E293B')}
  - Text: {tokens.get('text', '#F8FAFC')}

TARGET FILE MANIFEST (CREATE EACH FILE IN THIS ORDER):
{manifest_md}

WORKSPACE STATE: this folder is empty
The workspace folder already has assets/ and references/ prepared for you.
Do not search for a file before writing it. DO NOT search for files that do not exist yet.
Use write_file to create each file in the manifest with COMPLETE, WORKING, PRODUCTION CODE.
Never write placeholder comments like '// implement here' or 'TODO'.
Ensure all buttons, interactive charts, and views are fully functional.

SHELL ENVIRONMENT:
You are operating on Windows (cmd).
- Use Windows commands: `type`, `dir`, `python`, `npm`, etc.
- Do NOT use Linux commands like `cat`, `ls`, or `sudo`.

FINAL VERIFICATION:
Run the verification check: `{blueprint['verification_command']}`.
Ensure all files exist and are verified before reporting completion.
"""
        if recipe:
            prompt += f"\n\nTECHNICAL STACK RECIPE:\n{recipe}"

        return prompt
