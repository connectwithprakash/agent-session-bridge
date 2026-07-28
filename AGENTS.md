# Agent notes for session-bridge

This repo converts coding-agent sessions between Claude Code, Codex, and
Hermes so a session started in one harness can resume in another.

## Skill routing

Repo-specific knowledge lives in `skills/` and versions with the code. Load
the skill BEFORE doing the work it governs:

| Doing | Load first |
|---|---|
| Handing off a session (including the one you are in) | `skills/session-handoff/SKILL.md` (product skill; also ships in the wheel) |
| Cutting/verifying a release, PyPI or brew trouble | `skills/releasing/SKILL.md` |
| A harness updated, a schema guard refused, or you are touching `readers/`, `writers/`, or the SQLite registrars | `skills/harness-recertification/SKILL.md` |

To make the handoff skill available machine-wide (outside this repo), run
`session-bridge install-skill` — it symlinks the packaged skill into the
skills directory of every harness present on the machine (`~/.claude`,
`~/.codex`, `~/.hermes`); `--copy` decouples it from the package.

## Development basics

- `uv run --extra dev pytest` runs the suite; run it again with
  `--extra tui` — CI enforces both configurations.
- Commits are Conventional Commits and they drive releases via
  release-please: `feat` -> minor, `fix` -> patch, `docs`/`chore`/`test` ->
  no release. Never hand-edit `CHANGELOG.md` or the pyproject `version`.
- Never commit real session transcripts — they can contain secrets
  (`fixtures/real/` is gitignored for this reason).
