"""Reader: Hermes ``state.db`` -> IR.

Hermes's source of truth is its SQLite store; the ``~/.hermes/sessions/*.jsonl``
files are exports that newer Hermes builds no longer write, so a session that
exists only in ``state.db`` would otherwise be invisible to session-bridge.
This module reads sessions straight from the database — strictly read-only
(URI ``mode=ro``, so it can never touch the WAL of a live store) — by
exporting rows into the exact record shapes the JSONL reader parses.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from ..ir import Session
from .hermes import session_from_hermes_records


class HermesDbError(RuntimeError):
    """The database is not a readable Hermes store or lacks the session."""


def _connect_ro(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    if not path.is_file():
        raise HermesDbError(f"Hermes state.db not found: {path}")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if not {"sessions", "messages"} <= tables:
        conn.close()
        raise HermesDbError(f"not a Hermes state store: {path}")
    return conn


def _iso(ts: Any) -> Any:
    """Unix seconds -> ISO string; anything else passes through untouched."""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return ts


def export_hermes_records(
    db_path: str | Path, session_id: str
) -> list[dict[str, Any]]:
    """A session's rows as JSONL-shaped Hermes records (session_meta first).

    The output parses identically through ``read_hermes`` when written to a
    file, so exported sessions join every existing convert/register flow.
    """
    conn = _connect_ro(db_path)
    try:
        row = conn.execute(
            "SELECT model FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise HermesDbError(f"no session {session_id!r} in {db_path}")
        records: list[dict[str, Any]] = [
            {"role": "session_meta", "model": row[0], "platform": "hermes"}
        ]
        cursor = conn.execute(
            """
            SELECT role, content, tool_call_id, tool_calls, reasoning, timestamp
            FROM messages WHERE session_id = ? ORDER BY timestamp, id
            """,
            (session_id,),
        )
        for role, content, tool_call_id, tool_calls, reasoning, ts in cursor:
            rec: dict[str, Any] = {"role": role, "timestamp": _iso(ts)}
            if content is not None:
                rec["content"] = content
            if tool_call_id:
                rec["tool_call_id"] = tool_call_id
            if tool_calls:
                try:
                    parsed = json.loads(tool_calls)
                except (json.JSONDecodeError, TypeError):
                    parsed = None
                if parsed:
                    rec["tool_calls"] = parsed
            if reasoning:
                rec["reasoning"] = reasoning
            records.append(rec)
        return records
    finally:
        conn.close()


def read_hermes_db(db_path: str | Path, session_id: str) -> Session:
    """Read one session out of a Hermes state.db into the IR."""
    return session_from_hermes_records(export_hermes_records(db_path, session_id))


@dataclass(frozen=True)
class HermesDbSessionInfo:
    """Cheap per-session listing data for discovery."""

    session_id: str
    started_at: float
    last_at: float
    approx_bytes: int
    first_user: Optional[str]
    last_text: Optional[str]
    last_role: Optional[str]


def list_hermes_db_sessions(db_path: str | Path) -> list[HermesDbSessionInfo]:
    """Every session in the store with preview data, one query pass each."""
    conn = _connect_ro(db_path)
    try:
        infos: list[HermesDbSessionInfo] = []
        for sid, started_at in conn.execute(
            "SELECT id, started_at FROM sessions ORDER BY started_at DESC"
        ):
            last = conn.execute(
                "SELECT MAX(timestamp), COALESCE(SUM(LENGTH(COALESCE(content,''))),0) "
                "FROM messages WHERE session_id = ?",
                (sid,),
            ).fetchone()
            first_user = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                "AND content IS NOT NULL AND TRIM(content) != '' "
                "ORDER BY timestamp, id LIMIT 1",
                (sid,),
            ).fetchone()
            last_msg = conn.execute(
                "SELECT content, role FROM messages WHERE session_id = ? "
                "AND role IN ('user','assistant') "
                "AND content IS NOT NULL AND TRIM(content) != '' "
                "ORDER BY timestamp DESC, id DESC LIMIT 1",
                (sid,),
            ).fetchone()
            infos.append(
                HermesDbSessionInfo(
                    session_id=sid,
                    started_at=float(started_at or 0),
                    last_at=float(last[0] or started_at or 0),
                    approx_bytes=int(last[1] or 0),
                    first_user=first_user[0] if first_user else None,
                    last_text=last_msg[0] if last_msg else None,
                    last_role=last_msg[1] if last_msg else None,
                )
            )
        return infos
    finally:
        conn.close()
