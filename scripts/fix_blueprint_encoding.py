"""
Fix encoding in core/blueprint_engine.py so it never crashes on Windows cp1252 consoles.
"""
from pathlib import Path

path = Path(r"c:\Users\harma\Desktop\PROJECTS\Keys-acendence-series\acendence-VIII_GEN-I\core\blueprint_engine.py")
text = path.read_text(encoding="utf-8")

old_explain = '''    def explain_master_prompt(self, blueprint: dict[str, Any], master_prompt: str) -> str:
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

new_explain = '''    def explain_master_prompt(self, blueprint: dict[str, Any], master_prompt: str) -> str:
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
        summary_str = "\\n".join(lines)
        self._notify("[*]", f"Master Prompt ready ({len(master_prompt)} chars) - target: {', '.join(manifest)}")
        return summary_str'''

if old_explain in text:
    text = text.replace(old_explain, new_explain, 1)
    path.write_text(text, encoding="utf-8")
    print("FIXED EXPLAIN ENCODING IN BLUEPRINT ENGINE")
else:
    print("Could not find old_explain")
