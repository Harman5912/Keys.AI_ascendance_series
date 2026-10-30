"""Research Browser — the Keys.AI browser workspace.

A real Chromium view (QtWebEngine) with tabs, an address bar, and a research
sidebar that saves the page, captures genuine screenshots, downloads the images
the page is showing, and sends approved assets into the current project.

It is a page of the main window's centre view stack, opened from the right-hand
control panel — the same place, and the same way, the live camera opens. CLOSE
hands the centre view back to the HUD by emitting ``closed``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ui import C
from core.research_browser import collector, integration, library, paths, urls
from core.research_browser.service import BrowserService

_FIELD = f"""
    QLineEdit {{
        background: rgba(4, 9, 14, 230); color: {C.TEXT};
        border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 6px;
    }}
    QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
"""


def _btn(text: str, color: str = C.TEXT_MED, height: int = 24) -> QPushButton:
    button = QPushButton(text)
    button.setFixedHeight(height)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(f"""
        QPushButton {{
            background: transparent; color: {color};
            border: 1px solid {color}; border-radius: 3px;
            padding: 2px 8px; font-size: 8pt;
        }}
        QPushButton:hover {{ background: rgba(255, 215, 0, 22); }}
        QPushButton:disabled {{ color: {C.BORDER_B}; border-color: {C.BORDER}; }}
    """)
    return button


def _label(text: str, size: int = 8, color: str = C.TEXT_DIM) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {color}; font-size: {size}pt; background: transparent;")
    return label


class BrowserWorkspace(QWidget):
    #: The user closed the workspace (✕ CLOSE) — the host puts the HUD back.
    closed = pyqtSignal()

    def __init__(self, parent=None, service: BrowserService | None = None):
        super().__init__(parent)
        from core.research_browser import get_service
        self.svc = service or get_service()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            BrowserWorkspace {{
                background: rgba(3, 6, 10, 252);
                border: 1px solid {C.BORDER_B}; border-radius: 8px;
            }}
        """)
        self.task_id = "session"
        self.project_root = ""
        self._tab_ids: list[str] = []
        self._build()
        self.svc.attach_view(self.view)
        self.svc.tabs_changed.connect(self._sync_tabs)
        self.svc.tab_state_changed.connect(self._sync_state)
        self.svc.load_finished.connect(self._on_load_finished)
        self.svc.url_changed.connect(lambda *_: self._sync_state())
        self.svc.title_changed.connect(lambda *_: self._sync_state())
        self._sync_tabs()
        self._refresh_library()

    # ── layout ────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(_label("◈  RESEARCH BROWSER", 12, C.PRI))
        head.addSpacing(8)
        self.state_label = _label("idle", 8, C.TEXT_DIM)
        head.addWidget(self.state_label)
        head.addStretch()
        head.addWidget(_label("real Chromium · same page the agent reads", 7, C.TEXT_DIM))
        close = _btn("✕  CLOSE", C.TEXT_DIM)
        close.clicked.connect(self.closed.emit)
        head.addWidget(close)
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.back_btn = _btn("◀", C.TEXT_MED)
        self.back_btn.clicked.connect(lambda: self._act(self.svc.go_back, wait=False))
        self.fwd_btn = _btn("▶", C.TEXT_MED)
        self.fwd_btn.clicked.connect(lambda: self._act(self.svc.go_forward, wait=False))
        self.reload_btn = _btn("⟳", C.TEXT_MED)
        self.reload_btn.clicked.connect(self._reload)
        self.stop_btn = _btn("■", C.TEXT_MED)
        self.stop_btn.clicked.connect(lambda: self.svc.stop_navigation())
        for widget in (self.back_btn, self.fwd_btn, self.reload_btn, self.stop_btn):
            bar.addWidget(widget)

        self.address = QLineEdit()
        self.address.setStyleSheet(_FIELD)
        self.address.setPlaceholderText("Search or enter an address (https://…)")
        self.address.returnPressed.connect(self._navigate_from_bar)
        bar.addWidget(self.address, stretch=1)
        go = _btn("GO", C.PRI)
        go.clicked.connect(self._navigate_from_bar)
        bar.addWidget(go)
        self.search_combo = QComboBox()
        self.search_combo.addItems(["google", "duckduckgo", "bing"])
        engine = str(paths.load().get("search_engine") or "google").lower()
        if engine not in ("google", "duckduckgo", "bing"):
            engine = "google"
        self.search_combo.setCurrentText(engine)
        self.search_combo.setFixedWidth(105)
        self.search_combo.currentTextChanged.connect(self._set_search_engine)
        bar.addWidget(self.search_combo)
        root.addLayout(bar)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        self.tab_combo = QComboBox()
        self.tab_combo.setMinimumWidth(260)
        self.tab_combo.currentIndexChanged.connect(self._on_tab_changed)
        tab_row.addWidget(self.tab_combo, stretch=1)
        new_tab = _btn("+ TAB", C.TEXT_MED)
        new_tab.clicked.connect(lambda: self.svc.open_tab(""))
        tab_row.addWidget(new_tab)
        close_tab = _btn("CLOSE TAB", C.TEXT_MED)
        close_tab.clicked.connect(self._close_current_tab)
        tab_row.addWidget(close_tab)
        root.addLayout(tab_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.view = QWebEngineView()
        split.addWidget(self.view)
        split.addWidget(self._build_sidebar())
        # The page is the point of this workspace: it gets the width, and the
        # sources/assets panel stays as a narrow strip the user can drag wider.
        split.setStretchFactor(0, 9)
        split.setStretchFactor(1, 2)
        split.setSizes([1120, 250])
        root.addWidget(split, stretch=1)

        foot = QHBoxLayout()
        self.status = _label("", 7, C.TEXT_DIM)
        self.status.setWordWrap(True)
        foot.addWidget(self.status, stretch=1)
        self.task_edit = QLineEdit(self.task_id)
        self.task_edit.setFixedWidth(140)
        self.task_edit.setStyleSheet(_FIELD)
        self.task_edit.setToolTip("Task id — sources and assets are stored per task")
        self.task_edit.editingFinished.connect(self._set_task)
        foot.addWidget(_label("task", 7, C.TEXT_DIM))
        foot.addWidget(self.task_edit)
        root.addLayout(foot)

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(190)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(4)

        row = QHBoxLayout()
        self.save_source_btn = _btn("SAVE SOURCE", C.PRI)
        self.save_source_btn.clicked.connect(self._save_source)
        row.addWidget(self.save_source_btn)
        cap = _btn("CAPTURE", C.TEXT_MED)
        cap.clicked.connect(self._screenshot)
        row.addWidget(cap)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.selection_btn = _btn("COLLECT SELECTION", C.TEXT_MED)
        self.selection_btn.clicked.connect(self._collect_selection)
        row2.addWidget(self.selection_btn)
        self.images_btn = _btn("PAGE IMAGES", C.TEXT_MED)
        self.images_btn.clicked.connect(self._show_page_images)
        row2.addWidget(self.images_btn)
        lay.addLayout(row2)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {C.BORDER}; }}
            QTabBar::tab {{ background: transparent; color: {C.TEXT_DIM};
                            padding: 4px 8px; font-size: 8pt; }}
            QTabBar::tab:selected {{ color: {C.PRI};
                                     border-bottom: 1px solid {C.PRI}; }}
        """)
        self.source_list = QListWidget()
        self.asset_list = QListWidget()
        self.image_list = QListWidget()
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setStyleSheet(
            f"background: rgba(0,0,0,120); color: {C.TEXT_MED}; border: 1px solid {C.BORDER};")
        self.tabs.addTab(self.source_list, "SOURCES")
        self.tabs.addTab(self.asset_list, "ASSETS")
        self.tabs.addTab(self.image_list, "IMAGES")
        self.tabs.addTab(self.notes, "DETAIL")
        lay.addWidget(self.tabs, stretch=1)

        self.source_list.itemActivated.connect(self._open_source)
        self.asset_list.itemClicked.connect(self._show_asset)
        self.asset_list.itemActivated.connect(self._open_asset_file)
        self.image_list.itemActivated.connect(self._collect_image)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFixedHeight(90)
        self.detail.setStyleSheet(
            f"background: rgba(0,0,0,120); color: {C.TEXT_DIM}; "
            f"border: 1px solid {C.BORDER}; font-size: 7pt;")
        lay.addWidget(self.detail)

        project_row = QHBoxLayout()
        self.project_edit = QLineEdit()
        self.project_edit.setStyleSheet(_FIELD)
        self.project_edit.setPlaceholderText("Project folder for ADD TO PROJECT")
        project_row.addWidget(self.project_edit, stretch=1)
        browse = _btn("…", C.TEXT_MED)
        browse.clicked.connect(self._browse_project)
        project_row.addWidget(browse)
        lay.addLayout(project_row)

        actions = QHBoxLayout()
        self.add_btn = _btn("ADD TO PROJECT", C.PRI)
        self.add_btn.clicked.connect(self._add_asset_to_project)
        actions.addWidget(self.add_btn)
        self.approve_btn = _btn("APPROVE", C.TEXT_MED)
        self.approve_btn.clicked.connect(lambda: self._approve_asset(True))
        actions.addWidget(self.approve_btn)
        self.reject_btn = _btn("REJECT", C.TEXT_DIM)
        self.reject_btn.clicked.connect(lambda: self._approve_asset(False))
        actions.addWidget(self.reject_btn)
        lay.addLayout(actions)

        self.refresh_btn = _btn("REFRESH LIBRARY", C.TEXT_DIM)
        self.refresh_btn.clicked.connect(self._refresh_library)
        lay.addWidget(self.refresh_btn)
        return panel

    # ── helpers ───────────────────────────────────────────────────────────
    def _current(self) -> str:
        return self.svc.active_tab()

    def _set_status(self, text: str, color: str = C.TEXT_DIM) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-size: 7pt;")

    def _act(self, fn, *args, wait=True, **kwargs):
        result = fn(*args, **kwargs)
        if not result.get("ok"):
            self._set_status(f"✗ {result.get('error', 'failed')}", C.RED)
        else:
            self._set_status("ok", C.GREEN)
        self._sync_state()
        return result

    def _set_task(self) -> None:
        self.task_id = (self.task_edit.text() or "session").strip() or "session"
        self._refresh_library()

    def _browse_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Project folder")
        if folder:
            self.project_root = folder
            self.project_edit.setText(folder)

    def _set_search_engine(self, engine: str) -> None:
        """Remember the chosen engine — Google is the default, not DuckDuckGo."""
        try:
            paths.save({"search_engine": str(engine or "google").lower()})
        except Exception:
            pass

    def _navigate_from_bar(self) -> None:
        target = self.address.text().strip()
        if not target:
            return
        if not self.svc.active_tab():
            self.svc.open_tab("")
        result = self.svc.navigate(self._current(), target,
                                   engine=self.search_combo.currentText())
        if not result.get("ok"):
            self._set_status(f"✗ {result.get('error')}", C.RED)
        self.view.setFocus()

    def _reload(self) -> None:
        tab = self._current()
        if tab:
            self.svc.reload_page(tab, wait=False)

    def _zoom(self, delta: float) -> None:
        state = self.svc.state(self._current())
        if state.get("ok"):
            self.svc.set_zoom(self._current(), float(state.get("zoom", 1.0)) + delta)

    def _close_current_tab(self) -> None:
        tab = self._current()
        if tab:
            self.svc.close_tab(tab)

    # ── service → UI ──────────────────────────────────────────────────────
    def _sync_tabs(self) -> None:
        tabs = self.svc.tabs()
        self._tab_ids = [t["tab_id"] for t in tabs]
        self.tab_combo.blockSignals(True)
        self.tab_combo.clear()
        for index, tab in enumerate(tabs):
            title = (tab["title"] or tab["url"] or "New tab")[:48]
            self.tab_combo.addItem(f"{index + 1}. {title}")
            if tab["active"]:
                self.tab_combo.setCurrentIndex(index)
        self.tab_combo.blockSignals(False)
        self._sync_state()

    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < len(self._tab_ids):
            self.svc.select_tab(self._tab_ids[index])

    def _sync_state(self) -> None:
        state = self.svc.state(self._current())
        if not state.get("ok"):
            return
        if self.address.text() != state["url"] and not self.address.hasFocus():
            self.address.setText(state["url"])
        self.back_btn.setEnabled(state["can_go_back"])
        self.fwd_btn.setEnabled(state["can_go_forward"])
        self.state_label.setText(
            ("loading…" if state["loading"] else "ready")
            + (f" · {state['title'][:40]}" if state.get("title") else ""))
        if state.get("error"):
            self._set_status(f"✗ {state['error']}", C.RED)
        if state.get("crashed"):
            self._set_status("✗ The page crashed. Press ⟳ to reload.", C.RED)
        self.view.setZoomFactor(float(state.get("zoom") or 1.0))

    def _on_load_finished(self, tab_id: str, ok: bool) -> None:
        if ok:
            self._set_status(f"loaded {self.svc.state(tab_id).get('url', '')}", C.GREEN)
        else:
            self._set_status("✗ page failed to load", C.RED)

    # ── collection actions ────────────────────────────────────────────────
    def _save_source(self) -> None:
        result = collector.save_source(self.svc, self._current(), self.task_id)
        if not result.get("ok"):
            self._set_status(f"✗ {result.get('error')}", C.RED)
            return
        source = result["source"]
        self._set_status(f"saved source {source['source_id']} "
                         f"({result['chars']} chars)", C.GREEN)
        self._refresh_library()
        self.tabs.setCurrentWidget(self.source_list)

    def _screenshot(self, full_page: bool = False) -> None:
        result = collector.capture(self.svc, self._current(),
                                   task_id=self.task_id, full_page=full_page)
        if not result.get("ok"):
            self._set_status(f"✗ {result.get('error')}", C.RED)
            return
        self._set_status(f"✓ {result['width']}×{result['height']} → "
                         f"{Path(result['path']).name}", C.GREEN)
        self.detail.setPlainText(result["path"])

    def _collect_selection(self) -> None:
        result = collector.collect_selection(self.svc, self._current(),
                                             task_id=self.task_id)
        if not result.get("ok"):
            self._set_status(f"✗ {result.get('error')}", C.RED)
            return
        self._set_status(f"✓ selection stored as "
                         f"{result['evidence']['evidence_id']}", C.GREEN)
        self._refresh_library()

    def _show_page_images(self) -> None:
        result = self.svc.list_page_images(self._current())
        if not result.get("ok"):
            self._set_status(f"✗ {result.get('error')}", C.RED)
            return
        self.image_list.clear()
        for index, image in enumerate(result["images"]):
            item = QListWidgetItem(
                f"{image.get('width') or '?'}×{image.get('height') or '?'}  "
                f"{(image.get('alt') or image.get('src', ''))[:60]}")
            item.setData(Qt.ItemDataRole.UserRole, image)
            self.image_list.addItem(item)
        self.tabs.setCurrentWidget(self.image_list)
        self._set_status(f"{len(result['images'])} image sources on this page")

    def _collect_image(self, item) -> None:
        image = item.data(Qt.ItemDataRole.UserRole) or {}
        src = image.get("src")
        if not src:
            return
        result = collector.collect_image(
            self.svc, self._current(), src, task_id=self.task_id,
            license_status="unknown")
        if not result.get("ok"):
            self._set_status(f"✗ {result.get('error')}", C.RED)
            return
        asset = result["asset"]
        self._set_status(
            f"✓ {asset['width']}×{asset['height']} {asset['format']} · "
            f"{asset['asset_id']} (licence {asset['license_status']})", C.GREEN)
        self._refresh_library()
        self.tabs.setCurrentWidget(self.asset_list)

    # ── library ───────────────────────────────────────────────────────────
    def _refresh_library(self) -> None:
        self.source_list.clear()
        for source in library.list_sources(self.task_id):
            mark = "✓" if source.get("inspected") else "○"
            item = QListWidgetItem(
                f"{mark} {source.get('title') or source.get('url')}"
                f"\n    {source.get('domain', '')}  ·  {source.get('status')}")
            item.setData(Qt.ItemDataRole.UserRole, source)
            self.source_list.addItem(item)
        self.asset_list.clear()
        for asset in library.list_assets(self.task_id):
            mark = "✓" if asset.get("approved") else "·"
            item = QListWidgetItem(
                f"{mark} {asset.get('width')}×{asset.get('height')} "
                f"{asset.get('format')}  {asset.get('filename')}"
                f"\n    {asset.get('license_status')}  ·  {asset.get('asset_id')}")
            item.setData(Qt.ItemDataRole.UserRole, asset)
            self.asset_list.addItem(item)
        coverage = library.coverage(self.task_id)
        self.notes.setPlainText(
            f"Task: {self.task_id}\n"
            f"Sources: {coverage['sources']} ({coverage['inspected']} inspected, "
            f"{coverage['failed']} failed)\n"
            f"Assets: {coverage['assets']} ({coverage['approved_assets']} approved, "
            f"{coverage['unknown_licence']} unknown licence)\n"
            f"Evidence: {coverage['evidence']}\n"
            f"Questions: {', '.join(coverage['questions']) or '—'}\n")
        self.detail.clear()

    def _open_source(self, item) -> None:
        source = item.data(Qt.ItemDataRole.UserRole) or {}
        if source.get("url"):
            self.svc.open_tab(source["url"], task_id=self.task_id)

    def _show_asset(self, item) -> None:
        asset = item.data(Qt.ItemDataRole.UserRole) or {}
        lines = [
            f"asset: {asset.get('asset_id')}",
            f"file: {asset.get('filename')}",
            f"size: {asset.get('width')}×{asset.get('height')} "
            f"{asset.get('format')} · {asset.get('size_bytes')} bytes",
            f"licence: {asset.get('license_status')}",
            f"source: {asset.get('source_url')}",
            f"page: {asset.get('page_url')}",
            f"sha256: {str(asset.get('sha256'))[:32]}…",
        ]
        self.detail.setPlainText("\n".join(lines))
        if asset.get("path"):
            pixmap = QPixmap(asset["path"])
            if not pixmap.isNull():
                self.tabs.setCurrentWidget(self.notes)

    def _open_asset_file(self, item) -> None:
        asset = item.data(Qt.ItemDataRole.UserRole) or {}
        path = asset.get("path") or ""
        if not Path(path).is_file():
            self._set_status("✗ that asset file is no longer on disk", C.RED)
            return
        try:
            if sys.platform == "win32":
                import os
                os.startfile(path)                    # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            self._set_status(f"✗ {exc}", C.RED)

    def _approve_asset(self, approved: bool) -> None:
        item = self.asset_list.currentItem()
        if item is None:
            self._set_status("select an asset first", C.RED)
            return
        asset = item.data(Qt.ItemDataRole.UserRole) or {}
        library.update_asset(asset["asset_id"], approved=bool(approved))
        self._refresh_library()
        self._set_status(("approved " if approved else "marked not approved ")
                         + asset["asset_id"], C.GREEN if approved else C.TEXT_MED)

    def shutdown(self) -> None:
        """Detach the engine view; the service itself is shut down by the app."""
        try:
            self.svc.detach_view()
        except Exception:
            pass
        try:
            self.view.setPage(None)
        except Exception:
            pass

    def _add_asset_to_project(self) -> None:
        item = self.asset_list.currentItem()
        if item is None:
            self._set_status("select an asset first", C.RED)
            return
        asset = item.data(Qt.ItemDataRole.UserRole) or {}
        root = self.project_edit.text().strip() or self.project_root
        if not root:
            self._set_status("choose a project folder (…) first", C.RED)
            return
        result = integration.add_to_project(asset["path"], root)
        if not result.get("ok"):
            self._set_status(f"✗ {result.get('error')}", C.RED)
            return
        library.link_usage(asset["asset_id"], result.get("dest", ""), role="embedded")
        self._set_status(f"✓ added → {result.get('reference')} "
                         f"(verified: {result.get('verified')})", C.GREEN)
        self._refresh_library()
