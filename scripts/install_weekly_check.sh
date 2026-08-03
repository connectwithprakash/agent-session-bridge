#!/usr/bin/env bash
# Install (or refresh) the weekly structure-check launchd job on macOS.
#
# Schedules scripts/weekly_structure_check.sh for Monday 09:30 local time,
# logging to ~/Library/Logs/session-bridge/structure-check.log. launchd runs
# a missed slot at the next wake, so a closed laptop only delays the check.
# Re-running this script after moving the repo updates the job in place.
#
# Uninstall: launchctl bootout "gui/$(id -u)/com.session-bridge.structure-check" \
#            && rm ~/Library/LaunchAgents/com.session-bridge.structure-check.plist
set -euo pipefail

if [ "$(uname)" != "Darwin" ]; then
    echo "This installer is macOS-only (launchd). On Linux, add a cron line like:"
    echo "  30 9 * * 1 $(cd "$(dirname "$0")" && pwd)/weekly_structure_check.sh >> ~/session-bridge-check.log 2>&1"
    exit 1
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.session-bridge.structure-check"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/session-bridge"
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$REPO/scripts/weekly_structure_check.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/structure-check.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/structure-check.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: $LABEL (Mondays 09:30, log: $LOG_DIR/structure-check.log)"
echo "run now:   launchctl kickstart -k gui/$(id -u)/$LABEL"
