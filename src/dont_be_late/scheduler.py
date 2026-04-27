"""
EventScheduler: polls GCal every 60s and fires overlay/interrupt callbacks
based on T-minus state for each upcoming event.
"""

import threading
import logging
from datetime import datetime, timezone
from typing import Callable, Any

from .config import AlertsConfig

log = logging.getLogger(__name__)

_PHASE_3MIN = "3min"
_PHASE_1MIN = "1min"
_PHASE_0 = "t0"


class EventScheduler:
    def __init__(
        self,
        fetch_events: Callable[[], list[dict]],
        on_yellow: Callable[[str, datetime, str, list], Any],
        on_red: Callable[[str, datetime, str, list], Any],
        on_modal: Callable[[str, str | None, list], None],
        on_hide: Callable,
        alerts_config: AlertsConfig | None = None,
        poll_interval_seconds: int = 60,
    ):
        self._fetch = fetch_events
        self._on_yellow = on_yellow
        self._on_red = on_red
        self._on_modal = on_modal
        self._on_hide = on_hide
        self._cfg = alerts_config
        self._poll_interval = poll_interval_seconds

        self._events: list[dict] = []
        self._fired: set[tuple[str, str]] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._lock = threading.Lock()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def dismiss(self, event_id: str, start_ts: str) -> None:
        """Pre-mark all phases for this event as fired so it won't re-trigger."""
        with self._lock:
            for phase in (_PHASE_3MIN, _PHASE_1MIN, _PHASE_0):
                self._fired.add((event_id, start_ts, phase))
        log.info("Dismissed event %s", event_id)

    def _refresh_events(self):
        try:
            events = self._fetch()
            with self._lock:
                self._events = events
            log.debug("Fetched %d upcoming events", len(events))
        except Exception:
            log.exception("GCal fetch failed")

    def _loop(self):
        self._refresh_events()
        tick = 0
        while not self._stop.wait(5):
            tick += 1
            if tick % max(1, self._poll_interval // 5) == 0:
                self._refresh_events()
            self._process()

    def _should_alert(self, ev: dict) -> bool:
        """Return False if any config filter rejects this event."""
        cfg = self._cfg
        if cfg is None:
            return True
        if cfg.require_accepted and ev.get("self_rsvp") != "accepted":
            log.debug("Skipping '%s': self_rsvp=%s", ev["name"], ev.get("self_rsvp"))
            return False
        if cfg.require_multiple_attendees and ev.get("attendee_count", 1) < 2:
            log.debug("Skipping '%s': only %d attendee(s)", ev["name"], ev.get("attendee_count", 1))
            return False
        return True

    def _process(self):
        now = datetime.now(timezone.utc)
        any_active = False

        with self._lock:
            events = list(self._events)

        for ev in events:
            if not self._should_alert(ev):
                continue
            delta = (ev["start_dt"] - now).total_seconds()
            eid = ev["id"]

            start_ts = ev["start_dt"].isoformat()

            if delta <= 0:
                any_active = True
                key = (eid, start_ts, _PHASE_0)
                if key not in self._fired:
                    self._fired.add(key)
                    log.info("T=0 for '%s'", ev["name"])
                    self._on_modal(ev["name"], ev.get("url"), ev.get("rooms", []))
            elif delta <= 60:
                any_active = True
                key = (eid, start_ts, _PHASE_1MIN)
                if key not in self._fired:
                    self._fired.add(key)
                    log.info("T-1min for '%s'", ev["name"])
                    self._on_red(ev["name"], ev["start_dt"], eid, ev.get("rooms", []))
            elif delta <= 180:
                any_active = True
                key = (eid, start_ts, _PHASE_3MIN)
                if key not in self._fired:
                    self._fired.add(key)
                    log.info("T-3min for '%s'", ev["name"])
                    self._on_yellow(ev["name"], ev["start_dt"], eid, ev.get("rooms", []))

        if not any_active:
            # Hide only if we had previously shown something
            if self._fired:
                self._on_hide()
                self._fired.clear()
