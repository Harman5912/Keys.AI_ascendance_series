"""AI Image Studio — the Keys.AI image-generation interface.

An overlay hosted over the existing HUD (same approach as the Agent Control
settings and Google account panels), so the visual language, fonts and gold
palette stay consistent and no other screen is redesigned.

All slow work (backend probes, model listing, generation, downloads, ComfyUI
installation, prompt enhancement) runs off the Qt thread through `_async`, and
results come back on the UI thread via a queued queue + signal. The generate
job itself lives in the service; this widget only polls its status, so a
failure always ends as a visible message instead of a stuck spinner.
"""

from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from core.image_studio import registry, service as service_mod, settings
from core.image_studio import validation
from ui import C

_BTN = """
    QPushButton {{
        background: transparent; color: {col};
        border: 1px solid {col}; border-radius: 3px;
        padding: 4px 10px;
    }}
    QPushButton:hover {{ background: rgba(255, 215, 0, 22); }}
    QPushButton:disabled {{ color: {dim}; border-color: {border};
                            background: transparent; }}
"""

_FIELD = """
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox,
    QDoubleSpinBox {{
        background: rgba(4, 9, 14, 230); color: {text};
        border: 1px solid {border}; border-radius: 3px; padding: 4px 6px;
        selection-background-color: {ghost};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {pri};
    }}
    QComboBox QAbstractItemView {{
        background: #0B0E14; color: {text};
        selection-background-color: {ghost};
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


class _TextDialog(QDialog):
    def __init__(self, parent, title: str, body: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 420)
        self.setStyleSheet(f"background: {C.BG}; color: {C.TEXT};")
        lay = QVBoxLayout(self)
        box = QPlainTextEdit(body)
        box.setReadOnly(True)
        box.setFont(QFont("Courier New", 8))
        lay.addWidget(box)
        close = _btn("CLOSE", C.PRI, 30)
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)


class _EnhanceDialog(QDialog):
    """Shows the enhanced prompt before generation (preview mode)."""

    def __init__(self, parent, original: str, enhanced: str, model: str):
        super().__init__(parent)
        self.setWindowTitle("Enhanced prompt")
        self.setMinimumSize(680, 360)
        self.setStyleSheet(f"background: {C.BG}; color: {C.TEXT};")
        self.choice = "cancel"
        lay = QVBoxLayout(self)
        lay.addWidget(_label(f"◈  ENHANCED PROMPT  ({model})", 9, C.PRI, True))
        self.box = QPlainTextEdit(enhanced)
        self.box.setFont(QFont("Courier New", 9))
        self.box.setStyleSheet(_FIELD.format(text=C.TEXT, border=C.BORDER,
                                             pri=C.PRI, ghost=C.PRI_GHO))
        lay.addWidget(self.box, stretch=1)
        lay.addWidget(_label("Original prompt is kept with the generation "
                             "record.", 7, C.TEXT_DIM))
        row = QHBoxLayout()
        use = _btn("▸  GENERATE WITH THIS", C.PRI, 30)
        orig = _btn("USE ORIGINAL", C.TEXT_MED, 30)
        cancel = _btn("CANCEL", C.TEXT_DIM, 30)
        use.clicked.connect(lambda: self._done("enhanced"))
        orig.clicked.connect(lambda: self._done("original"))
        cancel.clicked.connect(lambda: self._done("cancel"))
        row.addWidget(orig)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(use)
        lay.addLayout(row)

    def _done(self, choice: str):
        self.choice = choice
        self.accept()

    def text(self) -> str:
        return self.box.toPlainText().strip()


class ImageStudioPanel(QWidget):
    #: The user closed the studio (✕ CLOSE) — the host puts the HUD back.
    closed = pyqtSignal()
    _bg_sig = pyqtSignal()
    _log_sig = pyqtSignal(str)
    _dl_sig = pyqtSignal(int, str)

    def __init__(self, parent=None, service=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ImageStudioPanel {{
                background: rgba(0, 5, 9, 250);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        from core.image_studio import get_service
        self.svc = service or get_service()
        self._bg_queue: queue.Queue = queue.Queue()
        self._bg_sig.connect(self._drain_bg)
        self._log_sig.connect(self._append_log)
        self._dl_sig.connect(self._on_download_progress)

        self._status_cache: dict = {}
        self._models_cache: list[dict] = []
        self._active_job = ""
        self._pixmap: QPixmap | None = None
        self._preview_path = ""
        self._zoom = 1.0
        self._abort_download = threading.Event()
        self._abort_install = threading.Event()
        self._installing = False
        self._downloading = False

        self._build()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(600)
        self._poll_timer.timeout.connect(self._poll_job)
        self.refresh_all()

    # ── layout ────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(_label("◈  AI IMAGE STUDIO", 12, C.PRI, True))
        head.addSpacing(10)
        self._state_pill = _label("CHECKING BACKEND…", 8, C.TEXT_MED, True)
        head.addWidget(self._state_pill)
        head.addStretch()
        head.addWidget(_label("local · ComfyUI · offline after setup", 7,
                              C.TEXT_DIM))
        close = _btn("✕  CLOSE", C.TEXT_DIM, 24)
        close.clicked.connect(self.closed.emit)
        head.addWidget(close)
        root.addLayout(head)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {C.BORDER};")
        root.addWidget(line)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setStyleSheet(f"""
            QSplitter::handle {{ background: {C.BORDER}; width: 1px; }}
        """)
        split.addWidget(self._build_controls())
        split.addWidget(self._build_preview())
        split.addWidget(self._build_tabs())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 5)
        split.setStretchFactor(2, 4)
        split.setSizes([330, 420, 400])
        root.addWidget(split, stretch=1)

        foot = QHBoxLayout()
        self._footer = _label("", 7, C.TEXT_DIM)
        foot.addWidget(self._footer, stretch=1)
        self._open_out = _btn("📂  OUTPUT FOLDER", C.TEXT_MED, 24)
        self._open_out.clicked.connect(self._open_output_dir)
        foot.addWidget(self._open_out)
        root.addLayout(foot)

    def _build_controls(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(310)
        w.setMaximumWidth(400)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 8, 2)
        lay.setSpacing(5)
        field_style = _FIELD.format(text=C.TEXT, border=C.BORDER, pri=C.PRI,
                                    ghost=C.PRI_GHO)

        lay.addWidget(_label("PROMPT", 7, C.PRI, True))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Silver knight with a red cape on a dark fantasy battlefield…")
        self.prompt.setFixedHeight(86)
        self.prompt.setFont(QFont("Courier New", 9))
        self.prompt.setStyleSheet(field_style)
        lay.addWidget(self.prompt)

        enh = QHBoxLayout()
        self.enhance_cb = QCheckBox("Enhance with local Ollama")
        self.enhance_cb.setFont(QFont("Courier New", 7))
        self.enhance_cb.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        enh.addWidget(self.enhance_cb)
        enh.addStretch()
        self.enhance_btn = _btn("✨ ENHANCE", C.ACC, 22)
        self.enhance_btn.clicked.connect(self._enhance_only)
        enh.addWidget(self.enhance_btn)
        lay.addLayout(enh)
        self.enhance_note = _label("", 7, C.TEXT_DIM)
        self.enhance_note.setWordWrap(True)
        lay.addWidget(self.enhance_note)

        lay.addWidget(_label("NEGATIVE PROMPT (optional)", 7, C.PRI, True))
        self.negative = QPlainTextEdit()
        self.negative.setFixedHeight(44)
        self.negative.setFont(QFont("Courier New", 8))
        self.negative.setStyleSheet(field_style)
        lay.addWidget(self.negative)

        lay.addWidget(_label("MODEL", 7, C.PRI, True))
        self.model_combo = QComboBox()
        self.model_combo.setFont(QFont("Courier New", 8))
        self.model_combo.setStyleSheet(field_style)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        lay.addWidget(self.model_combo)
        self.model_state = _label("", 7, C.TEXT_DIM)
        self.model_state.setWordWrap(True)
        lay.addWidget(self.model_state)

        res = QHBoxLayout()
        res.addWidget(_label("SIZE", 7, C.TEXT_DIM))
        self.width_spin = QSpinBox()
        self.height_spin = QSpinBox()
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(256, 2048)
            spin.setSingleStep(64)
            spin.setValue(512)
            spin.setFont(QFont("Courier New", 8))
            spin.setStyleSheet(field_style)
        res.addWidget(self.width_spin)
        res.addWidget(_label("×", 8, C.TEXT_DIM))
        res.addWidget(self.height_spin)
        res.addStretch()
        lay.addLayout(res)

        qual = QHBoxLayout()
        qual.addWidget(_label("STEPS", 7, C.TEXT_DIM))
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 100)
        self.steps_spin.setValue(25)
        qual.addWidget(self.steps_spin)
        qual.addWidget(_label("CFG", 7, C.TEXT_DIM))
        self.cfg_spin = QDoubleSpinBox()
        self.cfg_spin.setRange(0.0, 30.0)
        self.cfg_spin.setSingleStep(0.5)
        self.cfg_spin.setValue(7.5)
        qual.addWidget(self.cfg_spin)
        for widget in (self.steps_spin, self.cfg_spin):
            widget.setFont(QFont("Courier New", 8))
            widget.setStyleSheet(field_style)
        qual.addStretch()
        lay.addLayout(qual)

        seed_row = QHBoxLayout()
        seed_row.addWidget(_label("SEED", 7, C.TEXT_DIM))
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(-1, 2**31 - 1)
        self.seed_spin.setValue(-1)
        self.seed_spin.setSpecialValueText("RANDOM")
        self.seed_spin.setFont(QFont("Courier New", 8))
        self.seed_spin.setStyleSheet(field_style)
        seed_row.addWidget(self.seed_spin, stretch=1)
        rand = _btn("🎲", C.TEXT_MED, 24)
        rand.clicked.connect(lambda: self.seed_spin.setValue(-1))
        seed_row.addWidget(rand)
        seed_row.addWidget(_label("BATCH", 7, C.TEXT_DIM))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 4)
        self.batch_spin.setValue(1)
        self.batch_spin.setFont(QFont("Courier New", 8))
        self.batch_spin.setStyleSheet(field_style)
        seed_row.addWidget(self.batch_spin)
        lay.addLayout(seed_row)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(_label("FORMAT", 7, C.TEXT_DIM))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "JPG", "WEBP"])
        self.format_combo.setFont(QFont("Courier New", 8))
        self.format_combo.setStyleSheet(field_style)
        fmt_row.addWidget(self.format_combo)
        fmt_row.addStretch()
        self.i2i_btn = _btn("＋ IMAGE→IMAGE", C.TEXT_DIM, 22)
        self.i2i_btn.clicked.connect(self._pick_input_image)
        fmt_row.addWidget(self.i2i_btn)
        lay.addLayout(fmt_row)
        self.i2i_label = _label("", 7, C.TEXT_DIM)
        self.i2i_label.setWordWrap(True)
        lay.addWidget(self.i2i_label)
        self._input_image = ""

        lay.addStretch()
        self.generate_btn = _btn("▸  GENERATE IMAGE", C.PRI, 36)
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        lay.addWidget(self.generate_btn)
        self.cancel_btn = _btn("■  CANCEL GENERATION", C.RED, 28)
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        lay.addWidget(self.cancel_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{ background: rgba(255,255,255,12); border: none;
                            border-radius: 4px; }}
            QProgressBar::chunk {{ background: {C.PRI}; border-radius: 4px; }}
        """)
        lay.addWidget(self.progress)
        self.status_label = _label("Idle", 7, C.TEXT_MED)
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)
        return w

    def _build_preview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(5)

        head = QHBoxLayout()
        head.addWidget(_label("◈  PREVIEW", 8, C.PRI, True))
        head.addStretch()
        for text, delta in (("−", -0.25), ("+", 0.25)):
            b = _btn(text, C.TEXT_MED, 22)
            b.setFixedWidth(28)
            b.clicked.connect(lambda _=False, d=delta: self._zoom_by(d))
            head.addWidget(b)
        fit = _btn("FIT", C.TEXT_MED, 22)
        fit.clicked.connect(self._fit)
        head.addWidget(fit)
        full = _btn("OPEN FULL SIZE", C.TEXT_MED, 22)
        full.clicked.connect(self._open_full)
        head.addWidget(full)
        lay.addLayout(head)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setStyleSheet(f"""
            QScrollArea {{ background: rgba(0,0,0,120);
                           border: 1px solid {C.BORDER}; border-radius: 4px; }}
        """)
        self.preview_label = QLabel("No image yet.\n\nDescribe an image and press "
                                    "GENERATE IMAGE.\nIf ComfyUI is not installed, "
                                    "open the BACKEND tab.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setFont(QFont("Courier New", 9))
        self.preview_label.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self.preview_label.setMinimumSize(320, 320)
        self.preview_scroll.setWidget(self.preview_label)
        lay.addWidget(self.preview_scroll, stretch=1)

        self.meta_label = _label("", 7, C.TEXT_DIM)
        self.meta_label.setWordWrap(True)
        lay.addWidget(self.meta_label)

        row = QHBoxLayout()
        self.save_btn = _btn("💾  SAVE COPY", C.PRI, 26)
        self.save_btn.clicked.connect(self._save_copy)
        self.save_btn.setEnabled(False)
        row.addWidget(self.save_btn)
        self.copy_btn = _btn("COPY PROMPT", C.TEXT_MED, 26)
        self.copy_btn.clicked.connect(self._copy_prompt)
        self.copy_btn.setEnabled(False)
        row.addWidget(self.copy_btn)
        self.reveal_btn = _btn("REVEAL FILE", C.TEXT_MED, 26)
        self.reveal_btn.clicked.connect(self._reveal)
        self.reveal_btn.setEnabled(False)
        row.addWidget(self.reveal_btn)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _build_tabs(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Courier New", 8))
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {C.BORDER};
                                background: transparent; }}
            QTabBar::tab {{ background: transparent; color: {C.TEXT_DIM};
                            padding: 5px 10px; border: 1px solid {C.BORDER};
                            border-bottom: none; }}
            QTabBar::tab:selected {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """)
        self.tabs.addTab(self._build_history_tab(), "HISTORY")
        self.tabs.addTab(self._build_models_tab(), "MODELS")
        self.tabs.addTab(self._build_backend_tab(), "BACKEND")
        return self.tabs

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(5)
        lay.addWidget(_label("Saved generations (persisted across restarts)", 7,
                             C.TEXT_DIM))
        self.history_list = QListWidget()
        self.history_list.setFont(QFont("Courier New", 8))
        self.history_list.setStyleSheet(f"""
            QListWidget {{ background: rgba(0,0,0,90); color: {C.TEXT_MED};
                           border: 1px solid {C.BORDER}; }}
            QListWidget::item:selected {{ background: {C.PRI_GHO};
                                          color: {C.PRI}; }}
        """)
        self.history_list.currentItemChanged.connect(self._on_history_select)
        lay.addWidget(self.history_list, stretch=1)
        row = QHBoxLayout()
        self.hist_open = _btn("OPEN", C.PRI, 24)
        self.hist_open.clicked.connect(self._history_open)
        self.hist_copy = _btn("COPY PROMPT", C.TEXT_MED, 24)
        self.hist_copy.clicked.connect(self._history_copy)
        row.addWidget(self.hist_open)
        row.addWidget(self.hist_copy)
        row.addStretch()
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.hist_remove = _btn("REMOVE RECORD", C.TEXT_MED, 24)
        self.hist_remove.clicked.connect(lambda: self._history_remove(False))
        self.hist_delete = _btn("DELETE IMAGE", C.RED, 24)
        self.hist_delete.clicked.connect(lambda: self._history_remove(True))
        row2.addWidget(self.hist_remove)
        row2.addWidget(self.hist_delete)
        row2.addStretch()
        lay.addLayout(row2)
        for b in (self.hist_open, self.hist_copy, self.hist_remove,
                  self.hist_delete):
            b.setEnabled(False)
        return w

    def _build_models_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(5)
        lay.addWidget(_label("Image-generation models", 7, C.TEXT_DIM))
        self.models_list = QListWidget()
        self.models_list.setFont(QFont("Courier New", 8))
        self.models_list.setStyleSheet(f"""
            QListWidget {{ background: rgba(0,0,0,90); color: {C.TEXT_MED};
                           border: 1px solid {C.BORDER}; }}
            QListWidget::item:selected {{ background: {C.PRI_GHO};
                                          color: {C.PRI}; }}
        """)
        self.models_list.currentItemChanged.connect(self._on_model_select)
        lay.addWidget(self.models_list, stretch=2)

        self.model_details = QPlainTextEdit()
        self.model_details.setReadOnly(True)
        self.model_details.setFixedHeight(150)
        self.model_details.setFont(QFont("Courier New", 7))
        self.model_details.setStyleSheet(f"""
            QPlainTextEdit {{ background: rgba(0,0,0,80); color: {C.TEXT_MED};
                              border: 1px solid {C.BORDER}; }}
        """)
        lay.addWidget(self.model_details)

        row = QHBoxLayout()
        self.dl_btn = _btn("⬇  DOWNLOAD", C.PRI, 26)
        self.dl_btn.clicked.connect(self._download_model)
        self.dl_cancel = _btn("STOP", C.TEXT_DIM, 26)
        self.dl_cancel.clicked.connect(self._cancel_download)
        self.dl_cancel.setEnabled(False)
        self.activate_btn = _btn("USE THIS MODEL", C.ACC, 26)
        self.activate_btn.clicked.connect(self._use_model)
        row.addWidget(self.dl_btn)
        row.addWidget(self.dl_cancel)
        row.addWidget(self.activate_btn)
        row.addStretch()
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.del_btn = _btn("DELETE FILES", C.RED, 24)
        self.del_btn.clicked.connect(self._delete_model)
        refresh = _btn("REFRESH", C.TEXT_MED, 24)
        refresh.clicked.connect(lambda: self.refresh_all())
        row2.addWidget(self.del_btn)
        row2.addStretch()
        row2.addWidget(refresh)
        lay.addLayout(row2)
        return w

    def _build_backend_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(5)
        lay.addWidget(_label("ComfyUI server URL", 7, C.TEXT_DIM))
        self.url_edit = QLineEdit(settings.DEFAULT_COMFY_URL)
        self.url_edit.setFont(QFont("Courier New", 8))
        self.url_edit.setStyleSheet(_FIELD.format(text=C.TEXT, border=C.BORDER,
                                                  pri=C.PRI, ghost=C.PRI_GHO))
        lay.addWidget(self.url_edit)

        lay.addWidget(_label("ComfyUI folder (contains main.py)", 7, C.TEXT_DIM))
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setFont(QFont("Courier New", 8))
        self.path_edit.setStyleSheet(_FIELD.format(text=C.TEXT, border=C.BORDER,
                                                   pri=C.PRI, ghost=C.PRI_GHO))
        path_row.addWidget(self.path_edit, stretch=1)
        browse = _btn("…", C.TEXT_MED, 24)
        browse.clicked.connect(self._browse_comfy)
        path_row.addWidget(browse)
        lay.addLayout(path_row)

        row = QHBoxLayout()
        save = _btn("SAVE", C.PRI, 24)
        save.clicked.connect(self._save_backend_settings)
        check = _btn("CHECK HEALTH", C.ACC, 24)
        check.clicked.connect(lambda: self.refresh_all(force=True))
        row.addWidget(save)
        row.addWidget(check)
        row.addStretch()
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.start_btn = _btn("▶  START BACKEND", C.GREEN, 26)
        self.start_btn.clicked.connect(self._start_backend)
        self.stop_btn = _btn("■  STOP BACKEND", C.RED, 26)
        self.stop_btn.clicked.connect(self._stop_backend)
        self.stop_btn.setEnabled(False)
        row2.addWidget(self.start_btn)
        row2.addWidget(self.stop_btn)
        lay.addLayout(row2)

        row3 = QHBoxLayout()
        self.install_btn = _btn("⬇  INSTALL COMFYUI", C.PRI, 26)
        self.install_btn.clicked.connect(self._install_backend)
        self.manual_btn = _btn("MANUAL STEPS", C.TEXT_MED, 26)
        self.manual_btn.clicked.connect(self._show_manual_steps)
        row3.addWidget(self.install_btn)
        row3.addWidget(self.manual_btn)
        lay.addLayout(row3)

        self.backend_info = QPlainTextEdit()
        self.backend_info.setReadOnly(True)
        self.backend_info.setFont(QFont("Courier New", 7))
        self.backend_info.setFixedHeight(120)
        self.backend_info.setStyleSheet(f"""
            QPlainTextEdit {{ background: rgba(0,0,0,80); color: {C.TEXT_MED};
                              border: 1px solid {C.BORDER}; }}
        """)
        lay.addWidget(self.backend_info)

        lay.addWidget(_label("Install / download log", 7, C.TEXT_DIM))
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(110)
        self.log_box.setFont(QFont("Courier New", 7))
        self.log_box.setStyleSheet(f"""
            QPlainTextEdit {{ background: rgba(0,0,0,80); color: {C.TEXT_DIM};
                              border: 1px solid {C.BORDER}; }}
        """)
        lay.addWidget(self.log_box)
        return w

    # ── async plumbing ────────────────────────────────────────────────────
    def _async(self, fn, cb) -> None:
        def work():
            try:
                result = (True, fn())
            except Exception as exc:
                result = (False, exc)
            self._bg_queue.put((cb, result))
            self._bg_sig.emit()
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

    def _append_log(self, text: str) -> None:
        self.log_box.appendPlainText(str(text)[:500])
        bar = self.log_box.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_status(self, text: str, color: str = C.TEXT_MED) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; background: transparent;")

    # ── refresh / state ───────────────────────────────────────────────────
    def refresh_all(self, force: bool = False) -> None:
        self._async(lambda: self.svc.backend_status(force=force), self._on_backend)
        self._async(lambda: self.svc.list_models(refresh=force), self._on_models)
        self._async(lambda: self.svc.history(80), self._on_history)
        try:
            cfg = self.svc.get_settings()
            self.url_edit.setText(cfg.get("comfy_url", ""))
            self.path_edit.setText(cfg.get("comfy_path", ""))
            self.enhance_cb.setChecked(bool(cfg.get("enhance_prompt")))
            if not self.prompt.toPlainText().strip():
                self.negative.setPlainText(str(cfg.get("negative_prompt") or ""))
        except Exception:
            pass

    def _on_backend(self, ok: bool, status) -> None:
        if not ok:
            self._state_pill.setText("BACKEND CHECK FAILED")
            self.backend_info.setPlainText(f"{status}")
            return
        self._status_cache = status or {}
        s = self._status_cache
        lines = [
            f"URL            : {s.get('url', '')}",
            f"Installed      : {'yes — ' + s.get('install_path', '') if s.get('installed') else 'not found'}",
            f"Reachable      : {'yes' if s.get('reachable') else 'no'}",
        ]
        device = s.get("device") or {}
        if device:
            lines += [
                f"GPU            : {device.get('name', '')}",
                f"VRAM           : {device.get('vram_total_gb', '?')} GB "
                f"({device.get('vram_free_gb', '?')} GB free)",
            ]
        if s.get("comfy_version"):
            lines.append(f"ComfyUI        : {s['comfy_version']}")
        if s.get("error"):
            lines.append(f"Error          : {s['error']}")
        if s.get("remote"):
            lines.append("WARNING        : endpoint is not this machine — "
                         "prompts/images cross the network.")
        lines.append("Started by Keys.AI: "
                     f"{'yes' if s.get('started_by_keysai') else 'no'}")
        self.backend_info.setPlainText("\n".join(lines))
        self._footer.setText(
            f"output: {settings.output_dir(self.svc.get_settings())}")
        self.stop_btn.setEnabled(bool(s.get("started_by_keysai")))
        self._refresh_state()

    def _on_models(self, ok: bool, models) -> None:
        if not ok:
            return
        self._models_cache = models or []
        current = self.model_combo.currentData()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in self._models_cache:
            mark = "●" if m.get("installed") else "○"
            self.model_combo.addItem(
                f"{mark}  {m.get('short') or m.get('name')}", m.get("id"))
        idx = max(0, self.model_combo.findData(current))
        if self._models_cache and current is None:
            try:
                chosen = self.svc.get_settings().get("model_id")
                found = self.model_combo.findData(chosen)
                idx = found if found >= 0 else 0
            except Exception:
                idx = 0
        self.model_combo.setCurrentIndex(idx)
        self.model_combo.blockSignals(False)

        self.models_list.clear()
        for m in self._models_cache:
            mark = "●" if m.get("installed") else "○"
            text = (f"{mark} {m.get('name')}  —  "
                    f"{'installed' if m.get('installed') else 'not installed'}  "
                    f"({m.get('vram_label', '')})")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, m)
            if m.get("status") in ("unsupported", "requires_custom_nodes", "warn"):
                item.setForeground(QColor(C.ACC))
            self.models_list.addItem(item)
        self._refresh_state()

    def _on_history(self, ok: bool, records) -> None:
        if not ok:
            return
        selected = ""
        item = self.history_list.currentItem()
        if item is not None:
            selected = (item.data(Qt.ItemDataRole.UserRole) or {}).get("job_id", "")
        self.history_list.clear()
        for rec in records or []:
            created = str(rec.get("created_at") or "")[5:16]
            prompt = " ".join(str(rec.get("prompt") or "").split())[:52]
            status = str(rec.get("status") or "")
            if status == service_mod.COMPLETED and not rec.get("file_exists"):
                status = "file missing"
            item = QListWidgetItem(f"{created}  [{status[:9]}]  {prompt}")
            item.setData(Qt.ItemDataRole.UserRole, rec)
            self.history_list.addItem(item)
            if selected and rec.get("job_id") == selected:
                self.history_list.setCurrentItem(item)

    def _selected_model(self) -> dict | None:
        item = self.models_list.currentItem()
        if item is not None:
            return item.data(Qt.ItemDataRole.UserRole)
        data = self.model_combo.currentData()
        for m in self._models_cache:
            if m.get("id") == data:
                return m
        return None

    def _model_for_generation(self) -> dict | None:
        data = self.model_combo.currentData()
        for m in self._models_cache:
            if m.get("id") == data:
                return m
        return None

    def _refresh_state(self) -> None:
        s = self._status_cache or {}
        m = self._model_for_generation()
        if self._active_job:
            return                       # job text wins while generating
        if not s.get("reachable"):
            if not s.get("installed"):
                self._state_pill.setText("● BACKEND NOT INSTALLED")
                self._state_pill.setStyleSheet(
                    f"color: {C.RED}; background: transparent;")
                self._set_status(
                    "ComfyUI is not installed. Open BACKEND → INSTALL COMFYUI "
                    "(or MANUAL STEPS), then start it.", C.RED)
            else:
                self._state_pill.setText("● BACKEND NOT RUNNING")
                self._state_pill.setStyleSheet(
                    f"color: {C.ACC}; background: transparent;")
                self._set_status(
                    "ComfyUI is installed but not answering. Open BACKEND → "
                    "START BACKEND.", C.ACC)
            self.generate_btn.setEnabled(False)
            return
        if m is None:
            self._state_pill.setText("● NO MODEL")
            self._set_status("Select a model in the MODELS tab.", C.ACC)
            self.generate_btn.setEnabled(False)
            return
        if not m.get("installed"):
            self._state_pill.setText("● MODEL MISSING")
            self._state_pill.setStyleSheet(
                f"color: {C.ACC}; background: transparent;")
            self.model_state.setText(
                f"{m.get('name')} is not in ComfyUI yet — install it from MODELS.")
            self.model_state.setStyleSheet(
                f"color: {C.ACC}; background: transparent;")
            self.generate_btn.setEnabled(False)
            return
        self._state_pill.setText("● BACKEND READY")
        self._state_pill.setStyleSheet(
            f"color: {C.GREEN}; background: transparent;")
        self.model_state.setText(
            f"{m.get('name')} ready · {m.get('vram_label', '')}")
        self.model_state.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent;")
        self._set_status("Ready. Describe an image and generate.", C.TEXT_MED)
        self.generate_btn.setEnabled(not self._active_job)

    def _on_model_changed(self, _index: int) -> None:
        m = self._model_for_generation()
        if m:
            defaults = m.get("defaults") or {}
            self.width_spin.setValue(int(defaults.get("width") or 512))
            self.height_spin.setValue(int(defaults.get("height") or 512))
            self.steps_spin.setValue(int(defaults.get("steps") or 25))
            self.cfg_spin.setValue(float(defaults.get("guidance_scale") or 7.5))
            self.batch_spin.setMaximum(int(m.get("max_batch") or 1))
            if not self.negative.toPlainText().strip():
                self.negative.setPlainText(defaults.get("negative_prompt") or "")
            self.svc.save_settings({"model_id": m.get("id"),
                                    "last_model": m.get("id")})
        self._refresh_state()

    def _on_model_select(self, *_args) -> None:
        m = self._selected_model()
        if not m:
            return
        details = [
            m.get("name", ""),
            m.get("type_label", ""),
            "",
            m.get("description", ""),
            "",
            f"VRAM: {m.get('vram_label', '')} "
            f"(needs ~{m.get('min_vram_gb', '?')} GB)",
            f"Max edge: {m.get('max_edge', '?')} px · "
            f"batch ≤ {m.get('max_batch', 1)}",
            f"Custom nodes: {', '.join(m.get('custom_nodes') or []) or 'none'}",
            f"Licence: {m.get('license', 'unknown')}",
            f"  {m.get('license_note', '')}",
            f"Status: {m.get('status_note', '')}",
        ]
        if m.get("files"):
            details.append("")
            details.append("Files:")
            for f in m["files"]:
                size = (f.get("size_bytes") or 0) / 1e9
                details.append(
                    f"  {'✓' if f.get('present') else '✗'} {f['filename']} "
                    f"({size:.2f} GB) → models/{f['folder']}/")
        self.model_details.setPlainText("\n".join(details))
        can_download = bool(m.get("files")) and not m.get("installed")
        self.dl_btn.setEnabled(can_download and not self._downloading)
        self.del_btn.setEnabled(bool(m.get("installed"))
                                and not m.get("id", "").startswith("local:"))
        self.activate_btn.setEnabled(bool(m.get("installed")))

    # ── generation ────────────────────────────────────────────────────────
    def _collect_request(self) -> dict:
        seed = self.seed_spin.value()
        return {
            "prompt": self.prompt.toPlainText().strip(),
            "negative_prompt": self.negative.toPlainText().strip(),
            "model_id": self.model_combo.currentData(),
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "steps": self.steps_spin.value(),
            "guidance_scale": self.cfg_spin.value(),
            "seed": seed,
            "batch_size": self.batch_spin.value(),
            "output_format": self.format_combo.currentText().lower(),
            "input_image": self._input_image,
            "denoise_strength": 0.65,
        }

    def _on_generate_clicked(self) -> None:
        if self.enhance_cb.isChecked():
            self._enhance_flow()
        else:
            self._generate()

    def _generate(self, request: dict | None = None,
                  original_prompt: str = "") -> None:
        if self._active_job:
            return
        request = request or self._collect_request()
        if original_prompt:
            request["original_prompt"] = original_prompt
        if not request.get("input_image"):
            request.pop("input_image", None)
            request.pop("denoise_strength", None)
        if not request["prompt"]:
            self._set_status("Enter a prompt first.", C.RED)
            return

        self.svc.save_settings({
            "model_id": request.get("model_id"),
            "width": request.get("width"), "height": request.get("height"),
            "steps": request.get("steps"),
            "guidance_scale": request.get("guidance_scale"),
            "seed": request.get("seed"),
            "batch_size": request.get("batch_size"),
            "negative_prompt": request.get("negative_prompt", ""),
            "output_format": request.get("output_format"),
            "enhance_prompt": self.enhance_cb.isChecked(),
        })

        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self._set_status("Submitting job…", C.TEXT_MED)
        self._async(lambda: self.svc.generate(request), self._on_job_started)

    def _on_job_started(self, ok: bool, result) -> None:
        if not ok:
            msg = str(result)
            self._set_status(f"✗ {msg}", C.RED)
            self._state_pill.setText("● GENERATION FAILED")
            self._state_pill.setStyleSheet(f"color: {C.RED}; background: transparent;")
            self.generate_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.progress.setValue(0)
            return
        self._active_job = result.get("job_id", "")
        self._state_pill.setText("● GENERATION QUEUED")
        self._state_pill.setStyleSheet(f"color: {C.ACC}; background: transparent;")
        self._set_status("Queued — waiting for ComfyUI…", C.TEXT_MED)
        self._poll_timer.start()
        self._async(lambda: self.svc.history(80), self._on_history)

    def _poll_job(self) -> None:
        job_id = self._active_job
        if not job_id:
            self._poll_timer.stop()
            return
        self._async(lambda: self.svc.get_job(job_id), self._on_job_tick)

    def _on_job_tick(self, ok: bool, job) -> None:
        if not ok or not job:
            return
        status = job.get("status")
        stage = job.get("stage") or status
        progress = job.get("progress") or 0.0
        self.progress.setValue(int(progress))
        if status not in service_mod.TERMINAL:
            self._state_pill.setText(f"● {str(status).upper()}")
            self._state_pill.setStyleSheet(
                f"color: {C.ACC}; background: transparent;")
            self._set_status(f"{stage} — {progress:.0f}%", C.TEXT_MED)
            return

        self._poll_timer.stop()
        self.cancel_btn.setEnabled(False)
        self.generate_btn.setEnabled(True)
        if status == service_mod.COMPLETED:
            self.progress.setValue(100)
            self._state_pill.setText("● COMPLETED")
            self._state_pill.setStyleSheet(
                f"color: {C.GREEN}; background: transparent;")
            images = job.get("images") or []
            first = images[0] if images else {}
            self._show_image(job.get("image_path") or first.get("path", ""), job)
            extra = f" (+{len(images) - 1} more)" if len(images) > 1 else ""
            self._set_status(
                f"✓ Saved {Path(job.get('image_path', '')).name}{extra} "
                f"· seed {job.get('seed')}", C.GREEN)
        elif status == service_mod.CANCELLED:
            self.progress.setValue(0)
            self._state_pill.setText("● CANCELLED")
            self._state_pill.setStyleSheet(
                f"color: {C.TEXT_MED}; background: transparent;")
            self._set_status("Generation cancelled. No image was saved.", C.TEXT_MED)
        else:
            self.progress.setValue(0)
            self._state_pill.setText("● GENERATION FAILED")
            self._state_pill.setStyleSheet(
                f"color: {C.RED}; background: transparent;")
            error = job.get("error") or "Unknown failure."
            self._set_status(f"✗ {error}", C.RED)
            self._append_log(f"FAILED {job.get('job_id')}: {error}")
            for note in (job.get("diagnostics") or [])[-6:]:
                self._append_log(note)
        self._active_job = ""
        self._async(lambda: self.svc.history(80), self._on_history)
        self._async(lambda: self.svc.backend_status(force=True), self._on_backend)

    def _cancel(self) -> None:
        job_id = self._active_job
        if not job_id:
            return
        self.cancel_btn.setEnabled(False)
        self._set_status("Cancelling…", C.ACC)
        self._async(lambda: self.svc.cancel_job(job_id),
                    lambda ok, res: self._set_status(
                        res.get("message") or res.get("error", ""),
                        C.TEXT_MED if ok else C.RED))

    # ── prompt enhancement ────────────────────────────────────────────────
    def _enhance_only(self) -> None:
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            self._set_status("Write a prompt to enhance first.", C.RED)
            return
        self.enhance_btn.setEnabled(False)
        self.enhance_note.setText("Enhancing with a local Ollama model…")
        self._async(lambda: self.svc.enhance_prompt(prompt), self._on_enhanced)

    def _on_enhanced(self, ok: bool, result) -> None:
        self.enhance_btn.setEnabled(True)
        if not ok or not result.get("ok"):
            msg = str(result.get("error") if ok else result)
            self.enhance_note.setText(f"Enhancement unavailable: {msg}")
            return
        self.prompt.setPlainText(result["prompt"])
        self.enhance_note.setText(
            f"Enhanced with {result.get('model')} ({result.get('source', '')}). "
            "The generated image records this prompt.")

    def _enhance_flow(self) -> None:
        request = self._collect_request()
        original = request["prompt"]
        self._set_status("Enhancing prompt locally…", C.ACC)
        self.generate_btn.setEnabled(False)
        self._async(lambda: self.svc.enhance_prompt(original),
                    lambda ok, res: self._after_enhance(ok, res, request, original))

    def _after_enhance(self, ok: bool, result, request: dict, original: str) -> None:
        if not ok or not result.get("ok"):
            self.generate_btn.setEnabled(True)
            msg = result.get("error") if ok else str(result)
            self._append_log(f"enhance skipped: {msg}")
            self._set_status(f"Enhancement skipped — {msg}", C.ACC)
            self._generate(request, original_prompt=original)
            return
        enhanced = result["prompt"]
        if bool(self.svc.get_settings().get("enhance_preview", True)):
            dlg = _EnhanceDialog(self, original, enhanced,
                                 result.get("model", ""))
            dlg.exec()
            if dlg.choice == "cancel":
                self.generate_btn.setEnabled(True)
                self._set_status("Generation cancelled before submitting.", C.TEXT_MED)
                return
            if dlg.choice == "original":
                self._generate(request, original_prompt=original)
                return
            enhanced = dlg.text()
        self.prompt.setPlainText(enhanced)
        request["prompt"] = enhanced
        self._generate(request, original_prompt=original)

    # ── preview ───────────────────────────────────────────────────────────
    def _show_image(self, path: str, job: dict | None = None) -> None:
        p = Path(str(path or ""))
        if not p.is_file():
            self._set_status("The saved image is missing from disk.", C.RED)
            return
        pix = QPixmap(str(p))
        if pix.isNull():
            self._set_status("That image could not be opened.", C.RED)
            return
        self._pixmap = pix
        self._preview_path = str(p)
        self._zoom = 1.0
        self._fit()
        for b in (self.save_btn, self.copy_btn, self.reveal_btn):
            b.setEnabled(True)
        if job:
            self.meta_label.setText(
                f"{pix.width()}×{pix.height()} · "
                f"seed {job.get('seed')} · "
                f"{job.get('settings', {}).get('steps', '?')} steps · "
                f"CFG {job.get('settings', {}).get('guidance_scale', '?')} · "
                f"{job.get('model')}\n"
                + " ".join(str(job.get("prompt") or "").split())[:220])
        else:
            self.meta_label.setText(str(p))

    def _fit(self) -> None:
        if self._pixmap is None:
            return
        area = self.preview_scroll.viewport().size()
        scaled = self._pixmap.scaled(
            max(64, area.width() - 4), max(64, area.height() - 4),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.preview_label.setPixmap(scaled)
        self.preview_label.resize(scaled.size())

    def _zoom_by(self, delta: float) -> None:
        if self._pixmap is None:
            return
        self._zoom = max(0.1, min(4.0, self._zoom + delta))
        base = self._pixmap
        target = base.scaled(
            max(32, int(base.width() * self._zoom)),
            max(32, int(base.height() * self._zoom)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.preview_label.setPixmap(target)
        self.preview_label.resize(target.size())

    def _open_full(self) -> None:
        if not self._preview_path:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(Path(self._preview_path).name)
        dlg.setStyleSheet(f"background: {C.BG};")
        lay = QVBoxLayout(dlg)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        label = QLabel()
        label.setPixmap(QPixmap(self._preview_path))
        scroll.setWidget(label)
        lay.addWidget(scroll)
        dlg.resize(1000, 760)
        dlg.exec()

    def _save_copy(self) -> None:
        if not self._preview_path:
            return
        src = Path(self._preview_path)
        target, _ = QFileDialog.getSaveFileName(
            self, "Save image copy", str(src), f"{src.suffix.upper()[1:]} (*{src.suffix})")
        if not target:
            return
        try:
            Path(target).write_bytes(src.read_bytes())
            self._set_status(f"Saved a copy to {target}", C.GREEN)
        except Exception as exc:
            self._set_status(f"Could not save a copy: {exc}", C.RED)

    def _copy_prompt(self) -> None:
        text = ""
        item = self.history_list.currentItem()
        if item is not None:
            text = str((item.data(Qt.ItemDataRole.UserRole) or {}).get("prompt") or "")
        if not text:
            text = self.meta_label.text().split("\n")[-1]
        QApplication.clipboard().setText(text)
        self._set_status("Prompt copied to the clipboard.", C.TEXT_MED)

    def _reveal(self) -> None:
        if not self._preview_path:
            return
        res = self.svc.reveal_file(self._preview_path)
        if not res.get("ok"):
            self._set_status(res.get("error", ""), C.RED)

    def _open_output_dir(self) -> None:
        res = self.svc.open_output_dir()
        self._set_status(res.get("path") or res.get("error", ""),
                         C.TEXT_MED if res.get("ok") else C.RED)

    # ── image-to-image ────────────────────────────────────────────────────
    def _pick_input_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an input image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            validation.validate_input_image(path)
        except validation.ValidationError as exc:
            self._set_status(str(exc), C.RED)
            return
        self._input_image = path
        self.i2i_label.setText(f"img2img input: {Path(path).name}  ·  "
                               "denoise 0.65 (change with the model defaults)")
        self._set_status("Image-to-image enabled for the next generation.", C.TEXT_MED)

    # ── history actions ───────────────────────────────────────────────────
    def _on_history_select(self, current, _previous) -> None:
        enabled = current is not None
        for b in (self.hist_open, self.hist_copy, self.hist_remove, self.hist_delete):
            b.setEnabled(enabled)
        if not enabled:
            return
        rec = current.data(Qt.ItemDataRole.UserRole) or {}
        path = rec.get("image_path") or ""
        if path and Path(path).is_file():
            self._show_image(path, {
                "settings": rec.get("settings") or {},
                "seed": rec.get("seed"),
                "model": rec.get("model"),
                "prompt": rec.get("prompt"),
            })
        else:
            self.meta_label.setText(
                f"Record {rec.get('job_id')} · {rec.get('status')} · "
                "image file missing")

    def _history_open(self) -> None:
        item = self.history_list.currentItem()
        if not item:
            return
        rec = item.data(Qt.ItemDataRole.UserRole) or {}
        path = rec.get("image_path") or ""
        if not path or not Path(path).is_file():
            self._set_status("That image is no longer on disk.", C.RED)
            return
        self._show_image(path, {"settings": rec.get("settings") or {},
                                "seed": rec.get("seed"),
                                "model": rec.get("model"),
                                "prompt": rec.get("prompt")})
        self.tabs.setCurrentIndex(0)

    def _history_copy(self) -> None:
        item = self.history_list.currentItem()
        if not item:
            return
        rec = item.data(Qt.ItemDataRole.UserRole) or {}
        QApplication.clipboard().setText(str(rec.get("prompt") or ""))
        self._set_status("Prompt copied.", C.TEXT_MED)

    def _history_remove(self, delete_file: bool) -> None:
        item = self.history_list.currentItem()
        if not item:
            return
        rec = item.data(Qt.ItemDataRole.UserRole) or {}
        job_id = rec.get("job_id", "")
        if not job_id:
            return
        if delete_file:
            answer = QMessageBox.question(
                self, "Delete image file?",
                "This deletes the saved image from disk as well as the history "
                "record. It cannot be undone.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._async(lambda: self.svc.remove_record(job_id, delete_file),
                    self._on_record_removed)

    def _on_record_removed(self, ok: bool, result) -> None:
        if not ok or not result.get("ok"):
            self._set_status(str(result.get("error") if ok else result), C.RED)
            return
        self._set_status("History record removed.", C.TEXT_MED)
        self._async(lambda: self.svc.history(80), self._on_history)

    # ── model actions ─────────────────────────────────────────────────────
    def _use_model(self) -> None:
        m = self._selected_model()
        if not m:
            return
        idx = self.model_combo.findData(m.get("id"))
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.svc.save_settings({"model_id": m.get("id")})
        self._set_status(f"Active model: {m.get('name')}", C.TEXT_MED)

    def _download_model(self) -> None:
        m = self._selected_model()
        if not m or not m.get("files") or self._downloading:
            return
        total = sum(int(f.get("size_bytes") or 0) for f in m["files"]) / 1e9
        answer = QMessageBox.question(
            self, "Download model",
            f"Download {m.get('name')}?\n\n"
            f"{total:.2f} GB will be written to ComfyUI's models folder.\n"
            f"Licence: {m.get('license')}\n\n"
            "The download can be stopped and resumed later.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._downloading = True
        self._abort_download.clear()
        self.dl_btn.setEnabled(False)
        self.dl_cancel.setEnabled(True)
        self._append_log(f"Downloading {m.get('name')} …")

        def work():
            return self.svc.download_model(
                m["id"],
                on_progress=lambda d: self._dl_sig.emit(
                    int(d.get("percent") or 0),
                    f"{d.get('received', 0) / 1e9:.2f} / "
                    f"{d.get('total', 0) / 1e9:.2f} GB"),
                should_stop=self._abort_download.is_set,
                on_log=self._log_sig.emit,
            )

        self._async(work, self._on_download_done)

    def _cancel_download(self) -> None:
        self._abort_download.set()
        self._append_log("Stopping download — the partial file is kept for resume.")

    def _on_download_progress(self, percent: int, text: str) -> None:
        self.progress.setValue(percent)
        self._set_status(f"Downloading model… {percent}% ({text})", C.ACC)

    def _on_download_done(self, ok: bool, result) -> None:
        self._downloading = False
        self.dl_cancel.setEnabled(False)
        self.dl_btn.setEnabled(True)
        self.progress.setValue(0)
        if ok and result.get("ok"):
            self._set_status("Model downloaded and verified.", C.GREEN)
            self._append_log("Download complete.")
        else:
            msg = str(result.get("error") if ok else result)
            self._set_status(f"Download failed: {msg}", C.RED)
            self._append_log(f"Download failed: {msg}")
        self.refresh_all(force=True)

    def _delete_model(self) -> None:
        m = self._selected_model()
        if not m or not m.get("installed"):
            return
        if m.get("id", "").startswith("local:"):
            self._set_status("Files installed outside AI Image Studio are not "
                             "deleted from here.", C.TEXT_MED)
            return
        answer = QMessageBox.question(
            self, "Delete model files",
            f"Delete {m.get('name')} from ComfyUI's models folder?\n\n"
            "The weights are removed from disk. You would need to download "
            "them again. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._async(lambda: self.svc.delete_model(m["id"], confirm=True),
                    self._on_model_deleted)

    def _on_model_deleted(self, ok: bool, result) -> None:
        if not ok or not result.get("ok"):
            self._set_status(str(result.get("error") if ok else result), C.RED)
        else:
            removed = result.get("deleted") or []
            self._set_status(f"Deleted {len(removed)} model file(s).", C.TEXT_MED)
            self._append_log(f"Deleted: {', '.join(Path(p).name for p in removed)}")
        self.refresh_all(force=True)

    # ── backend actions ───────────────────────────────────────────────────
    def _browse_comfy(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "ComfyUI folder")
        if path:
            self.path_edit.setText(path)

    def _save_backend_settings(self) -> None:
        url = self.url_edit.text().strip() or settings.DEFAULT_COMFY_URL
        try:
            from core.image_studio.comfy_client import normalise_url
            url = normalise_url(url)
        except Exception as exc:
            self._set_status(f"Invalid URL: {exc}", C.RED)
            return
        self.svc.save_settings({"comfy_url": url,
                                "comfy_path": self.path_edit.text().strip()})
        self.svc.reset_health()
        self._set_status("Backend settings saved.", C.TEXT_MED)
        self.refresh_all(force=True)

    def _start_backend(self) -> None:
        self.start_btn.setEnabled(False)
        self._set_status("Starting ComfyUI — this can take a minute while it "
                         "loads…", C.ACC)
        self._append_log("Starting ComfyUI …")
        self._async(lambda: self.svc.start_backend(on_log=self._log_sig.emit),
                    self._on_backend_started)

    def _on_backend_started(self, ok: bool, result) -> None:
        self.start_btn.setEnabled(True)
        if not ok or not result.get("ok"):
            msg = str(result.get("error") if ok else result)
            self._set_status(f"Backend did not start: {msg}", C.RED)
            self._append_log(msg)
            return
        mode = "already running" if result.get("already_running") else "started"
        self._set_status(f"ComfyUI {mode}.", C.GREEN)
        self.refresh_all(force=True)

    def _stop_backend(self) -> None:
        self._async(self.svc.stop_backend, self._on_backend_stopped)

    def _on_backend_stopped(self, ok: bool, result) -> None:
        if not ok or not result.get("ok"):
            self._set_status(str(result.get("message") if ok else result), C.TEXT_MED)
        else:
            self._set_status(result.get("message", "ComfyUI stopped."), C.TEXT_MED)
        self.refresh_all(force=True)

    def _show_manual_steps(self) -> None:
        from core.image_studio import installer
        target = Path(self.path_edit.text().strip() or
                      str(installer.default_install_target()))
        dlg = _TextDialog(self, "ComfyUI manual setup",
                          "\n".join(installer.manual_steps(target)))
        dlg.exec()

    def _install_backend(self) -> None:
        from core.image_studio import installer
        if self._installing:
            self._set_status("An installation is already running.", C.ACC)
            return
        target_text = self.path_edit.text().strip() or str(
            installer.default_install_target())
        target = Path(target_text)
        answer = QMessageBox.question(
            self, "Install ComfyUI",
            f"ComfyUI will be cloned into:\n{target}\n\n"
            "An isolated Python virtual environment is created there; the "
            "Keys.AI environment is not modified. Several GB will be "
            "downloaded (PyTorch + ComfyUI requirements) and it can take a "
            "while.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._installing = True
        self._abort_install.clear()
        self.install_btn.setEnabled(False)
        self._append_log(f"Installing ComfyUI into {target} …")
        self._set_status("Installing ComfyUI — see the log. This can take "
                         "10–30 minutes.", C.ACC)

        self._async(
            lambda: installer.install_comfy(
                target, on_log=self._log_sig.emit,
                should_stop=self._abort_install.is_set),
            self._on_install_done)

    def _on_install_done(self, ok: bool, result) -> None:
        self._installing = False
        self.install_btn.setEnabled(True)
        if not ok:
            msg = str(result)
            self._set_status(f"Installation did not complete: {msg}", C.RED)
            self._append_log(msg)
            self._append_log("Use MANUAL STEPS if the automatic path failed.")
            return
        self.path_edit.setText(result.get("path", ""))
        self.svc.save_settings({"comfy_path": result.get("path", "")})
        self._set_status("ComfyUI installed. Now install a model, then start "
                         "the backend.", C.GREEN)
        self._append_log(f"Installed at {result.get('path')}")
        self.tabs.setCurrentIndex(1)
        self.refresh_all(force=True)

    # ── lifecycle ─────────────────────────────────────────────────────────
    def resizeEvent(self, event):       # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._pixmap is not None and self._zoom == 1.0:
            self._fit()

    def shutdown(self) -> None:
        self._poll_timer.stop()
        self._abort_download.set()
        self._abort_install.set()


__all__ = ["ImageStudioPanel"]
