"""
Router (spec §22, §23): decide how to answer a request with ZERO LLM cost.

    chat        → conversational answer (provider)
    single_tool → one deterministic tool call (open X, search Y, weather...)
    plan        → multi-step task → LLM planner
    memory      → handled by the brain's memory path
    control     → stop / pause / resume

Pronoun/reference-aware: "run it" after "open ReviewBot" resolves to the
referenced project and routes to a plan (or code run) instead of asking
"run what?".
"""

from __future__ import annotations

import re


class RouteDecision:
    def __init__(self, kind: str = "chat", tool: str = "",
                 arguments: dict | None = None, reason: str = "",
                 message: str = ""):
        self.kind      = kind        # chat | single_tool | plan | control
        self.tool      = tool
        self.arguments = arguments or {}
        self.reason    = reason
        self.message   = message     # pre-baked clarification, if any

    def __repr__(self) -> str:
        return (f"RouteDecision(kind={self.kind}, tool={self.tool}, "
                f"args={self.arguments})")


class Router:
    def __init__(self, tool_registry, context):
        self._tools   = tool_registry
        self._context = context

    # ── main entry ───────────────────────────────────────────────────────
    def route(self, text: str, intent, resolved_text: str) -> RouteDecision:
        t = (resolved_text or text).strip()
        tl = " " + t.lower() + " "
        primary = intent.primary

        # control intents are handled by the brain itself
        if primary in ("STOP", "PAUSE", "RESUME"):
            return RouteDecision("control", reason="control intent")

        # memory intent → brain handles it
        if primary == "MEMORY":
            return RouteDecision("chat", reason="memory handled by brain")

        # ── multi-step / complex → plan (LLM) FIRST ──────────────────────
        # e.g. "open chrome and search for X and summarize" must become a
        # plan, not just the last matched single tool.
        if (primary == "MULTI_STEP_TASK"
                or "MULTI_STEP_TASK" in intent.tags
                or self._looks_multi_step(tl)):
            return RouteDecision("plan", reason="multi-step task detected")

        # ── single-tool patterns ─────────────────────────────────────────
        d = self._single_tool(text, resolved_text, tl, primary)
        if d is not None:
            return d

        # Coding intent → route to crown_code, the registered coding agent.
        # This used to name `live_code`, a tool that is neither declared nor
        # handled (its backing package `live_code.integration` does not exist),
        # so every typed "build me …" ended in "Unknown tool". `crown_code` is
        # in TOOL_HANDLERS and owns workspace creation, the recipe builders and
        # the bridge to the Crown Code agent.
        # …unless the sentence is a QUESTION ABOUT PAST WORK ("did you
        # actually run it?", "have you tested this?"). Those must be answered
        # honestly in chat — routing them to the coding agent answered a status
        # question with "I need your confirmation before I …", which reads as
        # the assistant claiming work it never reported on.
        if re.match(r"^\s*(?:did|have|has|had|was|were)\s+(?:you|it|this|keys)", tl):
            return RouteDecision("chat", reason="question about past work")
        if primary == "CODING" or "CODING" in intent.tags:
            return RouteDecision(
                "single_tool", "crown_code",
                {"action": "build", "description": text.strip()},
                "coding intent → crown_code")

        # generic command without a matched pattern → plan
        if primary == "COMMAND" or primary == "COMPUTER_ACTION":
            if self._last_ref():
                return RouteDecision("plan", reason="command with prior context")
            return RouteDecision("plan", reason="generic command")

        # question / conversation / unknown → chat
        return RouteDecision("chat", reason="conversational")

    # ── single-tool matchers ─────────────────────────────────────────────
    def _single_tool(self, text: str, resolved: str, tl: str,
                     primary) -> RouteDecision | None:

        # admin mode — legitimate UAC elevation only (spec §10–11: never
        # bypasses UAC, never touches security settings).
        # Verb-driven on purpose: "build me an admin dashboard" must keep
        # going to the coding agent, so build/product nouns skip this match.
        if re.search(r"\b(?:elevate\b|run\s+(?:this|it|keys(?:\.ai)?|the "
                     r"app|keysai)\s+as\s+admin\w*|"
                     r"make\s+(?:me|keys(?:\.ai)?|this)\s+(?:an?\s+)?admin\w*|"
                     r"give\s+me\s+(?:admin|administrator)\w*|"
                     r"admin(?:istrator)?\s+(?:mode|rights|privileges|access))",
                     tl):
            if not any(w in tl for w in ("dashboard", "website", "panel",
                                         "portal", " web", "build", "page")):
                # a question about privileges must READ status, not raise UAC
                verb = "elevation" if ("?" in (text or "") or
                                        re.search(r"\b(?:do|does|am|are|is)\b", tl)) \
                    else "elevate"
                return RouteDecision("single_tool", "computer_use",
                                     {"action": verb}, "elevation pattern")

        # open / launch app or website
        m = re.match(r"^\s*(?:open|launch|start)\s+(?:the\s+|the app\s+)?"
                     r"(.+?)\s*$", tl)
        if m and ("open" in tl or "launch" in tl or "start" in tl):
            app = m.group(1).strip().strip(".")
            app = re.sub(r"\b(app|application|program|software)\s*$", "",
                         app).strip()
            if app and len(app) <= 40 and not re.match(r"^[0-9\s]+$", app):
                # keep the user's casing when they capitalised it
                # (ReviewBot ≠ reviewbot); otherwise title-case simple names
                # (chrome → Chrome) which the open_app tool matches best.
                app = _original_case(text, app)
                if not any(c.isupper() for c in app):
                    app = app.title()
                if self._context is not None:
                    self._context.note_reference("app", app)
                return RouteDecision("single_tool", "open_app",
                                     {"app_name": app},
                                     "open-app pattern")

        # search the web
        m = re.search(r"\b(?:search|google|look up|research)\s+(?:the web|"
                      r"online)?\s*(?:for\s+)?(.+?)\s*$", tl)
        if m:
            q = m.group(1).strip().strip("?.")
            if q and "news" in q[:12]:
                mode = "news"
            else:
                mode = "research" if "research" in tl[:30] else "search"
            return RouteDecision("single_tool", "web_search",
                                 {"query": q, "mode": mode},
                                 "web-search pattern")

        # weather
        m = re.search(r"\bweather\s+(?:in|for|at\s+)?(.+?)\s*$", tl)
        if m:
            city = m.group(1).strip().strip("?.")
            if city:
                return RouteDecision("single_tool", "weather_report",
                                     {"city": city.title()},
                                     "weather pattern")

        # system status
        if re.search(r"\b(cpu|ram|system status|performance|temperature|"
                     r"memory usage|gpu|uptime)\b", tl):
            return RouteDecision("single_tool", "system_status", {},
                                 "system-status pattern")

        # reminder
        m = re.search(r"\bremind me\s+(?:to\s+)?(.+?)(?:\s+at\s+([0-9:.apm\s]+)"
                      r"|\s+on\s+([0-9./\-]+))?\s*$", tl)
        if m:
            message = m.group(1).strip().strip(".")
            time = (m.group(2) or m.group(3) or "").strip()
            args = {"message": message}
            if time:
                hm = re.search(r"(\d{1,2})[:.](\d{2})", time)
                if hm:
                    hour = int(hm.group(1))
                    minute = hm.group(2)
                    if "pm" in time and hour < 12:
                        hour += 12
                    args["time"] = f"{hour:02d}:{minute}"
                else:
                    args["time"] = time.replace(" ", "")
                date = re.search(r"(\d{4})-(\d{2})-(\d{2})", time)
                if date:
                    args["date"] = date.group(0)
            if "time" in args:
                return RouteDecision("single_tool", "reminder", args,
                                     "reminder pattern")
            return RouteDecision(
                "chat", reason="reminder needs a time",
                message=("I can set that reminder — what time should I set "
                         "it for?"))

        # send a message
        m = re.search(r"\bsend\s+(?:a\s+)?message\s+(?:to\s+)?(.+?)\s*:"
                      r"\s*(.+?)\s*$", tl)
        if m:
            receiver = m.group(1).strip()
            msg      = m.group(2).strip().strip(".")
            return RouteDecision(
                "single_tool", "send_message",
                {"receiver": receiver.title(), "message_text": msg,
                 "platform": "WhatsApp"},
                "send-message pattern")

        # youtube
        m = re.search(r"\b(?:play|summarize)\s+(.+?)\s+on\s+youtube\b", tl)
        if m:
            action = "summarize" if "summarize" in tl else "play"
            return RouteDecision("single_tool", "youtube_video",
                                 {"action": action, "query": m.group(1).strip()},
                                 "youtube pattern")

        # Live Code — only for explicit full-project requests
        # The AI decides which coding tool to use (live_code vs dev_agent vs code_helper)
        # so the router should NOT force-route generic coding words to live_code.

        # bare pronoun action with no reference → clarify (honest)
        m = re.match(r"^\s*(open|run|start|close|fix|edit|stop|launch|check)"
                     r"\s+(it|that|this|there)\s*$", tl)
        if m:
            return RouteDecision(
                "chat", reason="pronoun without reference",
                message=("I don't know what you'd like me to "
                         f"{m.group(1)} yet — tell me the file, app or "
                         "project and I'll do it."))

        return None

    def _last_ref(self):
        if self._context is not None:
            return self._context.last_reference()
        return None

    # ── heuristics ───────────────────────────────────────────────────────
    def _looks_multi_step(self, tl: str) -> bool:
        markers = ["and then", "first ", "then ", "after that", "next ",
                   "and open", "and run", "and create", "and write",
                   "and fix", "and send", "and search", "and summarize",
                   "and save", "and tell", "and check", "and test",
                   "and verify", "then ", "and start", "and install",
                   "and debug", "and read", "and close"]
        count = sum(1 for m in markers if m in tl)
        return count >= 2 or (" and " in tl and count >= 1)


def _original_case(text: str, token: str) -> str:
    """Return `token` as it appears (cased) inside `text`, so app names like
    'ReviewBot' keep their real casing instead of becoming 'Reviewbot'."""
    if not token:
        return token
    idx = (text or "").lower().find(token.lower())
    if idx != -1:
        return text[idx:idx + len(token)]
    return token
