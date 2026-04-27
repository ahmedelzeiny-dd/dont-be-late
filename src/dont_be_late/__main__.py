"""
Dont Be Late! daemon entry point.

Usage:
  dont-be-late          # live mode: polls Google Calendar
  dont-be-late --test   # test mode: scripted yellow → red → modal in ~20s
  dont-be-late --auth   # run OAuth2 flow and save token, then exit
"""

import argparse
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

from PyQt6.QtCore import QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from .overlay import OverlayManager
from .interrupt import trigger_modal
from . import config as _config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sort_rooms(rooms: list[str], office_location: str) -> list[str]:
    """Put rooms matching the configured office first, preserve original order otherwise."""
    if not office_location:
        return rooms
    loc = office_location.lower()
    matching = [r for r in rooms if loc in r.lower()]
    others   = [r for r in rooms if loc not in r.lower()]
    return matching + others


def _format_label(name: str, start_dt: datetime, rooms: list[str] | None = None) -> str:
    local = start_dt.astimezone()
    t = local.strftime("%-I:%M %p")
    parts = [f"{name}  •  {t}"]
    if rooms:
        parts.append(", ".join(rooms))
    return "  •  ".join(parts)


def _make_icon(r: int, g: int, b: int) -> QIcon:
    px = QPixmap(18, 18)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(r, g, b))
    p.setPen(QColor(0, 0, 0, 120))
    p.drawEllipse(1, 1, 15, 15)
    p.end()
    return QIcon(px)


_ICON_IDLE   = None  # built lazily after QApplication exists
_ICON_YELLOW = None
_ICON_RED    = None


def _icons():
    global _ICON_IDLE, _ICON_YELLOW, _ICON_RED
    if _ICON_IDLE is None:
        _ICON_IDLE   = _make_icon(120, 120, 120)
        _ICON_YELLOW = _make_icon(255, 200, 0)
        _ICON_RED    = _make_icon(220, 30, 30)
    return _ICON_IDLE, _ICON_YELLOW, _ICON_RED


# ---------------------------------------------------------------------------
# Menu bar tray icon
# ---------------------------------------------------------------------------

class TrayIcon(QObject):
    """macOS menu-bar status icon. Thread-safe via signals."""

    _sig_yellow = pyqtSignal(str, object)
    _sig_red    = pyqtSignal(str, object)
    _sig_idle   = pyqtSignal()

    def __init__(self, app: QApplication):
        super().__init__()
        idle, _, _ = _icons()

        self._tray = QSystemTrayIcon(idle, app)
        self._tray.setToolTip("Dont Be Late!")

        self._menu = QMenu()
        self._status = self._menu.addAction("No upcoming meetings")
        self._status.setEnabled(False)
        self._menu.addSeparator()
        self._dismiss = self._menu.addAction("Dismiss")
        self._dismiss.setVisible(False)
        self._menu.addSeparator()
        self._menu.addAction("Quit", app.quit)
        self._tray.setContextMenu(self._menu)
        self._tray.show()

        self._sig_yellow.connect(self._on_yellow)
        self._sig_red.connect(self._on_red)
        self._sig_idle.connect(self._on_idle)

    # public — safe from any thread
    def set_yellow(self, label: str, on_dismiss=None) -> None:
        self._sig_yellow.emit(label, on_dismiss)

    def set_red(self, label: str, on_dismiss=None) -> None:
        self._sig_red.emit(label, on_dismiss)

    def set_idle(self) -> None:
        self._sig_idle.emit()

    def _wire_dismiss(self, on_dismiss) -> None:
        try:
            self._dismiss.triggered.disconnect()
        except (RuntimeError, TypeError):
            pass
        if on_dismiss:
            self._dismiss.triggered.connect(on_dismiss)
            self._dismiss.setVisible(True)
        else:
            self._dismiss.setVisible(False)

    # slots — main thread only
    def _on_yellow(self, label: str, on_dismiss) -> None:
        _, yellow, _ = _icons()
        self._tray.setIcon(yellow)
        self._status.setText(f"⏰  {label}")
        self._wire_dismiss(on_dismiss)

    def _on_red(self, label: str, on_dismiss) -> None:
        _, _, red = _icons()
        self._tray.setIcon(red)
        self._status.setText(f"🔴  {label}")
        self._wire_dismiss(on_dismiss)

    def _on_idle(self) -> None:
        idle, _, _ = _icons()
        self._tray.setIcon(idle)
        self._status.setText("No upcoming meetings")
        self._wire_dismiss(None)


# ---------------------------------------------------------------------------
# Test sequence
# ---------------------------------------------------------------------------

def _run_test_sequence(overlay: OverlayManager, tray: TrayIcon, cfg: _config.Config) -> None:
    print("TEST MODE — yellow border in 0s, red in 10s, modal in 20s")
    open_in_browser = cfg.alerts.open_in_browser
    fake_start = datetime.now(timezone.utc) + timedelta(minutes=3)
    label = _format_label("TEST MEETING", fake_start)

    def _dismiss():
        overlay.hide()
        tray.set_idle()

    def step_yellow():
        log.info("[TEST] Showing yellow border")
        overlay.show_yellow(label)
        tray.set_yellow(label, _dismiss)

    def step_red():
        log.info("[TEST] Switching to pulsing red border")
        overlay.show_red_pulse(label)
        tray.set_red(label, _dismiss)

    def step_modal():
        from .interrupt import _run_modal
        log.info("[TEST] Firing modal (open_in_browser=%s)", open_in_browser)
        _run_modal("TEST MEETING", "https://zoom.us/j/123456789", open_in_browser, _dismiss, [])
        log.info("[TEST] Modal dismissed — exiting in 5s")
        time.sleep(5)
        QApplication.instance().quit()

    step_yellow()
    QTimer.singleShot(10_000, step_red)
    QTimer.singleShot(20_000, lambda: threading.Thread(target=step_modal, daemon=True).start())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(prog="dont-be-late")
    parser.add_argument("--test", action="store_true",
                        help="Run scripted demo sequence instead of polling GCal")
    parser.add_argument("--auth", action="store_true",
                        help="Authenticate with Google Calendar and save credentials, then exit")
    args = parser.parse_args()

    if args.auth:
        from .gcal import _get_service
        print("Opening browser for Google Calendar authentication…")
        _get_service()
        print("Authentication complete. Token saved.")
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Remove dock icon — this is a background menu-bar daemon, not a normal app.
    try:
        from AppKit import NSApp, NSApplicationActivationPolicyAccessory
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

    cfg = _config.load()
    log.info(
        "Config loaded — require_accepted=%s, require_multiple_attendees=%s, open_in_browser=%s",
        cfg.alerts.require_accepted,
        cfg.alerts.require_multiple_attendees,
        cfg.alerts.open_in_browser,
    )

    overlay = OverlayManager()
    overlay.init_windows()
    tray = TrayIcon(app)

    if args.test:
        _run_test_sequence(overlay, tray, cfg)
    else:
        from .gcal import fetch_upcoming_events
        from .scheduler import EventScheduler

        office = cfg.user.office_location

        def _on_yellow(name: str, start_dt, event_id: str, rooms: list) -> None:
            sorted_rooms = _sort_rooms(rooms, office)
            label = _format_label(name, start_dt, sorted_rooms)
            start_ts = start_dt.isoformat()
            dismiss = lambda: (_on_hide(), scheduler.dismiss(event_id, start_ts))
            overlay.show_yellow(label)
            tray.set_yellow(label, dismiss)

        def _on_red(name: str, start_dt, event_id: str, rooms: list) -> None:
            sorted_rooms = _sort_rooms(rooms, office)
            label = _format_label(name, start_dt, sorted_rooms)
            start_ts = start_dt.isoformat()
            dismiss = lambda: (_on_hide(), scheduler.dismiss(event_id, start_ts))
            overlay.show_red_pulse(label)
            tray.set_red(label, dismiss)

        def _on_hide() -> None:
            overlay.hide()
            tray.set_idle()

        def _modal(name: str, url: str | None, rooms: list) -> None:
            sorted_rooms = _sort_rooms(rooms, office)
            trigger_modal(name, url, cfg.alerts.open_in_browser,
                          on_dismiss=_on_hide, rooms=sorted_rooms)

        scheduler = EventScheduler(
            fetch_events=fetch_upcoming_events,
            on_yellow=_on_yellow,
            on_red=_on_red,
            on_modal=_modal,
            on_hide=_on_hide,
            alerts_config=cfg.alerts,
            poll_interval_seconds=cfg.gcal.poll_interval_seconds,
        )
        scheduler.start()
        log.info("Dont Be Late! started (live mode)")

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    wakeup = QTimer()
    wakeup.timeout.connect(lambda: None)
    wakeup.start(200)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
