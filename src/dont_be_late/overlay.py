"""
Full-screen transparent border overlay.

States:
  hide()          — window invisible
  show_yellow()   — solid 15px yellow border
  show_red_pulse() — pulsing red border (opacity animation)
"""

import math
import time

from PyQt6.QtCore import Qt, QRect, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFontMetrics, QPainterPath
from PyQt6.QtWidgets import QWidget, QApplication

import ctypes
import objc
from AppKit import NSWindow
from Quartz import kCGOverlayWindowLevel

_BORDER = 15
_YELLOW = QColor(255, 200, 0, 230)
_RED = QColor(220, 30, 30, 230)


class BorderWindow(QWidget):
    def __init__(self, screen):
        super().__init__()
        geo = screen.geometry()
        self.setGeometry(geo)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._color = _YELLOW
        self._meeting_name: str = ""
        self._pulse_timer: QTimer | None = None
        self._pulse_start: float = 0.0

    def showEvent(self, event):
        """Re-apply the NS-level overrides every time Qt shows the window.

        Qt resets window properties on show(), so we must set the overlay level
        *after* Qt finishes its own show logic, not in __init__.
        """
        super().showEvent(event)
        self._configure_ns_window()

    def _configure_ns_window(self):
        """Pin the window above all application windows on every Space."""
        try:
            ns_view = objc.objc_object(c_void_p=ctypes.c_void_p(int(self.winId())))
            ns_win: NSWindow = ns_view.window()
            # kCGOverlayWindowLevel (102) sits above every normal app window
            # and above the status bar (25), so clicking other apps cannot
            # push the border behind them.
            ns_win.setLevel_(kCGOverlayWindowLevel)
            ns_win.setHidesOnDeactivate_(False)
            ns_win.setCollectionBehavior_(
                1 << 0   # NSWindowCollectionBehaviorCanJoinAllSpaces
                | 1 << 4  # NSWindowCollectionBehaviorStationary (don't move on Space switch)
                | 1 << 7  # NSWindowCollectionBehaviorFullScreenAuxiliary
            )
        except Exception:
            pass

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        b = _BORDER
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        # Top, bottom, left, right strips
        painter.drawRect(QRect(0, 0, w, b))
        painter.drawRect(QRect(0, h - b, w, b))
        painter.drawRect(QRect(0, b, b, h - 2 * b))
        painter.drawRect(QRect(w - b, b, b, h - 2 * b))

        if self._meeting_name:
            self._draw_label(painter, w, h, b)

    def _draw_label(self, painter: QPainter, w: int, h: int, b: int) -> None:
        """Draw the meeting name centred in the bottom border, scaled to fit,
        with a white fill and black outline."""
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(b - 4)  # 2px padding top + bottom

        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(self._meeting_name)
        available = w - 16  # 8px side padding each edge

        if text_w > available:
            font.setPixelSize(max(6, int((b - 4) * available / text_w)))
            fm = QFontMetrics(font)

        # Centre the text within the left half of the screen
        x = w / 4 - fm.horizontalAdvance(self._meeting_name) / 2
        y = fm.ascent() + (b - fm.height()) / 2

        path = QPainterPath()
        path.addText(x, y, font, self._meeting_name)

        # White outline
        painter.setPen(QColor(255, 255, 255, 200))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.strokePath(path, painter.pen())

        # Black fill
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 230))
        painter.fillPath(path, painter.brush())

    def _stop_pulse(self):
        if self._pulse_timer:
            self._pulse_timer.stop()
            self._pulse_timer = None

    def show_yellow(self, name: str = ""):
        self._stop_pulse()
        self._meeting_name = name
        self._color = _YELLOW
        self.update()
        self.show()

    def show_red_pulse(self, name: str = ""):
        self._stop_pulse()
        self._meeting_name = name
        self._pulse_start = time.monotonic()
        self.show()

        def _tick():
            elapsed = time.monotonic() - self._pulse_start
            # Smooth sine wave: alpha oscillates between 60 and 230 once per second
            alpha = int(145 + 85 * math.sin(2 * math.pi * elapsed))
            self._color = QColor(220, 30, 30, alpha)
            self.update()

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(_tick)
        self._pulse_timer.start(33)  # ~30 fps

    def hide_border(self):
        self._stop_pulse()
        self.hide()


class OverlayManager(QObject):
    """Manages one BorderWindow per physical display.

    Inherits QObject so its signals are automatically queued when emitted
    from a background thread — the slots always run on the main Qt thread.
    """

    _sig_yellow = pyqtSignal(str)
    _sig_red = pyqtSignal(str)
    _sig_hide = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._windows: list[BorderWindow] = []
        self._sig_yellow.connect(self._do_show_yellow)
        self._sig_red.connect(self._do_show_red)
        self._sig_hide.connect(self._do_hide)

    def init_windows(self):
        """Call after QApplication is running."""
        for screen in QApplication.screens():
            win = BorderWindow(screen)
            self._windows.append(win)

    # --- public API: safe to call from any thread ---

    def show_yellow(self, name: str = ""):
        self._sig_yellow.emit(name)

    def show_red_pulse(self, name: str = ""):
        self._sig_red.emit(name)

    def hide(self):
        self._sig_hide.emit()

    # --- slots: always execute on the main thread ---

    def _do_show_yellow(self, name: str):
        for w in self._windows:
            w.show_yellow(name)

    def _do_show_red(self, name: str):
        for w in self._windows:
            w.show_red_pulse(name)

    def _do_hide(self):
        for w in self._windows:
            w.hide_border()
