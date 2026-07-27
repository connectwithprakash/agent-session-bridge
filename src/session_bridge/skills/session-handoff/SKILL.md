---
name: session-handoff
description: Hand off the CURRENT agent session to another harness (Claude Code, Codex, or Hermes) so the user can resume it there. Use when the user says "move/continue this session in <harness>", "convert this session", "hand off to codex/hermes/claude", or when a usage limit is about to stop this session. The source is the session this skill runs in; the destination is whatever harness the user names.
---

# Session handoff: continue this session in another harness

You are running inside a coding-agent session. The user wants this session
(or another one they name) to become resumable in a different harness. Use
the `session-bridge` CLI from this repo to do it. Everything is local files;
no network.

```
locate source file ─▶ inspect ─▶ convert or register ─▶ give resume command
```

## 0. Ensure session-bridge is installed

```bash
session-bridge --help >/dev/null 2>&1 || python3 -m pip install -e <path-to-this-repo>
```

(`<path-to-this-repo>` = the repo containing this skill file.)

## 1. Locate the source session file (the session you are in)

| You are running in | Where the transcript lives |
|---|---|
| Claude Code | `~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |
| Hermes | `~/.hermes/sessions/<ts>_<id>.jsonl` (exports; state.db is the truth) |

- **Claude Code:** encode the project cwd the way Claude Code does — resolve
  the real path (`os.path.realpath`; macOS symlinks like `/tmp` →
  `/private/tmp` matter), then replace every `/` with `-`. List that
  directory's `*.jsonl` by mtime; the newest one being actively written is
  the current session. Confirm by grepping it for a distinctive string from
  the current conversation.
- **Codex / Hermes:** newest file under the sessions tree, same confirmation
  grep.
- If the user names a *different* session ("yesterday's session about X"),
  find it the same way — by store, mtime, and a content grep — or run
  `session-bridge tui` and let the user pick from the discovery list.

## 2. Inspect before converting

```bash
session-bridge inspect --from <source-harness> <file>
```

Check the pending state it prints. If there are **open tool calls** (the
session stopped mid-turn), plan to add `--stub-open-calls` in step 3 —
providers reject a transcript whose tool call has no result, so the flag
appends a synthetic interrupted result and the handshake still discloses it.

## 3. Convert or register, by destination

Harness names: `claude-code`, `codex`, `hermes`.

**Destination Claude Code** — file placement is enough:

```bash
session-bridge convert --from <source> --to claude-code <file> \
  --place-claude-cwd <project-cwd> [--stub-open-calls]
```

It prints the placed path and the exact resume command
(`cd <cwd> && claude --resume <uuid>`). The cwd you place for must be the
directory the user will launch `claude` from.

**Destination Hermes** — needs a SQLite registration (a file drop is NOT
resumable):

```bash
session-bridge register --from <source> <file> \
  --model <hermes-configured-model> --title "<short title>" [--stub-open-calls]
```

`--model` matters: a cross-harness source id (e.g. `claude-*`) that Hermes
cannot route makes the resumed turn silently lose context. Ask the user
which Hermes model to use, or check `~/.hermes/` config. Resume:
`hermes --resume <printed sb_… id>`.

**Destination Codex** — rollout + SQLite index:

```bash
session-bridge register-codex --from <source> <file> \
  --cwd <project-cwd> --title "<short title>" [--stub-open-calls]
```

The model defaults to the most recently used one for provider `openai`;
pass `--model`/`--model-provider` if the user wants otherwise. Resume:
`cd <cwd> && codex resume <uuid>`.

Both register commands back up the store first and print the backup path —
keep `--no-backup` off unless the user explicitly asks.

## 4. Finish

- Relay the printed **resume command** to the user verbatim; that is the
  deliverable.
- Conversion notes on stderr list what could not transfer losslessly
  (thread forks, tool schemas, reasoning signatures, …). Summarize any that
  matter; the same notes are embedded in the transcript's resume handshake,
  so the receiving agent will see them too.
- A handoff of the CURRENT session captures it only up to the last flushed
  turn — anything after the conversion runs is not carried over, so run the
  handoff last, right before the user switches tools.

## Pitfalls

- Never `--force`/overwrite an existing placed transcript unless the user
  confirms — it may be a previously recovered session.
- Session ids must be UUID-shaped for Codex; let the tool generate them.
- Transcripts can contain secrets. Never commit converted session files;
  write outputs outside the repo (`fixtures/real/` is gitignored for a
  reason).
- Prefer `session-bridge tui` when the user should choose interactively;
  prefer the plain CLI when you already know source, file, and destination.
