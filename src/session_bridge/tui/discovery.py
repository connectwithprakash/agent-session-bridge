"""Cheap session discovery across the three harness stores.

The TUI needs a fast, fault-tolerant listing of every session on disk without
paying for a full parse of each transcript. Each scanner reads only the head of
a file (``_head_lines``) to extract identity metadata (session id, cwd) and a
one-line preview, and stats each file exactly once.

Design rules:
- Never raise for a single bad file: any candidate that cannot be read or
  parsed is silently skipped so one corrupt transcript cannot blank the picker.
- Never decode Claude Code's dashed project directory names back into a cwd —
  that encoding is lossy ("-" is both the separator and a literal). The cwd is
  taken from the records themselves.
- This module imports only stdlib + session_bridge internals; it must stay
  usable without the optional TUI framework installed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_PREVIEW_LIMIT = 120


@dataclass(frozen=True)
class SessionEntry:
    harness: str  # one of convert.HARNESSES
    path: Path
    mtime: float
    size: int
    session_id: str | None
    cwd: str | None
    preview: str | None  # first user-message text, truncated


# Real Claude Code transcripts open with a variable-length preamble of header
# records (file-history-snapshot, ai-title, last-prompt, ...) before the first
# user turn, so the head window must reach well past it to find cwd/preview.
_HEAD_WINDOW = 64
# Identity/preview metadata lives near the head in small records; cap the read
# so one pathological single-line file cannot exhaust memory mid-scan.
_MAX_LINE_BYTES = 1 << 20


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


def _truncate(text: str) -> str | None:
    text = text.strip()
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
                if preview is None and rec.get("type") == "user":
                    message = rec.get("message")
                    if isinstance(message, dict):
                        preview = _truncate(_joined_text(message.get("content")))
            entries.append(
                SessionEntry(
                    harness="claude-code",
                    path=path,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    session_id=path.stem,
                    cwd=cwd,
                    preview=preview,
                )
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            continue
    return entries


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
            preview = None
            for rec in head:
                payload = rec.get("payload")
                if not isinstance(payload, dict):
                    continue
                if rec.get("type") == "session_meta":
                    if session_id is None and isinstance(payload.get("id"), str):
                        session_id = payload["id"]
                    if cwd is None and isinstance(payload.get("cwd"), str):
                        cwd = payload["cwd"]
                elif (
                    preview is None
                    and rec.get("type") == "response_item"
                    and payload.get("type") == "message"
                    and payload.get("role") == "user"
                ):
                    preview = _truncate(_joined_text(payload.get("content")))
            entries.append(
                SessionEntry(
                    harness="codex",
                    path=path,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    session_id=session_id,
                    cwd=cwd,
                    preview=preview,
                )
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            continue
    return entries


def scan_hermes(hermes_home: Path | None = None) -> list[SessionEntry]:
    home = Path(hermes_home) if hermes_home is not None else Path.home() / ".hermes"
    entries: list[SessionEntry] = []
    for path in sorted(home.glob("sessions/*.jsonl")):
        try:
            stat = path.stat()
            # The Hermes session id IS the full filename stem (e.g.
            # "20260416_004124_10f12c82") — it's what state.db sessions.id
            # holds and what `hermes --resume` expects. Never split it.
            session_id = path.stem
            head = _head_lines(path)
            preview = None
            for rec in head:
                if rec.get("role") == "user":
                    preview = _truncate(_joined_text(rec.get("content")))
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
                )
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            continue
    return entries


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
