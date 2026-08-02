"""Side-effect layer behind the TUI's convert flow.

Split in two so the TUI can preview before committing:

- ``run_conversion`` is PURE — it produces a ``ConversionResult`` (records,
  loss report, handshake text) without touching the filesystem, so the TUI can
  render a preview and let the user back out.
- ``execute_writes`` performs every write the CLI's ``convert`` command would
  (output JSONL, optional handshake file, optional Claude Code placement) and
  reports the outcome as data. It never raises: the TUI renders errors, and a
  partial outcome (e.g. output written but placement refused) must survive the
  failure so the user knows what actually landed on disk.
"""

from __future__ import annotations

import shlex
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from .._ids import UnsafeSessionIdError
from ..convert import ConversionResult, convert, dump_jsonl, now_codex_timestamp
from ..place import SessionExistsError, UnsafeCwdError, place_claude_code
from .discovery import SessionEntry
from .options import ConvertOptions, resolve_output


def materialize(entry: SessionEntry) -> SessionEntry:
    """Give a db-backed Hermes entry a real JSONL file to feed file flows.

    Hermes sessions discovered from state.db have no transcript file; this
    exports the rows (read-only on the store) into a per-session temp cache
    and returns an equivalent file-backed entry. File-backed entries pass
    through untouched.
    """
    if not entry.db_backed:
        return entry
    from ..readers.hermes_db import export_hermes_records

    records = export_hermes_records(entry.path, entry.session_id or "")
    cache = Path(tempfile.gettempdir()) / "session-bridge-exports"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{entry.session_id}.jsonl"
    dump_jsonl(records, out)
    return replace(entry, path=out, db_backed=False)


def run_conversion(opts: ConvertOptions) -> ConversionResult:
    """Convert per ``opts`` without writing anything.

    Stamps Codex output with the real current time, matching the CLI (the
    writer's placeholder date would hide the session from Codex's recency
    sort).
    """
    codex_ts = now_codex_timestamp() if opts.target == "codex" else None
    return convert(
        opts.source,
        opts.target,
        opts.path,
        inject_handshake=not opts.no_handshake,
        codex_timestamp=codex_ts,
        stub_open_calls=opts.stub_open_calls,
    )


@dataclass
class WriteOutcome:
    output_path: Path | None
    record_count: int
    handshake_path: Path | None
    placed_path: Path | None
    resume_hint: str | None
    error: str | None  # None = full success


def execute_writes(
    result: ConversionResult,
    opts: ConvertOptions,
    *,
    claude_home: Path | None = None,
) -> WriteOutcome:
    """Perform all writes for a previously-run conversion.

    Errors are returned, never raised. Paths that were successfully written
    before the failure stay set in the outcome alongside ``error``.
    """
    output_path: Path | None = None
    handshake_path: Path | None = None
    placed_path: Path | None = None
    resume_hint: str | None = None

    def outcome(error: str | None) -> WriteOutcome:
        return WriteOutcome(
            output_path=output_path,
            record_count=len(result.records),
            handshake_path=handshake_path,
            placed_path=placed_path,
            resume_hint=resume_hint,
            error=error,
        )

    try:
        # A codex target's session_meta timestamp was stamped when the dry-run
        # conversion ran; the user may sit on that screen indefinitely, and the
        # CLI stamps immediately before writing. Re-run the (pure) conversion
        # so the written timestamp is bound to the write, like the CLI's.
        if opts.target == "codex":
            result = run_conversion(opts)

        out = resolve_output(opts)
        dump_jsonl(result.records, out)
        output_path = Path(out)

        if opts.handshake_out:
            hs = Path(opts.handshake_out)
            hs.write_text(result.handshake, encoding="utf-8")
            handshake_path = hs

        if opts.place_claude_cwd:
            session_id = opts.session_id or str(uuid.uuid4())
            placed_path = place_claude_code(
                result.records,
                opts.place_claude_cwd,
                session_id,
                claude_home=claude_home,
                overwrite=opts.force,
            )
            # Same hint the CLI prints after a successful placement.
            resume_hint = (
                f"(cd {shlex.quote(opts.place_claude_cwd)} "
                f"&& claude --resume {shlex.quote(session_id)})"
            )
    except (
        UnsafeSessionIdError,
        UnsafeCwdError,
        SessionExistsError,
        OSError,
        # The codex re-conversion re-reads the source file, which can have
        # changed since the dry run: parse failures are ValueErrors.
        ValueError,
    ) as exc:
        return outcome(str(exc))
    return outcome(None)
