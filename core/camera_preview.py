"""
Camera Preview — Live camera feed widget for the UI.

Shows a small preview window when camera is active.
Provides visual feedback that camera is working.
"""

from __future__ import annotations

import platform
import threading
import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QImage, QPixmap, QFont, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QSizePolicy, QFrame
)

_COLORS = {
    "bg": "rgba(10, 12, 18, 220)",
    "border": "rgba(255, 215, 0, 60)",
    "border_active": "rgba(0, 255, 136, 120)",
    "text": "#d9b650",
    "text_dim": "rgba(255, 215, 0, 120)",
    "accent": "#00ff88",
    "red": "#ff4466",
}


class CameraPreview(QWidget):
    """
    Small camera preview widget.
    
    Shows live camera feed with a header bar indicating status.
    Click to toggle between small/large preview.
    """
    
    # Signals
    frameCaptured = pyqtSignal(bytes)  # emitted with JPEG bytes when frame is ready
    closed = pyqtSignal()  # emitted when preview is closed
    
    _DEFAULT_W = 240
    _DEFAULT_H = 180
    
    def __init__(self, parent=None, camera_index: int = 0):
        super().__init__(parent)
        self._camera_index = camera_index
        self._cap = None
        self._running = False
        self._thread = None
        self._frame = None
        self._expanded = False
        
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self._DEFAULT_W, self._DEFAULT_H)
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the preview UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QFrame()
        header.setFixedHeight(24)
        header.setStyleSheet(f"""
            QFrame {{
                background: {_COLORS['bg']};
                border: 1px solid {_COLORS['border']};
                border-bottom: none;
                border-radius: 4px 4px 0 0;
            }}
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 2, 4, 2)
        
        self._status_label = QLabel("◉ CAMERA")
        self._status_label.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._status_label.setStyleSheet(f"color: {_COLORS['text']}; background: transparent;")
        header_layout.addWidget(self._status_label)
        header_layout.addStretch()
        
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {_COLORS['text_dim']};
                border: none; border-radius: 2px;
            }}
            QPushButton:hover {{ color: {_COLORS['red']}; }}
        """)
        close_btn.clicked.connect(self.close_preview)
        header_layout.addWidget(close_btn)
        
        layout.addWidget(header)
        
        # Image label
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(f"""
            background: {_COLORS['bg']};
            border: 1px solid {_COLORS['border']};
            border-top: none;
            border-radius: 0 0 4px 4px;
        """)
        self._image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self._image_label.setMinimumSize(120, 90)
        layout.addWidget(self._image_label, stretch=1)
        
        # Show placeholder
        self._show_placeholder()
    
    def _show_placeholder(self):
        """Show a placeholder image when camera is not active."""
        pixmap = QPixmap(200, 150)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background
        painter.setBrush(QColor(10, 12, 18, 200))
        painter.setPen(QPen(QColor(255, 215, 0, 40), 1))
        painter.drawRoundedRect(0, 0, 200, 150, 4, 4)
        
        # Camera icon
        painter.setPen(QPen(QColor(255, 215, 0, 100), 2))
        painter.drawEllipse(70, 45, 60, 60)
        painter.drawEllipse(85, 60, 30, 30)
        
        # Text
        painter.setPen(QColor(255, 215, 0, 80))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
                        "Camera Preview")
        
        painter.end()
        self._image_label.setPixmap(pixmap)
    
    def start_preview(self, camera_index: int = None):
        """Start the camera preview."""
        if camera_index is not None:
            self._camera_index = camera_index
        
        if self._running:
            return
        
        self._running = True
        self._status_label.setText("◉ ACTIVE")
        self._status_label.setStyleSheet(f"color: {_COLORS['accent']}; background: transparent;")
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        self.show()
    
    def _capture_loop(self):
        """Capture frames in a background thread."""
        try:
            import cv2
            try:
                backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            
            self._cap = cv2.VideoCapture(self._camera_index, backend)
            if not self._cap.isOpened():
                self._cap = cv2.VideoCapture(self._camera_index)
            
            if not self._cap.isOpened():
                self._update_status("NO CAMERA", False)
                return
            
            # Warm up
            for _ in range(3):
                self._cap.read()
            
            while self._running and self._cap.isOpened():
                ret, frame = self._cap.read()
                if ret and frame is not None:
                    # Encode to JPEG
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    jpeg_bytes = buf.tobytes()
                    
                    # Convert to QPixmap for display
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w
                    qt_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)
                    pixmap = QPixmap.fromImage(qt_img)
                    
                    # Scale to fit
                    scaled = pixmap.scaled(
                        self._image_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    
                    # Update UI in main thread
                    self._frame = scaled
                    QTimer.singleShot(0, lambda p=scaled: self._image_label.setPixmap(p))
                    
                    # Emit frame for external use
                    self.frameCaptured.emit(jpeg_bytes)
                
                time.sleep(0.033)  # ~30 FPS
        
        except ImportError:
            self._update_status("OPENCV MISSING", False)
        except Exception as e:
            self._update_status(f"ERROR: {e}", False)
        finally:
            if self._cap:
                self._cap.release()
            self._running = False
            QTimer.singleShot(0, lambda: self._update_status("STOPPED", False))
    
    def _update_status(self, text: str, active: bool):
        """Update status label (thread-safe via signal)."""
        QTimer.singleShot(0, lambda: self._set_status(text, active))
    
    def _set_status(self, text: str, active: bool):
        """Set status label text and color."""
        color = _COLORS['accent'] if active else _COLORS['text_dim']
        self._status_label.setText(f"◉ {text}")
        self._status_label.setStyleSheet(f"color: {color}; background: transparent;")
    
    def stop_preview(self):
        """Stop the camera preview."""
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None
        self._show_placeholder()
        self._update_status("STOPPED", False)
    
    def close_preview(self):
        """Close the preview window."""
        self.stop_preview()
        self.hide()
        self.closed.emit()
    
    def toggle_expand(self):
        """Toggle between small and large preview."""
        if self._expanded:
            self.setFixedSize(self._DEFAULT_W, self._DEFAULT_H)
            self._expanded = False
        else:
            self.setFixedSize(self._DEFAULT_W * 2, self._DEFAULT_H * 2)
            self._expanded = True
    
    def resizeEvent(self, event):
        """Handle resize to update image scaling."""
        super().resizeEvent(event)
        if self._frame:
            scaled = self._frame.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._image_label.setPixmap(scaled)
