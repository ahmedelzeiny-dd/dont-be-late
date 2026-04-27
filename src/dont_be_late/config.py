"""
Loads config.yaml from the project root and exposes a typed Config object.
Missing keys fall back to safe defaults so the app always starts cleanly.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG_FILE = Path(__file__).parent.parent.parent / "config.yaml"

_DEFAULTS = {
    "alerts": {
        "require_accepted": True,
        "require_multiple_attendees": True,
        "open_in_browser": True,
    },
    "gcal": {
        "poll_interval_seconds": 60,
    },
    "user": {
        "office_location": "",
    },
}


@dataclass(frozen=True)
class AlertsConfig:
    require_accepted: bool
    require_multiple_attendees: bool
    open_in_browser: bool


@dataclass(frozen=True)
class GCalConfig:
    poll_interval_seconds: int


@dataclass(frozen=True)
class UserConfig:
    office_location: str


@dataclass(frozen=True)
class Config:
    alerts: AlertsConfig
    gcal: GCalConfig
    user: UserConfig


def load() -> Config:
    raw: dict = {}
    if _CONFIG_FILE.exists():
        with _CONFIG_FILE.open() as f:
            raw = yaml.safe_load(f) or {}

    alerts_raw = raw.get("alerts", {})
    ad = _DEFAULTS["alerts"]
    alerts = AlertsConfig(
        require_accepted=bool(alerts_raw.get("require_accepted", ad["require_accepted"])),
        require_multiple_attendees=bool(
            alerts_raw.get("require_multiple_attendees", ad["require_multiple_attendees"])
        ),
        open_in_browser=bool(alerts_raw.get("open_in_browser", ad["open_in_browser"])),
    )

    gcal_raw = raw.get("gcal", {})
    gd = _DEFAULTS["gcal"]
    gcal = GCalConfig(
        poll_interval_seconds=int(
            gcal_raw.get("poll_interval_seconds", gd["poll_interval_seconds"])
        ),
    )

    user_raw = raw.get("user", {})
    user = UserConfig(
        office_location=str(user_raw.get("office_location", _DEFAULTS["user"]["office_location"])),
    )

    return Config(alerts=alerts, gcal=gcal, user=user)
