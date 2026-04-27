#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_NAME="com.ahmed.dont-be-late.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DEST="$LAUNCH_AGENTS/$PLIST_NAME"

UV_BIN="$(which uv)"
if [[ -z "$UV_BIN" ]]; then
    echo "ERROR: uv not found on PATH. Install it first: https://docs.astral.sh/uv/"
    exit 1
fi

echo "Using uv at: $UV_BIN"
echo "Project dir: $SCRIPT_DIR"

# Substitute placeholders in the plist template
sed \
    -e "s|UV_BIN|$UV_BIN|g" \
    -e "s|PROJECT_DIR|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/$PLIST_NAME" > "$DEST"

echo "Installed plist to: $DEST"

# Unload if already loaded (ignore errors)
launchctl unload "$DEST" 2>/dev/null || true

launchctl load "$DEST"
echo "LaunchAgent loaded. Dont Be Late! will start on next login."
echo ""
echo "To start immediately:  launchctl start com.ahmed.dont-be-late"
echo "To stop:               launchctl stop com.ahmed.dont-be-late"
echo "To uninstall:          launchctl unload $DEST && rm $DEST"
echo "Logs:                  tail -f /tmp/dont-be-late.err"
