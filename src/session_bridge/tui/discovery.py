"""Cheap session discovery across the three harness stores.

The TUI needs a fast, fault-tolerant listing of every session on disk without
paying for a full parse of each transcript. Each scanner reads only the head
and tail of a file (``_head_lines`` / ``_tail_lines``) to extract identity
metadata (session id, cwd), a first-human-message preview, and the last
message, and stats each file exactly once.

Design rules:
- Never raise for a single bad file: any candidate that cannot be read or
  parsed is silently skipped so one corrupt transcript cannot blank the picker.
- Never decode Claude Code's dashed project directory names back into a cwd —
  that encoding is lossy ("-" is both the separator and a literal). The cwd is
  taken from the records themselves.
- Previews show what a HUMAN typed, not harness-injected context: Codex
  prepends AGENTS.md/environment messages as user-role records, and Claude
  Code transcripts carry command/hook records with user type.
- This module imports only stdlib + session_bridge internals; it must stay
  usable without the optional TUI framework installed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Generous enough for the picker's detail pane; the table column truncates
# further for its one-line cell.
_PREVIEW_LIMIT = 240


@dataclass(frozen=True)
class SessionEntry:
    harness: str  # one of convert.HARNESSES
    path: Path
    mtime: float
    size: int
    session_id: str | None
    cwd: str | None
    preview: str | None  # first HUMAN user-message text, truncated
    last_preview: str | None = None  # last conversational message text, truncated
    last_role: str | None = None  # "user" | "assistant" for last_preview
    # Hermes keeps its source of truth in state.db and newer builds write no
    # JSONL exports; db-backed entries carry the db path and need an export
    # (tui.actions.materialize) before file-based flows can use them.
    db_backed: bool = False
    # Set by materialize(): where the session REALLY lives, so activity
    # checks look at the live store rather than the temp export snapshot.
    origin_path: Path | None = None
    origin_db_backed: bool = False


# Real Claude Code transcripts open with a variable-length preamble of header
# records (file-history-snapshot, ai-title, last-prompt, ...) before the first
# user turn, so the head window must reach well past it to find cwd/preview.
_HEAD_WINDOW = 64
# Identity/preview metadata lives near the head in small records; cap the read
# so one pathological single-line file cannot exhaust memory mid-scan.
_MAX_LINE_BYTES = 1 << 20
# Tail window for the last-message preview: enough bytes to cover trailing
# tool-result noise before the last conversational turn, cheap even for
# multi-megabyte transcripts.
_TAIL_BYTES = 256 * 1024

# User-role records these harnesses inject that no human typed.
_CODEX_INJECTED_PREFIXES = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<permissions instructions>",
    "<user_instructions>",
    "<INSTRUCTIONS>",
    "<turn_aborted>",
)
_CLAUDE_INJECTED_PREFIXES = (
    "<command-",
    "<local-command",
    "Caveat:",
    "<system-reminder",
    "[Request interrupted",
)


def _head_lines(path: Path, n: int = _HEAD_WINDOW) -> list[dict]:
    """Parse the first ``n`` JSON lines of a JSONL file, skipping bad lines."""
    records: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for _ in range(n):
            line = fh.readline(_MAX_LINE_BYTES)
            if not line:
                break
            if len(line) >= _MAX_LINE_BYTES and not line.endswith("\n"):
                break  # over-long line: stop rather than misparse its remainder
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                records.append(obj)
    return records


def _tail_lines(path: Path, max_bytes: int = _TAIL_BYTES) -> list[dict]:
    """Parse the JSON lines in the file's last ``max_bytes``, oldest first.

    Seeks near the end and drops the first (possibly partial) line unless the
    read started at byte 0, so every returned record parsed from a complete
    line.
    """
    size = path.stat().st_size
    start = max(0, size - max_bytes)
    with open(path, "rb") as fh:
        fh.seek(start)
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    records: list[dict] = []
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _truncate(text: str) -> str | None:
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > _PREVIEW_LIMIT:
        return text[: _PREVIEW_LIMIT - 1] + "…"
    return text


def _joined_text(content: object, text_key: str = "text") -> str:
    """Flatten a message content value (str or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get(text_key), str):
                parts.append(block[text_key])
        return "\n".join(parts)
    return ""


def _injected(text: str, prefixes: tuple[str, ...]) -> bool:
    return text.lstrip().startswith(prefixes)


def _claude_message_text(rec: dict) -> tuple[str | None, str]:
    """(role, text) for a conversational Claude Code record, else (None, "")."""
    if rec.get("type") not in ("user", "assistant"):
        return None, ""
    message = rec.get("message")
    if not isinstance(message, dict):
        return None, ""
    text = _joined_text(message.get("content"))
    if not text.strip() or _injected(text, _CLAUDE_INJECTED_PREFIXES):
        return None, ""
    return rec["type"], text


def scan_claude_code(claude_home: Path | None = None) -> list[SessionEntry]:
    home = Path(claude_home) if claude_home is not None else Path.home() / ".claude"
    entries: list[SessionEntry] = []
    for path in sorted(home.glob("projects/*/*.jsonl")):
        try:
            stat = path.stat()
            head = _head_lines(path)
            cwd = None
            preview = None
            for rec in head:
                if cwd is None and isinstance(rec.get("cwd"), str):
                    cwd = rec["cwd"]
                if preview is None:
                    role, text = _claude_message_text(rec)
                    if role == "user":
                        preview = _truncate(text)
            last_preview = None
            last_role = None
            for rec in reversed(_tail_lines(path)):
                role, text = _claude_message_text(rec)
                if role:
                    last_preview = _truncate(text)
                    last_role = role
                    break
            entries.append(
                SessionEntry(
                    harness="claude-code",
                    path=path,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    session_id=path.stem,
                    cwd=cwd,
                    preview=preview,
                    last_preview=last_preview,
                    last_role=last_role,
                )
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            continue
    return entries


def _codex_event_text(rec: dict) -> tuple[str | None, str]:
    """(role, text) for a conversational Codex record, else (None, "").

    ``event_msg`` records are the authoritative human/agent markers: Codex
    writes a ``user_message`` twin only for real human input (injected
    AGENTS.md/environment context gets none) and ``agent_message`` for
    assistant replies.
    """
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return None, ""
    if rec.get("type") == "event_msg":
        if payload.get("type") == "user_message":
            return "user", payload.get("message") or ""
        if payload.get("type") == "agent_message":
            return "assistant", payload.get("message") or ""
    return None, ""


def scan_codex(codex_home: Path | None = None) -> list[SessionEntry]:
    home = Path(codex_home) if codex_home is not None else Path.home() / ".codex"
    entries: list[SessionEntry] = []
    # Sessions nest under YYYY/MM/DD date directories.
    for path in sorted(home.glob("sessions/*/*/*/rollout-*.jsonl")):
        try:
            stat = path.stat()
            head = _head_lines(path)
            session_id = None
            cwd = None
            event_preview = None
            fallback_preview = None
            for rec in head:
                payload = rec.get("payload")
                if not isinstance(payload, dict):
                    continue
                if rec.get("type") == "session_meta":
                    if session_id is None and isinstance(payload.get("id"), str):
                        session_id = payload["id"]
                    if cwd is None and isinstance(payload.get("cwd"), str):
                        cwd = payload["cwd"]
                    continue
                if event_preview is None:
                    role, text = _codex_event_text(rec)
                    if role == "user":
                        event_preview = _truncate(text)
                if (
                    fallback_preview is None
                    and rec.get("type") == "response_item"
                    and payload.get("type") == "message"
                    and payload.get("role") == "user"
                ):
                    text = _joined_text(payload.get("content"))
                    # Older rollouts (and other tools' imports) may lack
                    # event_msg records; skip the known injected preambles.
                    if text.strip() and not _injected(text, _CODEX_INJECTED_PREFIXES):
                        fallback_preview = _truncate(text)
            last_preview = None
            last_role = None
            for rec in reversed(_tail_lines(path)):
                role, text = _codex_event_text(rec)
                if role and text.strip():
                    last_preview = _truncate(text)
                    last_role = role
                    break
            entries.append(
                SessionEntry(
                    harness="codex",
                    path=path,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    session_id=session_id,
                    cwd=cwd,
                    preview=event_preview or fallback_preview,
                    last_preview=last_preview,
                    last_role=last_role,
                )
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            continue
    return entries


def scan_hermes(hermes_home: Path | None = None) -> list[SessionEntry]:
    home = Path(hermes_home) if hermes_home is not None else Path.home() / ".hermes"
    entries: list[SessionEntry] = []
    seen_ids: set[str] = set()

    # state.db is Hermes's source of truth (newer builds write no JSONL
    # exports at all), so scan it first; JSONL files then fill in only the
    # sessions the db doesn't know.
    db_path = home / "state.db"
    if db_path.is_file():
        try:
            from ..readers.hermes_db import list_hermes_db_sessions

            for info in list_hermes_db_sessions(db_path):
                seen_ids.add(info.session_id)
                entries.append(
                    SessionEntry(
                        harness="hermes",
                        path=db_path,
                        mtime=info.last_at,
                        size=info.approx_bytes,
                        session_id=info.session_id,
                        cwd=info.cwd,
                        preview=_truncate(info.first_user or ""),
                        last_preview=_truncate(info.last_text or ""),
                        last_role=info.last_role,
                        db_backed=True,
                    )
                )
        except Exception:
            # A corrupt/foreign db must not blank the picker; JSONL exports
            # below still surface whatever they can.
            pass

    for path in sorted(home.glob("sessions/*.jsonl")):
        try:
            stat = path.stat()
            # The Hermes session id IS the full filename stem (e.g.
            # "20260416_004124_10f12c82") — it's what state.db sessions.id
            # holds and what `hermes --resume` expects. Never split it.
            session_id = path.stem
            if session_id in seen_ids:
                continue  # the db copy is fresher; the file is an old export
            head = _head_lines(path)
            preview = None
            for rec in head:
                if rec.get("role") == "user":
                    preview = _truncate(_joined_text(rec.get("content")))
                    break
            last_preview = None
            last_role = None
            for rec in reversed(_tail_lines(path)):
                role = rec.get("role")
                if role in ("user", "assistant"):
                    text = _joined_text(rec.get("content"))
                    if text.strip():
                        last_preview = _truncate(text)
                        last_role = role
                        break
            entries.append(
                SessionEntry(
                    harness="hermes",
                    path=path,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    session_id=session_id or None,
                    cwd=None,
                    preview=preview,
                    last_preview=last_preview,
                    last_role=last_role,
                )
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            continue
    return entries


# A session written to within this window is treated as live: an agent is
# probably still appending, so a conversion would capture a moving target.
ACTIVE_WINDOW_SECONDS = 180


def last_activity(entry: SessionEntry) -> float | None:
    """The source's freshest write timestamp, queried live (never raises).

    Uses the origin store for materialized entries — the temp export's own
    mtime is meaningless (it is always "just now").
    """
    import sqlite3

    try:
        if entry.db_backed or entry.origin_db_backed:
            db = entry.origin_path if entry.origin_db_backed else entry.path
            conn = sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT MAX(timestamp) FROM messages WHERE session_id = ?",
                    (entry.session_id,),
                ).fetchone()
            finally:
                conn.close()
            return float(row[0]) if row and row[0] is not None else None
        return Path(entry.origin_path or entry.path).stat().st_mtime
    except Exception:
        return None


def is_active(entry: SessionEntry, *, now: float | None = None) -> bool:
    """True when the session's source was written to within the window."""
    import time

    ts = last_activity(entry)
    if ts is None:
        return False
    return ((now if now is not None else time.time()) - ts) < ACTIVE_WINDOW_SECONDS


def discover_sessions(
    *,
    claude_home: Path | None = None,
    codex_home: Path | None = None,
    hermes_home: Path | None = None,
) -> list[SessionEntry]:
    """All sessions across the three stores, newest first."""
    entries = (
        scan_claude_code(claude_home)
        + scan_codex(codex_home)
        + scan_hermes(hermes_home)
    )
    entries.sort(key=lambda entry: entry.mtime, reverse=True)
    return entries
