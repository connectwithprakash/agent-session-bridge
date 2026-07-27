# Agent notes for session-bridge

This repo converts coding-agent sessions between Claude Code, Codex, and
Hermes so a session started in one harness can resume in another.

**Handing off a session** (including the one you are running in right now):
follow the skill at `.claude/skills/session-handoff/SKILL.md`. It covers
locating the current session's transcript, inspecting pending state, and the
per-destination convert/register commands with their resume incantations.
The skill applies to any agent that can run shell commands — it is not
Claude Code-specific.

Development basics: `python3 -m pytest` (or `uv run --extra dev pytest`)
runs the suite; the TUI needs the optional extra (`pip install -e '.[tui]'`).
Never commit real session transcripts — they can contain secrets.
