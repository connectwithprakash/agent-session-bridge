#!/usr/bin/env bash
# Scheduled structural recertification against the real harness stores.
#
# Harnesses auto-update and have silently changed their store formats before
# (Codex rollout filename parsing, Hermes dropping JSONL exports). This runs
# the live acceptance matrix in --structure-only mode (no LLM calls): it
# seeds real sessions, bridges every pair whose CLIs are installed, verifies
# placement/registration structure, and cleans up after itself.
#
# Do not run it while the TUI or another acceptance run is mutating the
# stores. On failure it posts a macOS notification when osascript exists;
# the exit code is the runner's either way.
#
# Install the weekly launchd job with scripts/install_weekly_check.sh.
set -u

# launchd starts jobs with a minimal PATH; the harness CLIs, uv, and the
# session-bridge binary live in the standard user locations.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

echo "=== weekly structure check: $(date) ==="
uv run --extra dev --extra tui python scripts/live_acceptance.py --structure-only
status=$?

if [ "$status" -ne 0 ] && command -v osascript >/dev/null 2>&1; then
    osascript -e 'display notification "A harness update may have broken store compatibility. See ~/Library/Logs/session-bridge/structure-check.log" with title "session-bridge: structure check FAILED"'
fi
echo "=== exit $status ==="
exit "$status"
