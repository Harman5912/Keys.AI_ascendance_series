"""WhatsApp messaging: chat opening, identity verification, send +
verification, message queue with duplicate protection (spec 8-10, 19-22).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class OperationRecord:
    """Spec 19: per-message operation identity for duplicate protection.
    States: prepared -> attempted -> possibly_sent -> confirmed | failed.
    An operation_id ties a retry to the SAME logical send so we never
    resend blindly after a verification timeout."""

    def __init__(self, target: str, message: str):
        self.operation_id = uuid.uuid4().hex[:12]
        self.target = target
        self.message = message
        self.created_at = time.time()
        self.attempt_count = 0
        self.state = "prepared"
        self.last_evidence: str = ""

    def mark(self, state: str, evidence: str = ""):
        self.state = state
        if evidence:
            self.last_evidence = evidence

    def as_dict(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "target": self.target,
            "message": self.message[:60],
            "attempt_count": self.attempt_count,
            "state": self.state,
            "created_at": self.created_at,
        }


class WhatsAppQueue:
    """Spec 21-22: persistent pending-message queue. Survives browser
    disconnects (saved to disk); safe-resume revalidates before sending.
"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or Path.home() / ".keysai_profiles" / "whatsapp" / "queue.json"
        self._items: list[dict] = []
        self._paused = False
        self._load()

    def _load(self):
        try:
            if self._path.exists():
                self._items = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._items = []

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._items), encoding="utf-8")
        except Exception:
            pass

    def enqueue(self, target: str, message: str,
                record: Optional[OperationRecord] = None) -> OperationRecord:
        """Queue a message. Pass the SAME OperationRecord used by the caller
        so later state updates (confirmed / possibly_sent / failed) land on
        the queued item — otherwise the operation_id would never match and
        the queue would keep stale pending items (duplicate-protection bug)."""
        rec = record or OperationRecord(target, message)
        self._items.append(rec.as_dict())
        self._save()
        return rec

    def pending(self) -> list[dict]:
        return [i for i in self._items if i["state"] not in ("confirmed", "failed")]

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def paused(self) -> bool:
        return self._paused

    def update(self, operation_id: str, state: str):
        for i in self._items:
            if i["operation_id"] == operation_id:
                i["state"] = state
                i["attempt_count"] = i.get("attempt_count", 0) + 1
                self._save()
                return

    def count(self) -> int:
        return len(self.pending())


class SendVerifier:
    """Spec 20: verify a send with DOM evidence before reporting success.
    Never reports "sent" on a fixed timer — only on evidence.
"""

    def __init__(self, driver, log=None):
        self.driver = driver
        self.log = log or (lambda _m: None)

    def message_visible(self, text: str) -> bool:
        try:
            texts = self.driver.outgoing_texts()
            needle = text.strip()[:50]
            return any(needle and needle in t.strip()[:50] for t in texts)
        except Exception:
            return False

    def composer_cleared(self) -> bool:
        try:
            return not (self.driver.composer_text() or "").strip()
        except Exception:
            return False

    def verify(self, operation: OperationRecord, timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.message_visible(operation.message):
                operation.mark("confirmed", "message text visible in pane");
                return True
            time.sleep(0.4)
        operation.mark("possibly_sent", "verification timeout - evidence unknown")
        return False


class ChatOpener:
    """Spec 8-10: open a chat and VERIFY it is the right one before
    proceeding. Never sends to an unverified conversation."""

    def __init__(self, driver, log=None):
        self.driver = driver
        self.log = log or (lambda _m: None)

    def open(self, target: str, timeout: float = 20.0) -> tuple[bool, str]:
        self.log(f"[WA] STATE: CHAT_OPENING | TARGET: {target}")
        try:
            if not self.driver.search_and_select(target):
                return False, f"chat {target} not found in list"
        except Exception as e:
            return False, f"search failed: {str(e)[:120]}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                title = self.driver.chat_title()
                if title and self._matches(title, target):
                    if self.driver.message_pane_visible():
                        return True, f"chat {target} opened and verified"
            except Exception:
                pass
            time.sleep(0.4)
        return False, f"chat {target} did not reach ready state"

    @staticmethod
    def _matches(title: str, target: str) -> bool:
        """Word-boundary identity check (spec 9): 'Ali' must NOT verify
        against a chat titled 'Alicia'. Exact match or whole-word match,
        and reject too-short targets."""
        t = (title or "").strip().lower()
        tg = (target or "").strip().lower()
        if not t or not tg or len(tg) < 2:
            return False
        if t == tg:
            return True
        return re.search(r"(?<![a-z0-9])" + re.escape(tg) + r"(?![a-z0-9])", t) is not None


class MessageSender:
    """Spec 19-20, 44: one verified, duplicate-safe send.
    OPEN -> VERIFY CHAT -> TYPE -> SEND -> VERIFY. On verification timeout
    we re-check evidence before ever resending."""

    def __init__(self, driver, chat_opener, verifier, queue,
                 log=None):
        self.driver = driver
        self.chat_opener = chat_opener
        self.verifier = verifier
        self.queue = queue
        self.log = log or (lambda _m: None)

    def send(self, target: str, message: str,
             timeout: float = 20.0) -> tuple[bool, str, OperationRecord]:
        """Send with one adaptive timeout budget (spec 7, 32): the caller
        passes the per-operation budget from the health model, and it gates
        BOTH the chat-open and the send-verification windows."""
        operation = OperationRecord(target, message)
        self.queue.enqueue(target, message, record=operation)
        self.log(f"[WA] OP {operation.operation_id} prepared | TARGET: {target}")
        operation.mark("attempted", "send started")

        opened, detail = self.chat_opener.open(target, timeout=timeout)
        if not opened:
            operation.mark("failed", detail)
            self.queue.update(operation.operation_id, "failed")
            return False, detail, operation

        try:
            if not self.driver.composer_ready():
                raise RuntimeError("composer not ready")
            self.driver.type_message(message)
        except Exception as e:
            operation.mark("failed", f"typing failed: {str(e)[:100]}")
            self.queue.update(operation.operation_id, "failed")
            return False, str(e), operation

        self.log(f"[WA] STATE: SENDING | LATENCY: n/a")
        if not self.driver.send_message_action():
            operation.mark("failed", "send action failed")
            self.queue.update(operation.operation_id, "failed")
            return False, "send action failed", operation

        t0 = time.time()
        ok = self.verifier.verify(operation, timeout=timeout)
        latency = time.time() - t0
        self.log(f"[WA] VERIFY: {'SUCCESS' if ok else 'TIMEOUT'} | {latency:.2f}s")
        if ok:
            self.queue.update(operation.operation_id, "confirmed")
            return True, "confirmed", operation

        # Duplicate protection (spec 19): verification timed out, so the
        # message MAY have been sent. Re-check evidence before ANY resend.
        if self.verifier.message_visible(operation.message):
            operation.mark("confirmed", "re-check found message in pane")
            self.queue.update(operation.operation_id, "confirmed")
            return True, "confirmed after re-check", operation
        operation.mark("possibly_sent", "send attempted, evidence uncertain")
        self.queue.update(operation.operation_id, "possibly_sent")
        return False, "send attempted but unverified - will not blindly resend", operation
