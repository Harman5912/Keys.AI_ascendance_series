"""
Enhance core/blueprint_engine.py with portfolio intelligence & master prompt explanation.
"""
from pathlib import Path

path = Path(r"c:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I\core\blueprint_engine.py")
text = path.read_text(encoding="utf-8")

# Add explain_master_prompt method to BlueprintEngine
old_synthesize = '''        # Generate Master Prompt
        master_prompt = self._build_master_prompt(task, requirements, blueprint_data, recipe)
        return {
            "blueprint": blueprint_data,
            "blueprint_path": str(blueprint_file),
            "master_prompt": master_prompt,
        }'''

new_synthesize = '''        # Generate Master Prompt
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
            "📜 ARCHITECTURAL BLUEPRINT & MASTER INSTRUCTION PROMPT SYNTHESIZED",
            "=" * 78,
            f"🎯 Target Objective: {task}",
            f"📦 Stacks & Tools  : {', '.join(stacks) if stacks else 'Modern Web (HTML5/Tailwind/JS)'}",
            f"🎨 Design Palette  : Primary {tokens.get('primary', '#3B82F6')}, Dark Slate {tokens.get('background', '#0F172A')}",
            f"📁 Target Files    : {', '.join(manifest)}",
            f"⚡ Harvested SVGs  : {', '.join(icons[:8]) if icons else 'standard vector icons'}",
        ]

        if "harman" in task.lower() or "harman" in master_prompt.lower():
            lines.extend([
                "👤 Subject Profile : Harman Sadhwani (Creator of Keys.ai | Lead AI Architect)",
                "🌟 Showcased Work  : Keys.ai, ReviewBot, Drop of Hope, BharatHealth",
                "🛠️ Core Skillset   : Python, TypeScript, React, PyTorch, PySide6, Local LLMs, Agentic Systems",
                "✨ Aesthetic Spec  : Modern Dark Glassmorphism, Interactive Dynamic Filters, Animated Counters",
            ])

        lines.extend([
            "⚙️ Execution Mode  : Bespoke Autonomous Local Model (NO PRESET DESIGN TEMPLATES)",
            "=" * 78,
        ])
        summary_str = "\\n".join(lines)
        self._notify("📜", f"Master Prompt ready ({len(master_prompt)} chars) — target: {', '.join(manifest)}")
        return summary_str'''

if old_synthesize in text:
    text = text.replace(old_synthesize, new_synthesize, 1)

# Enhance _generate_manifest for portfolios
old_manifest = '''        # 6. Websites / Landing Pages / Web Apps
        else:
            manifest.append({"path": "index.html", "role": "Complete interactive responsive layout with Tailwind CDN"})
            manifest.append({"path": "app.js", "role": "Client application logic, navigation, and state management"})
            manifest.append({"path": "styles.css", "role": "Custom styling, animations, and design tokens"})
            manifest.append({"path": "test_app.py", "role": "Automated headless validation script"})'''

new_manifest = '''        # 6. Personal Portfolios / Developer Showcase
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
            manifest.append({"path": "test_app.py", "role": "Automated headless validation script"})'''

if old_manifest in text:
    text = text.replace(old_manifest, new_manifest, 1)

# Enhance _build_master_prompt with rich portfolio details
old_bmp = '''        prompt = f"""You are Crown Code, an elite senior software engineer.

TASK OBJECTIVE:
{task}'''

new_bmp = '''        # Rich portfolio context if applicable
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
{portfolio_context}'''

if old_bmp in text:
    text = text.replace(old_bmp, new_bmp, 1)

path.write_text(text, encoding="utf-8")
print("BLUEPRINT ENGINE PATCHED OK")
