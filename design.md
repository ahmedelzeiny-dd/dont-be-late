This updated design document integrates the dual-layered approach: a **passive visual persistent border** for the countdown and an **active modal interrupt** at the exact start time.

---

# Design Document: Chronos-Border v2.0
**Project Codename:** Chronos-Border  
**Primary Goal:** Prevent meeting-misses caused by hyperfocus on macOS via non-ignorable UI interrupts.

---

## 1. Functional Requirements

### Phase A: Peripheral Awareness (The Border)
* **T-minus 3 Minutes:** A 10px **Yellow** border appears around all displays.
* **T-minus 1 Minute:** The border changes to **Red** and begins a slow "breathing" pulse (transparency oscillation).
* **Behavior:** The border must sit above the Notch, Dock, and Full-screen apps. It must allow mouse clicks to pass through to the IDE (Click-through).

### Phase B: Forceful Interrupt (The Dialogue)
* **T-minus 0 Minutes:** A system-level modal dialogue box appears in the center of the screen.
* **Action:** The dialogue must play a "Critical" system sound and offer two buttons: **"Join Now"** (launches URL) and **"Dismiss"**.
* **Focus:** The dialogue box must steal focus to ensure that hitting "Enter" while typing accidentally interacts with the alert (ideally launching the meeting).

---

## 2. System Architecture

The system operates as a background daemon with three specialized modules:

| Module | Technology | Responsibility |
| :--- | :--- | :--- |
| **GCal Poller** | `google-api-python-client` | Fetches events every 60s; extracts Zoom/Meet URLs via Regex. |
| **Overlay Manager** | `PyQt6` + `PyObjC` | Manages the transparent, full-screen border window. |
| **Interrupt Controller** | `AppleScript` (via `osascript`) | Triggers the system-critical modal and handles the "Join" logic. |

---

## 3. Technical Implementation Details

### Overlay Layering (The "Ghost" Window)
To ensure the border is "always visible" even in Full-Screen mode or different Spaces, the `NSWindow` must be configured with specific macOS-level behaviors:

* **Window Level:** `kCGStatusWindowLevel` (or `NSStatusWindowLevel`). This places the window above almost every other element in the macOS Window Server.
* **Collection Behavior:** * `NSWindowCollectionBehaviorCanJoinAllSpaces`: Ensures the border follows you when you swipe between desktops.
    * `NSWindowCollectionBehaviorFullScreenAuxiliary`: Allows the border to show up on top of Full-Screen apps like VS Code or Terminal.

### The "Nuclear" Dialogue (T-0)
The dialogue box is triggered via a Python subprocess calling AppleScript. Using the `as critical` flag is essential for bypassing certain system silencers.

```python
# Conceptual logic for the T-0 Interrupt
def trigger_modal(meeting_name, url):
    apple_script = f'''
    tell application "System Events"
        activate
        display alert "MEETING STARTING: {meeting_name}" 
        message "Your flow state has been officially interrupted." 
        as critical 
        buttons {{"Dismiss", "JOIN NOW"}} 
        default button "JOIN NOW"
    end tell
    '''
    # Execution blocks until user interaction
    result = subprocess.run(["osascript", "-e", apple_script], capture_output=True)
    if "JOIN NOW" in result.stdout.decode():
        webbrowser.open(url)
```

---

## 4. State Logic Table

| Time ($T$) | Border State | Dialogue State | User Impact |
| :--- | :--- | :--- | :--- |
| $T > 3m$ | Hidden | Hidden | None |
| $3m \ge T > 1m$ | **Solid Yellow** | Hidden | Peripheral awareness |
| $1m \ge T > 0m$ | **Pulsing Red** | Hidden | High urgency; "Wrap it up" |
| $T \le 0m$ | **Solid Red** | **Visible Modal** | Hard stop; requires manual click/Enter |

---

## 5. Security & Permissions Requirements

To function as designed, the compiled script or `.app` wrapper requires:
1.  **Accessibility Permissions:** To allow the window to stay on top and potentially "activate" itself over other apps.
2.  **Calendar Access:** Or a valid `credentials.json` for the GCal API.
3.  **Screen Recording Permission:** (Required by macOS for certain `CoreGraphics` calls if you choose to implement screen-dimming/gamma-shifting).

---

## 6. Risks & Mitigations

* **Accidental Dismissal:** If you are typing fast, you might hit `Space` or `Enter` just as the box appears. 
    * *Mitigation:* The "Default" button is set to **Join Now**, so an accidental keypress puts you into the meeting rather than dismissing the alert.
* **The "Notch" Obstruction:** On modern MacBooks, a top-edge border might be hidden by the camera housing.
    * *Mitigation:* The border should be rendered with an inset or be thick enough (15px+) to be visible around the perimeter of the Notch.
* **API Latency:** Polling every 60s might miss the exact $T=0$ mark by a few seconds.
    * *Mitigation:* Use a local "Countdown Timer" that syncs with the API once, then relies on the system clock for the final 3-minute sequence.

---

This design ensures that your "flow state" is respected with a 3-minute warning, but your "professional reliability" is enforced at minute zero. How do you feel about the "Join Now" being the default button? (It's a bold move, but it's the most effective way to handle accidental keypresses).