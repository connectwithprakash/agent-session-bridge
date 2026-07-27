---
name: session-handoff
description: Hand off the CURRENT agent session to another harness (Claude Code, Codex, or Hermes) so the user can resume it there. Use when the user says "move/continue this session in <harness>", "convert this session", "hand off to codex/hermes/claude", or when a usage limit is about to stop this session. The source is the session this skill runs in; the destination is whatever harness the user names.
---

The canonical skill ships inside the package so `session-bridge install-skill`
can distribute it to every harness on the machine. Read and follow it:

`src/session_bridge/skills/session-handoff/SKILL.md` (relative to this repo's
root; also reachable via the `skills/session-handoff` symlink).
