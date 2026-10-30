"""
Intelligent intent understanding (spec §5).

Classifies what the user wants into a primary intent plus secondary tags,
e.g. "Open VS Code and fix the error in my Python project"
    -> primary COMPUTER_ACTION, tags {CODING, MULTI_STEP_TASK}

The classifier is deterministic (fast, free, works offline). An optional
LLM refinement hook exists but is OFF by default (config intent.llm_refine).
"""

from __future__ import annotations

import re


# ── canonical intents ────────────────────────────────────────────────────────
CONVERSATION    = "CONVERSATION"
QUESTION        = "QUESTION"
COMMAND         = "COMMAND"
COMPUTER_ACTION = "COMPUTER_ACTION"
FILE_OPERATION  = "FILE_OPERATION"
CODING          = "CODING"
WEB_RESEARCH    = "WEB_RESEARCH"
APP_CONTROL     = "APP_CONTROL"
MULTI_STEP_TASK = "MULTI_STEP_TASK"
REMINDER        = "REMINDER"
MEMORY          = "MEMORY"
SYSTEM_TASK     = "SYSTEM_TASK"
STOP            = "STOP"
PAUSE           = "PAUSE"
RESUME          = "RESUME"
UNKNOWN         = "UNKNOWN"

ALL_INTENTS = [
    CONVERSATION, QUESTION, COMMAND, COMPUTER_ACTION, FILE_OPERATION,
    CODING, WEB_RESEARCH, APP_CONTROL, MULTI_STEP_TASK, REMINDER, MEMORY,
    SYSTEM_TASK, STOP, PAUSE, RESUME, UNKNOWN,
]


class IntentResult:
    def __init__(self, primary: str = UNKNOWN, tags: list[str] | None = None,
                 confidence: float = 0.0, tool_hint: str = "",
                 reason: str = ""):
        self.primary    = primary
        self.tags       = list(dict.fromkeys(tags or []))  # dedupe, keep order
        self.confidence = confidence
        self.tool_hint  = tool_hint
        self.reason     = reason

    def __repr__(self) -> str:
        return (f"IntentResult(primary={self.primary}, tags={self.tags}, "
                f"confidence={self.confidence:.2f})")


# ── keyword banks (lowercase matching) ──────────────────────────────────────
_WORD = r"(?<![a-z]){}"

_STOP_WORDS = ["stop", "cancel", "abort", "quit", "halt", "dur", "iptal",
               "kes", "durdur", "stand down"]

_PAUSE_WORDS = ["pause", "hold on", "wait a moment", "bekle", "duraklat"]

_RESUME_WORDS = ["resume", "continue", "go on", "keep going", "devam",
                 "kaldığın yerden"]

_MEMORY_SAVE = ["remember", "don't forget", "do not forget", "always remember",
                "never forget", "keep in mind", "hatırla", "unutma"]
_MEMORY_FORGET = ["forget", "remove from memory", "unlearn", "sil that memory",
                  "unut"]
_MEMORY_RECALL = ["what do you know about me", "what do you remember",
                  "what do you remember about me", "what have you stored",
                  "what did we talk about", "what did we work on",
                  "show my memory", "what's in my memory"]

_REMINDER_WORDS = ["remind me", "set a reminder", "set reminder", "reminder",
                   "hatırlat", "hatırlatma"]

_WEB_WORDS = ["search the web", "search online", "search for", "web search",
              "look up", "find out", "google it", "research", "latest news",
              "what is the latest", "current events", "check the news",
              "price of", "compare prices", "araştır", "internette ara",
              "ara"]

_COMPUTER_WORDS = ["open", "close", "click", "double click", "right click",
                   "type ", "press ", "scroll", "volume", "brightness",
                   "screenshot", "minimize", "maximize", "switch to",
                   "focus", "shutdown", "restart", "turn off", "turn on",
                   "wifi", "mute", "unmute", "hotkey", "paste", "copy",
                   "run ", "launch", "start ", "stop the app", "kill"]

_APP_NAMES = ["vscode", "vs code", "visual studio", "chrome", "browser",
              "whatsapp", "notepad", "word", "excel", "powerpoint",
              "discord", "spotify", "terminal", "cmd", "powershell",
              "explorer", "file explorer", "steam", "telegram", "instagram",
              "calculator", "paint", "outlook", "gmail", "youtube",
              "google", "bing", "yahoo", "edge", "firefox", "netflix",
              "vlc", "slack", "zoom", "teams", "github", "figma",
              "spotify", "photoshop", "blender", "unity", "steam"]

_CODING_WORDS = ["code", "python", "javascript", "typescript", "java", "c++",
                 "cpp", "rust", "go lang", "golang", "flask", "django",
                 "react", "node", "api", "bug", "error", "fix", "debug",
                 "refactor", "compile", "build ", "function", "script",
                 "program", "variable", "repository", "repo", "git",
                 "commit", "branch", "pull request", "test suite", "pytest",
                 "unit test", "syntax", "exception", "traceback", "class ",
                 "import ", ".py", ".js", ".ts", ".html", ".css", ".java",
                 ".cpp", "dependency", "pip install", "npm install",
                 "terminal command"]

_FILE_WORDS = ["create a file", "create file", "write a file", "write file",
               "delete file", "delete the file", "move file", "rename",
               "copy file", "read file", "read the file", "open file",
               "save file", "folder", "directory", "new folder", "create a folder",
               "desktop", "documents", "downloads", "file explorer", "list files",
               "disk usage", "organize"]

_SYSTEM_WORDS = ["system status", "cpu", "ram", "memory usage", "gpu",
                 "temperature", "uptime", "processes", "system monitor",
                 "performance", "battery", "storage", "disk space", "bluetooth",
                 "display settings", "night light", "dark mode", "light mode"]

_QUESTION_WORDS = ["what is", "what's", "who is", "who's", "how do", "how to",
                   "how does", "why is", "why does", "when is", "where is",
                   "can you explain", "explain", "tell me about", "define",
                   "meaning of", "difference between", "which is"]

_CONVERSATION_WORDS = ["hello", "hi", "hey", "good morning", "good afternoon",
                       "good evening", "how are you", "how's it going", "thank",
                       "thanks", "who are you", "what can you do", "goodbye",
                       "bye", "nice to meet you", "merhaba", "selam",
                       "teşekkür", "günaydın", "iyi akşamlar", "nasılsın"]

_MULTI_STEP_MARKERS = ["and then", "then ", "first ", "next ", "after that",
                       "step 1", "step 2", "then run", "and run", "and open",
                       "and create", "and fix", "and write", "and test",
                       "and send", "and search", "and summarize", "and save",
                       "and tell", "and report", "then tell", "then check",
                       "once you", "after you", "in the end", "finally",
                       "and verify", "and start", "and install", "and debug"]


def _contains_any(text: str, words: list[str]) -> bool:
    """Substring match, except single short keywords which must match on
    word boundaries. Without that, the 'api' inside 'capi tal' — or 'capital'
    — tagged every geography question as a coding intent and routed it to the
    coding tool instead of chat."""
    import re as _re
    for w in words:
        if len(w) <= 4 and w.isalnum():
            if _re.search(rf"\b{_re.escape(w)}\b", text):
                return True
        elif w in text:
            return True
    return False


class IntentClassifier:
    def __init__(self, provider=None, llm_refine: bool = False):
        self._provider = provider
        self._llm_refine = llm_refine

    def classify(self, text: str) -> IntentResult:
        t = " " + (text or "").lower().strip() + " "
        tags: list[str] = []
        scores: dict[str, int] = {}
        reason_bits: list[str] = []

        def hit(intent: str, words: list[str], reason: str, weight: int = 1):
            if _contains_any(t, words):
                scores[intent] = scores.get(intent, 0) + weight
                reason_bits.append(reason)
                if intent not in tags:
                    tags.append(intent)

        # high-priority control / memory / reminders
        hit(STOP, _STOP_WORDS, "stop word", 5)
        hit(PAUSE, _PAUSE_WORDS, "pause word", 5)
        hit(RESUME, _RESUME_WORDS, "resume word", 5)
        hit(MEMORY, _MEMORY_SAVE + _MEMORY_FORGET + _MEMORY_RECALL,
            "memory phrase", 4)
        hit(REMINDER, _REMINDER_WORDS, "reminder phrase", 4)
        hit(SYSTEM_TASK, _SYSTEM_WORDS, "system phrase", 3)

        # tool-domain tags
        hit(WEB_RESEARCH, _WEB_WORDS, "web phrase")
        hit(COMPUTER_ACTION, _COMPUTER_WORDS, "computer verb")
        hit(APP_CONTROL, _APP_NAMES, "app name")
        hit(CODING, _CODING_WORDS, "coding phrase")
        hit(FILE_OPERATION, _FILE_WORDS, "file phrase")

        # multi-step markers
        if _contains_any(t, _MULTI_STEP_MARKERS):
            scores[MULTI_STEP_TASK] = scores.get(MULTI_STEP_TASK, 0) + 2
            reason_bits.append("multi-step marker")
            if MULTI_STEP_TASK not in tags:
                tags.append(MULTI_STEP_TASK)

        # question / conversation fallbacks
        if _contains_any(t, _QUESTION_WORDS) or t.strip().endswith("?"):
            scores[QUESTION] = scores.get(QUESTION, 0) + 3
            if QUESTION not in tags:
                tags.append(QUESTION)
        if _contains_any(t, _CONVERSATION_WORDS):
            scores[CONVERSATION] = scores.get(CONVERSATION, 0) + 2
            if CONVERSATION not in tags:
                tags.append(CONVERSATION)

        # command: an action verb starting the sentence
        action_start = re.match(
            r"\s*(open|close|click|type|press|scroll|run|start|stop|launch|"
            r"send|create|delete|move|copy|rename|edit|fix|search|play|call|"
            r"show|tell|set|change|turn|switch|mute|unmute|shutdown|restart|"
            r"read|write|make|install|open|download|find|check)\b", t)
        if action_start and COMMAND not in tags:
            tags.append(COMMAND)
            scores[COMMAND] = scores.get(COMMAND, 0) + 1

        # ── primary selection ────────────────────────────────────────────
        primary = UNKNOWN
        best = 0
        # Priority order breaks ties in favour of the more specific intent.
        priority = [STOP, PAUSE, RESUME, MEMORY, REMINDER, SYSTEM_TASK,
                    WEB_RESEARCH, MULTI_STEP_TASK, FILE_OPERATION, CODING,
                    APP_CONTROL, COMPUTER_ACTION, QUESTION, COMMAND,
                    CONVERSATION]
        for intent in priority:
            sc = scores.get(intent, 0)
            if sc > best:
                best = sc
                primary = intent

        if primary == UNKNOWN and tags:
            primary = tags[0]

        # Multi-step is almost always a modifier of another intent, never
        # the primary when a concrete action domain is present.
        if primary == MULTI_STEP_TASK and (COMPUTER_ACTION in tags
                                           or CODING in tags
                                           or WEB_RESEARCH in tags
                                           or FILE_OPERATION in tags):
            primary = (COMPUTER_ACTION if COMPUTER_ACTION in tags
                       else CODING if CODING in tags
                       else WEB_RESEARCH if WEB_RESEARCH in tags
                       else FILE_OPERATION)

        if primary == UNKNOWN and not tags:
            primary = COMMAND if action_start else CONVERSATION

        # tool hint for fast single-step routing
        tool_hint = _tool_hint(primary, t)
        conf = min(1.0, 0.35 + 0.13 * best + 0.1 * (len(tags) - 1))
        return IntentResult(primary, tags, round(conf, 2), tool_hint,
                            "; ".join(reason_bits[:3]))


def _tool_hint(primary: str, t: str) -> str:
    hints = {
        STOP: "stop", PAUSE: "pause", RESUME: "resume",
        MEMORY: "save_memory", REMINDER: "reminder",
        WEB_RESEARCH: "web_search", SYSTEM_TASK: "system_status",
    }
    if primary in hints:
        return hints[primary]
    if primary == APP_CONTROL:
        return "open_app"
    if primary in (CODING,):
        return "code_helper"
    if primary == FILE_OPERATION:
        return "file_controller"
    if primary == COMPUTER_ACTION:
        return "computer_use" if "app" in t else "computer_settings"
    return ""
