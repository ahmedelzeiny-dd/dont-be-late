import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

BASE_DIR = Path(__file__).parent.parent.parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

_URL_PATTERN = re.compile(
    r"https?://(?:"
    r"[\w-]+\.zoom\.us/j/\S+"
    r"|meet\.google\.com/[a-z0-9-]+"
    r"|teams\.microsoft\.com/l/meetup-join/\S+"
    r")",
    re.IGNORECASE,
)


def _get_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def _extract_url(event: dict) -> str | None:
    # Check dedicated conference data first
    entry_points = (
        event.get("conferenceData", {}).get("entryPoints", [])
    )
    for ep in entry_points:
        if ep.get("entryPointType") == "video":
            return ep.get("uri")

    # Fall back to regex scan over description + location
    text = " ".join(
        filter(None, [event.get("description", ""), event.get("location", "")])
    )
    match = _URL_PATTERN.search(text)
    return match.group(0) if match else None


def fetch_upcoming_events(lookahead_minutes: int = 10) -> list[dict]:
    """Return events starting within the next `lookahead_minutes` minutes."""
    service = _get_service()
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(minutes=lookahead_minutes)

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        start_str = item["start"].get("dateTime") or item["start"].get("date")
        if not start_str:
            continue
        # Parse RFC3339 datetime; skip all-day events (no time component)
        if "T" not in start_str:
            continue
        start_dt = datetime.fromisoformat(start_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        attendees = item.get("attendees", [])
        # self_rsvp: the calendar owner's response ("accepted", "declined",
        # "tentative", "needsAction"). Falls back to "accepted" if there are
        # no attendees (organiser-only event with no invite list).
        self_rsvp = next(
            (a.get("responseStatus", "needsAction") for a in attendees if a.get("self")),
            "accepted" if not attendees else "needsAction",
        )
        # Room resources are attendees with "resource": True.
        rooms = [
            a.get("displayName") or a.get("email", "")
            for a in attendees
            if a.get("resource") and (a.get("displayName") or a.get("email"))
        ]
        events.append(
            {
                "id": item["id"],
                "name": item.get("summary", "Untitled Meeting"),
                "start_dt": start_dt,
                "url": _extract_url(item),
                "attendee_count": len(attendees) if attendees else 1,
                "self_rsvp": self_rsvp,
                "rooms": rooms,
            }
        )
    return events
