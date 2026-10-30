"""The target capability catalog — names, not implementations.

This is the list Keys.AI wants to be able to do. A name here exists only to make
the gap visible in the inventory: unless a registry skill claims it, its status
is PLANNED and no code pretends otherwise.

Naming rule: an entry is a capability, not a synonym. When a real skill covers
several of these names, the skill lists them in its manifest ``tags`` and the
inventory matches them — that is why "coding" does not need "code", "implement"
and "modify-code" as three separate modules.
"""

from __future__ import annotations

#: group -> capability names from the assignment
TARGET_CATALOG: dict[str, tuple[str, ...]] = {
    "planning": (
        "plan", "deep-plan", "analyze", "ask-user", "task-graph",
        "task-status", "task-resume", "self-review", "decision-log",
        "memory-search", "skill-search", "skill-create", "skill-update",
    ),
    "research": (
        "research", "deep-research", "web-search", "browser-open",
        "browser-control", "screenshot", "extract-web", "source-verify",
        "cross-check", "citation", "image-search", "image-download",
        "document-research", "repo-search", "repo-analyze", "research-report",
        "globe",
    ),
    "software": (
        "code", "architect", "project-scan", "codebase-map", "understand-code",
        "implement", "modify-code", "refactor", "debug", "fix-error",
        "dependency-check", "api-design", "api-integrate", "database-design",
        "migration", "frontend", "backend", "fullstack", "python",
        "javascript", "typescript", "desktop-app", "mobile-app", "cli-tool",
        "git", "code-review", "optimize-code", "documentation",
        "repo-inspect", "coding",
    ),
    "interface": (
        "ui-design", "ux-audit", "design-system", "component-build",
        "responsive", "animation", "accessibility", "visual-test",
        "ui-debug", "asset-search", "asset-integrate", "design-to-code",
    ),
    "testing": (
        "test-plan", "unit-test", "integration-test", "e2e-test",
        "smoke-test", "regression-test", "api-test", "browser-test",
        "test-coverage", "performance-test", "security-test", "test-report",
        "acceptance-check",
    ),
    "models": (
        "model-select", "model-test", "model-benchmark", "provider-check",
        "provider-switch", "ollama-detect", "ollama-run", "api-key-check",
        "agent-create", "agent-run", "agent-handoff", "multi-agent",
        "parallel-tasks", "tool-select", "tool-execute", "context-manage",
        "agent-evaluate", "workflow", "workflow-save", "agent-log",
    ),
    "documents": (
        "file-read", "file-write", "file-search", "file-organize",
        "file-diff", "pdf-read", "docx-read", "xlsx-analyze", "csv-analyze",
        "data-clean", "data-analyze", "visualize-data", "report-create",
        "export-pdf", "export-docx", "export-xlsx", "export-pptx",
        "artifact-verify", "files", "documents",
    ),
    "security": (
        "permission-check", "action-confirm", "secret-scan", "secure-code",
        "dependency-audit", "sandbox-run", "command-explain", "file-backup",
        "rollback", "access-audit", "privacy-check", "audit-log",
    ),
}


def all_names() -> list[str]:
    seen: list[str] = []
    for names in TARGET_CATALOG.values():
        for name in names:
            if name not in seen:
                seen.append(name)
    return seen
