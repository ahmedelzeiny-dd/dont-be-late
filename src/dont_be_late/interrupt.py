"""
T=0 modal interrupt via AppleScript.
Runs in a background thread so it never blocks the Qt event loop.
"""

import subprocess
import threading
import webbrowser
from typing import Callable

def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _resolve_url(url: str, open_in_browser: bool) -> str:
    """Return the URL to open.

    When open_in_browser is True, the URL is opened as-is in the default
    browser. For Zoom this shows the 'Open Zoom' interstitial page rather
    than launching the app directly.
    When False, the URL is handed to the system handler (opens the Zoom app).
    """
    return url


def trigger_modal(
    meeting_name: str,
    url: str | None,
    open_in_browser: bool = True,
    on_dismiss: Callable | None = None,
    rooms: list[str] | None = None,
) -> None:
    """Fire the modal in a daemon thread; open URL if user clicks Join Now."""
    thread = threading.Thread(
        target=_run_modal,
        args=(meeting_name, url, open_in_browser, on_dismiss, rooms or []),
        daemon=True,
    )
    thread.start()


def _run_modal(
    meeting_name: str,
    url: str | None,
    open_in_browser: bool,
    on_dismiss: Callable | None,
    rooms: list[str],
) -> None:
    safe_name = _escape_applescript(meeting_name)
    message_lines = [safe_name]
    if rooms:
        rooms_str = _escape_applescript(", ".join(rooms))
        message_lines.append(f"📍 {rooms_str}")
    safe_message = _escape_applescript("\n".join(message_lines))
    script = f'''
tell application "System Events"
    activate
    set result to display alert "MEETING STARTING NOW" ¬
        message "{safe_message}" ¬
        as critical ¬
        buttons {{"Dismiss", "JOIN NOW"}} ¬
        default button "JOIN NOW"
    return button returned of result
end tell
'''
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if "JOIN NOW" in proc.stdout and url:
        webbrowser.open(_resolve_url(url, open_in_browser))
    if on_dismiss:
        on_dismiss()
