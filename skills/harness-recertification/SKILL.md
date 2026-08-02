---
name: session-bridge-harness-recertification
description: Re-verify session-bridge against a new Claude Code, Codex, or Hermes version and update the README supported-versions matrix. Use when a harness updates, when registration refuses with a schema error, when a reader starts mis-parsing real sessions, or when touching readers/, writers/, or the SQLite registrars.
---

# Harness recertification

session-bridge's real dependencies are three external tools' storage formats.
This is the procedure that keeps the README's supported-versions matrix honest
after any of them updates. Run it per affected harness; it needs a real
install of that harness.

## The live-recall acceptance test

The core check is always the same shape: prove the target harness actually
resumes a converted session with its context intact, not merely that a file
appeared.

1. **Seed TWO sentinels.** In the source harness, run a short real session
   where the USER states a unique fact ("the magic word is XYZZY-<random>")
   AND the ASSISTANT is made to reply with its own unique phrase, plus at
   least one tool call. User-turn recall and assistant-turn recall fail
   independently (Codex reconstructs them through different mechanisms), so
   a user-only sentinel proves half the transfer.
2. **Convert or register** into the target with session-bridge, exactly as a
   user would (use `--stub-open-calls` if the seed stopped mid-turn).
3. **Live-resume in the target** (`claude --resume`, `codex resume`,
   `hermes --resume`) and ask the model for the sentinel.
4. **Pass = the model recalls it.** A resume that opens but answers from a
   blank context is a FAIL (Hermes does this when `--model` names a model it
   cannot route; see README).
4b. **Hermes verification must use the interactive TUI** (drive it headlessly
   with vhs if needed): `hermes -z` oneshot mode silently ignores
   `--resume` and spawns a fresh session, so a -z reply proves nothing —
   confirm which session actually answered by checking state.db, not the
   reply text.
5. **Also verify the session is LISTED in the target's own picker/session
   list**, not only that direct-id resume works. The two paths have different
   requirements: Codex's picker demands an `event_msg` `user_message` record
   in the rollout, a native-format filename (local time, no ms/Z suffix),
   and populated index columns, none of which id-based resume checks. Codex
   also re-syncs index rows FROM the rollout file, so the rollout is the
   source of truth: fixing only the DB row gets silently reverted.

Round-trip reads too: convert target -> IR -> target and diff; the fixtures in
`tests/fixtures/` document the shapes each reader must keep parsing.

## When a schema guard refuses

The registrars fail closed by design. On refusal:

- Codex: `writers/codex_db.py:_require_schema` names the missing `threads`
  columns. Diff the live `state_5.sqlite` schema
  (`sqlite3 ~/.codex/state_5.sqlite '.schema threads'`) against the expected
  set, extend the writer AND its isolated-store DDL in `tests/test_codex_db.py`,
  then run the acceptance test above before trusting it.
- Hermes: same drill via `writers/hermes_db.py:_require_schema` against
  `~/.hermes/state.db` (`sessions`, `messages`).
- Hermes sessions may be db-only: newer builds write NO JSONL exports, so
  file-based checks silently test stale April-era exports. Source db-only
  sessions via `session-bridge export-hermes` (or the TUI, which reads
  state.db directly) and verify discovery lists them.
- Claude Code has no index; drift shows up as reader misparses instead. Compare
  a fresh transcript's record types against `readers/claude_code.py`'s handled
  set (unknown types must degrade to RAW blocks, never crash).

## Closing the loop

After a pass, update in the SAME commit:

1. The README supported-versions matrix row (harness, verified version, date).
2. Any fixture that had to change shape (keep fixtures synthetic; real
   transcripts may contain secrets and are gitignored under `fixtures/real/`).
3. A `fix(<harness>):` or `feat(<harness>):` commit if code changed — the
   commit type feeds the release changelog, which is where users learn a new
   harness version is supported.
