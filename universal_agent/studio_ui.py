"""Project Agent panel — the Keys.AI interface for long-running projects.

A page of the main window's centre view stack (the same place the live camera
and then the browser and image studio open), same gold palette and Courier
typography, no change to any other screen.

The widget never runs work itself. It calls the service, polls the task, and
renders states: requirements, planning, running, waiting for approval,
validating, completed, failed, cancelled. Every slow service call goes through
``_async`` so the Qt event loop (and the voice session) stays responsive.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ui import C

_STATUS_COLOR = {
    "READY": C.TEXT_MED, "PLANNING": C.ACC, "RUNNING": C.ACC,
    "WAITING_FOR_USER": C.PRI, "WAITING_FOR_APPROVAL": C.PRI,
    "VALIDATING": C.ACC, "REPAIRING": C.ACC, "COMPLETED": C.GREEN,
    "FAILED": C.RED, "CANCELLED": C.TEXT_DIM, "INTAKE": C.TEXT_DIM,
}

_BTN = """
    QPushButton {{
        background: transparent; color: {col};
        border: 1px solid {col}; border-radius: 3px; padding: 4px 10px;
    }}
    QPushButton:hover {{ background: rgba(255, 215, 0, 22); }}
    QPushButton:disabled {{ color: {dim}; border-color: {border}; }}
"""

_FIELD = """
    QLineEdit, QPlainTextEdit, QComboBox {{
        background: rgba(4, 9, 14, 235); color: {text};
        border: 1px solid {border}; border-radius: 3px; padding: 4px 6px;
        selection-background-color: {ghost};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border: 1px solid {pri};
    }}
    QComboBox QAbstractItemView {{
        background: #0B0E14; color: {text}; selection-background-color: {ghost};
    }}
"""


def _btn(text: str, color: str = C.PRI, height: int = 28) -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(height)
    b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(_BTN.format(col=color, dim=C.TEXT_DIM, border=C.BORDER))
    return b


def _label(text: str, size: int = 8, color: str = C.TEXT_DIM,
           bold: bool = False) -> QLabel:
    w = QLabel(text)
    w.setFont(QFont("Courier New", size,
                    QFont.Weight.Bold if bold else QFont.Weight.Normal))
    w.setStyleSheet(f"color: {color}; background: transparent;")
    return w


def _open_path(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    if os.name == "nt":
        os.startfile(str(p))                      # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


class ProjectAgentPanel(QWidget):
    #: The user closed the panel (✕ CLOSE) — the host puts the HUD back.
    closed = pyqtSignal()
    _bg_sig = pyqtSignal()

    def __init__(self, parent=None, service=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ProjectAgentPanel {{
                background: rgba(0, 5, 9, 250);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        from universal_agent import get_service
        self.svc = service or get_service()
        self._bg_queue: queue.Queue = queue.Queue()
        self._bg_sig.connect(self._drain_bg)
        self._task_id = ""
        self._question_sig = ""
        self._plan_sig = ""
        self._answer_widgets: dict[str, object] = {}
        self._last_status = ""
        self._closed = False
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._refresh_tasks()

    # ── layout ────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(_label("◈  PROJECT AGENT", 12, C.PRI, True))
        head.addSpacing(10)
        self._pill = _label("READY FOR A TASK", 8, C.TEXT_MED, True)
        head.addWidget(self._pill)
        head.addStretch()
        head.addWidget(_label("research · build · documents · data · images · web",
                              7, C.TEXT_DIM))
        close = _btn("✕  CLOSE", C.TEXT_DIM, 24)
        close.clicked.connect(self.closed.emit)
        head.addWidget(close)
        root.addLayout(head)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {C.BORDER};")
        root.addWidget(line)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setStyleSheet(f"QSplitter::handle {{ background: {C.BORDER}; width: 1px; }}")
        split.addWidget(self._build_left())
        split.addWidget(self._build_middle())
        split.addWidget(self._build_right())
        split.setSizes([330, 430, 420])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 5)
        split.setStretchFactor(2, 4)
        root.addWidget(split, stretch=1)

        foot = QHBoxLayout()
        self._footer = _label("", 7, C.TEXT_DIM)
        foot.addWidget(self._footer, stretch=1)
        self._workspace_btn = _btn("📂  WORKSPACE", C.TEXT_MED, 24)
        self._workspace_btn.clicked.connect(self._open_workspace)
        foot.addWidget(self._workspace_btn)
        root.addLayout(foot)

    def _build_left(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(300)
        w.setMaximumWidth(380)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 8, 2)
        lay.setSpacing(5)

        lay.addWidget(_label("TASK", 7, C.PRI, True))
        self.request = QPlainTextEdit()
        self.request.setPlaceholderText(
            "e.g. Research the current local LLM runtimes and write a cited "
            "report.\nOr: Build a portfolio for a photographer.\nOr: Analyse "
            "C:\\data\\sales.xlsx and chart the monthly totals.")
        self.request.setFixedHeight(110)
        self.request.setFont(QFont("Courier New", 9))
        self.request.setStyleSheet(_FIELD.format(text=C.TEXT, border=C.BORDER,
                                                 pri=C.PRI, ghost=C.PRI_GHO))
        lay.addWidget(self.request)

        self.start_btn = _btn("▸  START PROJECT", C.PRI, 34)
        self.start_btn.clicked.connect(self._start)
        lay.addWidget(self.start_btn)

        # Research presets: the recipes this task's research runs. Ticking one
        # is a request to research with it before the build — the plan gets a
        # research step and the build receives what it found.
        lay.addWidget(_label("RESEARCH PRESETS", 7, C.PRI, True))
        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(3)
        self._preset_buttons: list[tuple[str, QPushButton]] = []
        for index, preset in enumerate(self._available_presets()):
            box = _btn(str(preset.get("label") or preset.get("id")), C.TEXT_MED, 22)
            box.setCheckable(True)
            box.setToolTip(str(preset.get("description") or ""))
            box.setStyleSheet(box.styleSheet() + f"""
                QPushButton:checked {{ color: {C.PRI}; border: 1px solid {C.PRI};
                                       background: {C.PRI_GHO}; }}
            """)
            grid.addWidget(box, index // 2, index % 2)
            self._preset_buttons.append((str(preset.get("id")), box))
        lay.addLayout(grid)
        hint = _label("Presets add their own searches to the plan: repositories, "
                      "docs, design references, nationwide records.", 7, C.TEXT_DIM)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        self.resume_btn = _btn("↻  RESUME", C.ACC, 26)
        self.resume_btn.clicked.connect(self._resume)
        self.cancel_btn = _btn("■  CANCEL", C.RED, 26)
        self.cancel_btn.clicked.connect(self._cancel)
        row.addWidget(self.resume_btn)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

        lay.addWidget(_label("RECENT TASKS", 7, C.PRI, True))
        self.task_list = QListWidget()
        self.task_list.setFont(QFont("Courier New", 7))
        self.task_list.setStyleSheet(f"""
            QListWidget {{ background: rgba(0,0,0,90); color: {C.TEXT_MED};
                           border: 1px solid {C.BORDER}; }}
            QListWidget::item:selected {{ background: {C.PRI_GHO}; color: {C.PRI}; }}
        """)
        self.task_list.currentItemChanged.connect(self._on_task_pick)
        lay.addWidget(self.task_list, stretch=1)
        return w

    def _build_middle(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(5)
        lay.addWidget(_label("◈  PLAN & PROGRESS", 8, C.PRI, True))
        self.action_label = _label("No task selected.", 8, C.TEXT_MED)
        self.action_label.setWordWrap(True)
        lay.addWidget(self.action_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(7)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{ background: rgba(255,255,255,12); border: none;
                            border-radius: 3px; }}
            QProgressBar::chunk {{ background: {C.PRI}; border-radius: 3px; }}
        """)
        lay.addWidget(self.progress)

        self.plan_list = QListWidget()
        self.plan_list.setFont(QFont("Courier New", 8))
        self.plan_list.setStyleSheet(f"""
            QListWidget {{ background: rgba(0,0,0,90); color: {C.TEXT_MED};
                           border: 1px solid {C.BORDER}; }}
            QListWidget::item {{ padding: 3px; }}
        """)
        lay.addWidget(self.plan_list, stretch=2)

        lay.addWidget(_label("ACTIVITY", 7, C.PRI, True))
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Courier New", 7))
        self.log_box.setStyleSheet(f"""
            QPlainTextEdit {{ background: rgba(0,0,0,80); color: {C.TEXT_MED};
                              border: 1px solid {C.BORDER}; }}
        """)
        lay.addWidget(self.log_box, stretch=3)
        return w

    def _build_right(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Courier New", 8))
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {C.BORDER}; }}
            QTabBar::tab {{ background: transparent; color: {C.TEXT_DIM};
                            padding: 5px 10px; border: 1px solid {C.BORDER};
                            border-bottom: none; }}
            QTabBar::tab:selected {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """)
        self.tabs.addTab(self._build_questions(), "QUESTIONS")
        self.tabs.addTab(self._build_artifacts(), "ARTIFACTS")
        self.tabs.addTab(self._build_brief(), "BRIEF")
        return self.tabs

    def _build_questions(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(5)
        self.questions_hint = _label(
            "The agent asks only what it cannot proceed without.", 7, C.TEXT_DIM)
        self.questions_hint.setWordWrap(True)
        lay.addWidget(self.questions_hint)

        self.approval_box = QWidget()
        ab = QVBoxLayout(self.approval_box)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(4)
        self.approval_title = _label("", 8, C.PRI, True)
        self.approval_title.setWordWrap(True)
        self.approval_detail = _label("", 7, C.TEXT_MED)
        self.approval_detail.setWordWrap(True)
        ab.addWidget(self.approval_title)
        ab.addWidget(self.approval_detail)
        arow = QHBoxLayout()
        self.approve_btn = _btn("✓  APPROVE", C.GREEN, 26)
        self.approve_btn.clicked.connect(lambda: self._decide(True))
        self.reject_btn = _btn("✕  REJECT", C.RED, 26)
        self.reject_btn.clicked.connect(lambda: self._decide(False))
        arow.addWidget(self.approve_btn)
        arow.addWidget(self.reject_btn)
        arow.addStretch()
        ab.addLayout(arow)
        self.approval_box.hide()
        lay.addWidget(self.approval_box)

        self.q_scroll = QScrollArea()
        self.q_scroll.setWidgetResizable(True)
        self.q_scroll.setStyleSheet(f"QScrollArea {{ border: none; background: transparent; }}")
        self.q_host = QWidget()
        self.q_layout = QVBoxLayout(self.q_host)
        self.q_layout.setContentsMargins(0, 0, 0, 0)
        self.q_layout.setSpacing(6)
        self.q_layout.addStretch()
        self.q_scroll.setWidget(self.q_host)
        lay.addWidget(self.q_scroll, stretch=1)

        self.submit_answers = _btn("▸  SUBMIT ANSWERS", C.PRI, 30)
        self.submit_answers.clicked.connect(self._answer)
        self.submit_answers.setEnabled(False)
        lay.addWidget(self.submit_answers)
        return w

    def _build_artifacts(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(5)
        self.artifact_list = QListWidget()
        self.artifact_list.setFont(QFont("Courier New", 8))
        self.artifact_list.setStyleSheet(f"""
            QListWidget {{ background: rgba(0,0,0,90); color: {C.TEXT_MED};
                           border: 1px solid {C.BORDER}; }}
            QListWidget::item:selected {{ background: {C.PRI_GHO}; color: {C.PRI}; }}
        """)
        lay.addWidget(self.artifact_list, stretch=1)
        self.artifact_detail = _label("", 7, C.TEXT_DIM)
        self.artifact_detail.setWordWrap(True)
        lay.addWidget(self.artifact_detail)
        row = QHBoxLayout()
        self.open_btn = _btn("OPEN", C.PRI, 26)
        self.open_btn.clicked.connect(self._open_artifact)
        self.reveal_btn = _btn("REVEAL", C.TEXT_MED, 26)
        self.reveal_btn.clicked.connect(self._reveal_artifact)
        self.copy_btn = _btn("COPY PATH", C.TEXT_MED, 26)
        self.copy_btn.clicked.connect(self._copy_path)
        row.addWidget(self.open_btn)
        row.addWidget(self.reveal_btn)
        row.addWidget(self.copy_btn)
        lay.addLayout(row)
        return w

    def _build_brief(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        self.brief_box = QPlainTextEdit()
        self.brief_box.setReadOnly(True)
        self.brief_box.setFont(QFont("Courier New", 7))
        self.brief_box.setStyleSheet(f"""
            QPlainTextEdit {{ background: rgba(0,0,0,80); color: {C.TEXT_MED};
                              border: 1px solid {C.BORDER}; }}
        """)
        lay.addWidget(self.brief_box)
        return w

    # ── async plumbing ────────────────────────────────────────────────────
    def _async(self, fn, cb) -> None:
        def work():
            try:
                result = (True, fn())
            except Exception as exc:
                result = (False, exc)
            if self._closed:
                return
            try:
                self._bg_queue.put((cb, result))
                self._bg_sig.emit()
            except RuntimeError:
                # Widget already destroyed (app exiting) — drop the result.
                pass
        threading.Thread(target=work, daemon=True).start()

    def _drain_bg(self) -> None:
        while True:
            try:
                cb, (ok, value) = self._bg_queue.get_nowait()
            except queue.Empty:
                break
            try:
                cb(ok, value)
            except Exception:
                traceback.print_exc()

    def _set_status(self, text: str, color: str = C.TEXT_MED) -> None:
        self.action_label.setText(text)
        self.action_label.setStyleSheet(f"color: {color}; background: transparent;")

    # ── actions ───────────────────────────────────────────────────────────
    @staticmethod
    def _available_presets() -> list[dict]:
        """The research recipes from config/research_presets.json."""
        try:
            from universal_agent.workers import presets
            return presets.load()
        except Exception:
            return []

    def _selected_presets(self) -> list[str]:
        return [pid for pid, box in getattr(self, "_preset_buttons", [])
                if box.isChecked()]

    def _start(self) -> None:
        request = self.request.toPlainText().strip()
        if not request:
            self._set_status("Describe the project first.", C.RED)
            return
        self.start_btn.setEnabled(False)
        self._set_status("Creating the task…", C.TEXT_MED)
        chosen = self._selected_presets()
        # Answers are stored as text, so the selection travels as a list of ids
        # joined by commas and the planner reads it back with presets.parse.
        answers = {"presets": ", ".join(chosen)} if chosen else None
        self._async(lambda: self.svc.create(request, answers=answers),
                    self._on_created)

    def _on_created(self, ok: bool, task) -> None:
        self.start_btn.setEnabled(True)
        if not ok:
            self._set_status(f"Could not start: {task}", C.RED)
            return
        self._task_id = task["id"]
        self._refresh_tasks()
        self._render(task)

    def _resume(self) -> None:
        if not self._task_id:
            return
        self._async(lambda: self.svc.resume(self._task_id),
                    self._on_simple("Resuming…"))

    def _cancel(self) -> None:
        if not self._task_id:
            return
        answer = QMessageBox.question(
            self, "Cancel task",
            "Stop this task? Finished artifacts are kept; no new side effects "
            "will be started.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._async(lambda: self.svc.cancel(self._task_id),
                    self._on_simple("Cancelling…"))

    def _answer(self) -> None:
        values = {}
        for slot, widget in self._answer_widgets.items():
            values[slot] = (widget.currentText() if isinstance(widget, QComboBox)
                            else widget.text()).strip()
        if not any(values.values()):
            self._set_status("Answer at least one question.", C.RED)
            return
        self.submit_answers.setEnabled(False)
        self._async(lambda: self.svc.answer(self._task_id, values),
                    self._on_answered)

    def _on_answered(self, ok: bool, task) -> None:
        if not ok:
            self._set_status(f"Answer not accepted: {task}", C.RED)
            self.submit_answers.setEnabled(True)
            return
        self._render(task)

    def _decide(self, approved: bool) -> None:
        if not self._task_id:
            return
        self.approve_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self._async(lambda: self.svc.approve(self._task_id, approved),
                    self._on_simple("Approval recorded."))

    def _on_simple(self, message: str):
        def cb(ok: bool, value):
            self._set_status(message if ok else f"Failed: {value}",
                             C.TEXT_MED if ok else C.RED)
            if ok:
                self._render(value)
        return cb

    def _poll(self) -> None:
        if not self._task_id:
            return
        task_id = self._task_id
        self._async(lambda: self.svc.get_task(task_id), self._on_poll)

    def _on_poll(self, ok: bool, task) -> None:
        if not ok or not task or task.get("id") != self._task_id:
            return
        self._render(task)

    def _refresh_tasks(self) -> None:
        self._async(lambda: self.svc.list_tasks(20), self._on_tasks)

    def _on_tasks(self, ok: bool, tasks) -> None:
        if not ok:
            return
        self.task_list.blockSignals(True)
        self.task_list.clear()
        for task in tasks or []:
            item = QListWidgetItem(
                f"{str(task.get('updated_at'))[5:16]}  "
                f"[{task.get('status')[:9]}]  "
                f"{' '.join(str(task.get('request') or '').split())[:34]}")
            item.setData(Qt.ItemDataRole.UserRole, task.get("id"))
            if task.get("id") == self._task_id:
                item.setForeground(QColor(C.PRI))
            self.task_list.addItem(item)
        self.task_list.blockSignals(False)

    def _on_task_pick(self, current, _previous) -> None:
        if current is None:
            return
        task_id = current.data(Qt.ItemDataRole.UserRole)
        if not task_id:
            return
        self._task_id = task_id
        self._async(lambda: self.svc.get_task(task_id), self._on_poll)

    # ── rendering ─────────────────────────────────────────────────────────
    def _render(self, task: dict) -> None:
        status = str(task.get("status") or "")
        self._pill.setText(f"● {status.replace('_', ' ')}")
        self._pill.setStyleSheet(
            f"color: {_STATUS_COLOR.get(status, C.TEXT_MED)}; background: transparent;")
        self._footer.setText(
            f"{task.get('intent', '')}  ·  workspace: {task.get('workspace', '')}")
        self._workspace_btn.setEnabled(bool(task.get("workspace")))

        plan = task.get("plan") or {}
        steps = plan.get("steps") or []
        done = sum(1 for s in steps if s.get("status") == "done")
        self.progress.setValue(int(done * 100 / len(steps)) if steps else 0)

        if status == "WAITING_FOR_USER":
            self._set_status(
                "The agent needs your answers before it can plan safely.",
                C.PRI)
        elif status == "WAITING_FOR_APPROVAL":
            self._set_status("Waiting for your approval decision.", C.PRI)
        elif status == "RUNNING":
            current = task.get("current_step") or 0
            title = steps[current]["title"] if 0 <= current < len(steps) else ""
            self._set_status(f"Running: {title}", C.ACC)
        elif status == "COMPLETED":
            summary = (task.get("result") or {}).get("summary") or "Completed."
            self._set_status(f"✓ {summary}", C.GREEN)
        elif status == "FAILED":
            self._set_status(f"✕ {task.get('error') or 'Task failed.'}", C.RED)
        elif status == "CANCELLED":
            self._set_status("Cancelled — no further work will run.", C.TEXT_DIM)
        elif status == "PLANNING":
            self._set_status("Planning the work…", C.ACC)
        elif status in ("VALIDATING", "REPAIRING"):
            self._set_status(f"{status.capitalize()} artifacts…", C.ACC)
        else:
            self._set_status("Ready.", C.TEXT_MED)

        self.start_btn.setEnabled(status not in ("RUNNING", "PLANNING",
                                                 "VALIDATING", "REPAIRING",
                                                 "WAITING_FOR_APPROVAL"))
        self.cancel_btn.setEnabled(status not in ("COMPLETED", "CANCELLED"))
        self.resume_btn.setEnabled(status in ("FAILED", "RUNNING", "PLANNING",
                                              "VALIDATING", "REPAIRING",
                                              "WAITING_FOR_APPROVAL")
                                   and not task.get("active"))

        plan_sig = "|".join(f"{s.get('id')}:{s.get('status')}:{s.get('detail', '')[:40]}"
                            for s in steps)
        if plan_sig != self._plan_sig:
            self._plan_sig = plan_sig
            self.plan_list.clear()
            for step in steps:
                mark = {"done": "✓", "running": "→", "failed": "✕"}.get(
                    step.get("status"), "○")
                item = QListWidgetItem(
                    f"{mark}  {step.get('title')}   [{step.get('worker')}]")
                item.setForeground(QColor(
                    C.GREEN if step.get("status") == "done" else
                    C.ACC if step.get("status") == "running" else C.TEXT_MED))
                self.plan_list.addItem(item)

        logs = task.get("logs") or []
        if logs:
            text = "\n".join(f"{e.get('ts', '')}  {e.get('text', '')}" for e in logs[-160:])
            if text != self.log_box.toPlainText():
                self.log_box.setPlainText(text)
                bar = self.log_box.verticalScrollBar()
                bar.setValue(bar.maximum())

        approval = task.get("approval") or {}
        pending = (status == "WAITING_FOR_APPROVAL"
                   and approval.get("status") == "pending")
        if pending:
            self.approval_title.setText(f"⚠  APPROVAL REQUIRED — {approval.get('title', '')}")
            self.approval_detail.setText(approval.get("detail", ""))
            self.approve_btn.setEnabled(True)
            self.reject_btn.setEnabled(True)
            self.approval_box.show()
        else:
            self.approval_box.hide()

        questions = [q for q in task.get("questions") or []
                     if q.get("slot") not in (task.get("answers") or {})]
        q_sig = task["id"] + ":" + "|".join(q.get("slot", "") for q in questions)
        if q_sig != self._question_sig:
            self._question_sig = q_sig
            self._build_question_form(questions)
        self.submit_answers.setEnabled(bool(questions) and status == "WAITING_FOR_USER")
        if questions and self.tabs.currentIndex() != 0:
            self.tabs.setCurrentIndex(0)

        self._render_artifacts(task)
        if status != self._last_status:
            self._last_status = status
            self._refresh_tasks()
        brief = task.get("brief") or {}
        text = [
            f"GOAL: {brief.get('goal', task.get('request', ''))}",
            f"INTENT: {task.get('intent', '')}",
            "",
            "DELIVERABLES:",
        ]
        text += [f"- {d}" for d in brief.get("deliverables") or []]
        text += ["", "ACCEPTANCE CRITERIA:"] + \
                [f"- {c}" for c in brief.get("acceptance_criteria") or []]
        if task.get("assumptions"):
            text += ["", "ASSUMPTIONS:"] + [f"- {a}" for a in task["assumptions"]]
        # Research provenance: which pages were actually inspected, and which
        # findings are only search snippets. Shown as-is, never as a claim.
        evidence = task.get("evidence") or []
        if evidence:
            seen: list[str] = []
            rows = []
            for item in evidence:
                url = str(item.get("source_url") or "")
                if not url or url in seen:
                    continue
                seen.append(url)
                mark = "✓" if item.get("verified") else "~"
                rows.append(f"- [{mark}] {item.get('title') or url} — {url}")
            text += ["", f"SOURCES ({len(seen)}  ✓ inspected  ~ snippet only):"]
            text += rows[:40]
        if task.get("warnings"):
            text += ["", "WARNINGS:"] + [f"- {w}" for w in task["warnings"]]
        if task.get("error"):
            text += ["", "ERROR:", task["error"]]
        if plan.get("note"):
            text += ["", f"PLANNER: {plan['note']}"]
        self.brief_box.setPlainText("\n".join(text))

    def _build_question_form(self, questions: list[dict]) -> None:
        while self.q_layout.count():
            item = self.q_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._answer_widgets: dict[str, object] = {}
        for q in questions:
            prefix = "REQUIRED" if q.get("required") else "optional"
            self.q_layout.addWidget(_label(
                f"{q.get('question')}  ({prefix})", 8, C.PRI if q.get("required")
                else C.TEXT_MED, True))
            if q.get("why"):
                self.q_layout.addWidget(_label(q["why"], 7, C.TEXT_DIM))
            if q.get("options"):
                widget = QComboBox()
                widget.setEditable(True)
                widget.addItems(q["options"])
                if q.get("default"):
                    widget.setCurrentText(str(q["default"]))
                widget.setFont(QFont("Courier New", 8))
            else:
                widget = QLineEdit()
                widget.setPlaceholderText(q.get("hint") or "")
                if q.get("default"):
                    widget.setText(str(q["default"]))
                widget.setFont(QFont("Courier New", 8))
            widget.setStyleSheet(_FIELD.format(text=C.TEXT, border=C.BORDER,
                                               pri=C.PRI, ghost=C.PRI_GHO))
            self.q_layout.addWidget(widget)
            self._answer_widgets[q["slot"]] = widget
        self.q_layout.addStretch()

    def _render_artifacts(self, task: dict) -> None:
        artifacts = task.get("artifacts") or []
        paths = [a.get("path") for a in artifacts]
        current = [self.artifact_list.item(i).data(Qt.ItemDataRole.UserRole)
                   for i in range(self.artifact_list.count())]
        if paths == current:
            return
        self.artifact_list.clear()
        for item in artifacts:
            mark = "✓" if item.get("validated") else "!"
            text = f"{mark} {item.get('name')}  ({item.get('kind', '')})"
            row = QListWidgetItem(text)
            row.setData(Qt.ItemDataRole.UserRole, item.get("path"))
            row.setData(Qt.ItemDataRole.UserRole + 1, item)
            if not item.get("validated"):
                row.setForeground(QColor(C.ACC))
            self.artifact_list.addItem(row)
        if artifacts:
            detail = artifacts[-1].get("validation_detail") or ""
            self.artifact_detail.setText(detail)

    # ── artifact actions ──────────────────────────────────────────────────
    def _selected_artifact(self) -> dict | None:
        item = self.artifact_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole + 1)

    def _open_artifact(self) -> None:
        path = self.artifact_list.currentItem()
        if path is None:
            return
        _open_path(path.data(Qt.ItemDataRole.UserRole) or "")

    def _reveal_artifact(self) -> None:
        item = self.artifact_list.currentItem()
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path.exists():
            self._set_status("That artifact is no longer on disk.", C.RED)
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                _open_path(str(path.parent))
        except Exception as exc:
            self._set_status(f"Could not reveal the file: {exc}", C.RED)

    def _copy_path(self) -> None:
        item = self.artifact_list.currentItem()
        if item is None:
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(str(item.data(Qt.ItemDataRole.UserRole)))
        self._set_status("Artifact path copied.", C.TEXT_MED)

    def _open_workspace(self) -> None:
        task = self.svc.get_task(self._task_id) if self._task_id else None
        if task and task.get("workspace"):
            _open_path(task["workspace"])

    # ── lifecycle ─────────────────────────────────────────────────────────
    def shutdown(self) -> None:
        self._closed = True
        self._timer.stop()


__all__ = ["ProjectAgentPanel"]
