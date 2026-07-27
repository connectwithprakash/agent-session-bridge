"""Register a converted session in Codex's local session store.

Codex keeps its resumable-session index in ``state_5.sqlite``. A rollout JSONL
file alone is not discoverable by ``codex resume``: the store also needs a
``threads`` row that points at it. This module writes both pieces against a
caller-supplied Codex home so tests can exercise the real contract on an
isolated store.

The on-disk Codex schema evolves, so registration validates its required
``threads`` columns and fills optional columns only when present. It never
creates a database or tables implicitly. The CLI takes a SQLite backup before
calling this writer against the real store.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from .._ids import validate_session_id
from ..ir import Session
from .codex import workspace_write_policies, write_codex


class CodexRegistrationError(RuntimeError):
    """The target is not a compatible Codex store or registration failed."""


_REQUIRED_THREAD_COLUMNS = {
    "id",
    "rollout_path",
    "created_at",
    "updated_at",
    "source",
    "model_provider",
    "cwd",
    "title",
    "sandbox_policy",
    "approval_mode",
}


def _require_schema(conn: sqlite3.Connection) -> set[str]:
    """Return the ``threads`` columns or reject a non-Codex database."""
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "threads" not in tables:
        raise CodexRegistrationError("not a Codex state store (missing table: threads)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
    missing = _REQUIRED_THREAD_COLUMNS - columns
    if missing:
        raise CodexRegistrationError(
            f"incompatible Codex threads schema (missing columns: {sorted(missing)})"
        )
    return columns


def validate_codex_store(codex_home: str | Path) -> Path:
    """Verify and return the SQLite store path without mutating it."""
    db_path = Path(codex_home).expanduser() / "state_5.sqlite"
    if not db_path.is_file():
        raise CodexRegistrationError(f"Codex state_5.sqlite not found: {db_path}")
    # Read-only URI: this runs at plan/validation time, before any backup
    # exists, so it must not be able to touch the live store (a default
    # connect opens read-write and can checkpoint the WAL).
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        _require_schema(conn)
    finally:
        conn.close()
    return db_path


def infer_codex_model(codex_home: str | Path, model_provider: str = "openai") -> str | None:
    """Return the most recently used model for a configured Codex provider."""
    db_path = validate_codex_store(codex_home)
    # Read-only, and explicitly closed: sqlite3's context manager only manages
    # transactions, so a bare `with connect(...)` leaks the handle.
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = conn.execute(
            """
            SELECT model
            FROM threads
            WHERE model_provider = ? AND model IS NOT NULL AND model != ''
            ORDER BY recency_at_ms DESC, updated_at_ms DESC, updated_at DESC
            LIMIT 1
            """,
            (model_provider,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _atomic_write_jsonl(records: list[dict], target: Path) -> None:
    """Publish a complete rollout without replacing another registration's file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.link(temporary, target)
        os.unlink(temporary)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _first_user_text(session: Session) -> str:
    for message in session.messages:
        if message.role.value == "user":
            text = message.display_text().strip()
            if text:
                return text
    return ""


def _thread_values(
    columns: set[str],
    *,
    session_id: str,
    rollout_path: Path,
    session: Session,
    title: str,
    started_at: float,
    sandbox_policy: dict,
    approval_mode: str,
) -> dict[str, object]:
    """Build values only for columns present in the installed Codex schema."""
    seconds = int(started_at)
    milliseconds = int(started_at * 1000)
    first_user_message = _first_user_text(session)
    values: dict[str, object] = {
        "id": session_id,
        "rollout_path": str(rollout_path),
        "created_at": seconds,
        "updated_at": seconds,
        "source": "cli",
        "model_provider": session.meta.model_provider or "openai",
        "cwd": session.meta.cwd or "",
        "title": title,
        "sandbox_policy": json.dumps(sandbox_policy, separators=(",", ":")),
        "approval_mode": approval_mode,
        "tokens_used": 0,
        "has_user_event": int(bool(first_user_message)),
        "archived": 0,
        "cli_version": session.meta.version or "",
        "first_user_message": first_user_message,
        "memory_mode": "enabled",
        "model": session.meta.model,
        "reasoning_effort": None,
        "created_at_ms": milliseconds,
        "updated_at_ms": milliseconds,
        "thread_source": "user",
        "preview": first_user_message,
        "recency_at": seconds,
        "recency_at_ms": milliseconds,
        "history_mode": "legacy",
        "name": None,
    }
    return {name: value for name, value in values.items() if name in columns}


def register_codex_session(
    session: Session,
    codex_home: str | Path,
    session_id: str,
    *,
    cwd: str,
    title: str,
    model: str | None = None,
    model_provider: str = "openai",
    started_at: Optional[float] = None,
) -> Path:
    """Create a Codex rollout and its ``threads`` index row.

    ``session_id`` must be a safe UUID-shaped id accepted by ``codex resume``.
    ``cwd`` is required because Hermes transcripts do not retain a working
    directory and Codex uses it to filter the resume picker. The function writes
    the rollout atomically, then inserts the index row in one SQLite transaction;
    if indexing fails, the newly-created rollout is removed.

    Returns the created rollout path. Raises ``CodexRegistrationError`` for
    schema mismatches, id conflicts, unsafe ids, or an invalid working directory.
    """
    validate_session_id(session_id)
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise CodexRegistrationError("Codex session id must be a UUID") from exc

    resolved_cwd = os.path.realpath(os.path.expanduser(cwd))
    if not os.path.isdir(resolved_cwd):
        raise CodexRegistrationError(f"Codex target cwd does not exist: {resolved_cwd}")
    if not model_provider:
        raise CodexRegistrationError("Codex target model provider is required")
    if model is None and session.meta.model_provider == model_provider:
        model = session.meta.model
    if not model:
        raise CodexRegistrationError("Codex target model is required")

    home = Path(codex_home).expanduser()
    db_path = validate_codex_store(home)

    timestamp = started_at if started_at is not None else time.time()
    iso_timestamp = datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    day_path = datetime.fromtimestamp(timestamp, UTC).strftime("%Y/%m/%d")
    rollout_path = home / "sessions" / day_path / f"rollout-{iso_timestamp.replace(':', '-')}-{session_id}.jsonl"
    if rollout_path.exists():
        raise CodexRegistrationError(f"Codex rollout already exists: {rollout_path}")

    target_meta = replace(
        session.meta,
        session_id=session_id,
        cwd=resolved_cwd,
        model=model,
        model_provider=model_provider,
    )
    target_session = replace(session, meta=target_meta)
    transcript_sandbox, index_sandbox = workspace_write_policies(resolved_cwd)
    result = convert_session_to_codex(
        target_session,
        iso_timestamp,
        approval_policy="on-request",
        sandbox_policy=transcript_sandbox,
        file_system_sandbox_policy=index_sandbox["file_system"],
    )

    rollout_created = False
    try:
        _atomic_write_jsonl(result, rollout_path)
        rollout_created = True
        conn = sqlite3.connect(db_path)
        try:
            columns = _require_schema(conn)
            existing = conn.execute("SELECT 1 FROM threads WHERE id = ?", (session_id,)).fetchone()
            if existing:
                raise CodexRegistrationError(f"Codex session id already exists: {session_id}")
            values = _thread_values(
                columns,
                session_id=session_id,
                rollout_path=rollout_path,
                session=target_session,
                title=title,
                started_at=timestamp,
                sandbox_policy=index_sandbox,
                approval_mode="on-request",
            )
            names = list(values)
            placeholders = ", ".join("?" for _ in names)
            with conn:
                conn.execute(
                    f"INSERT INTO threads ({', '.join(names)}) VALUES ({placeholders})",
                    [values[name] for name in names],
                )
        finally:
            conn.close()
    except (sqlite3.Error, FileExistsError) as exc:
        if rollout_created:
            rollout_path.unlink(missing_ok=True)
        raise CodexRegistrationError(f"Codex registration failed: {exc}") from exc
    except BaseException:
        if rollout_created:
            rollout_path.unlink(missing_ok=True)
        raise
    return rollout_path


def convert_session_to_codex(
    session: Session,
    timestamp: str,
    *,
    approval_policy: str,
    sandbox_policy: dict,
    file_system_sandbox_policy: dict,
) -> list[dict]:
    """Render a prepared target session to Codex records without rereading a source."""
    records, _ = write_codex(
        session,
        timestamp=timestamp,
        approval_policy=approval_policy,
        sandbox_policy=sandbox_policy,
        file_system_sandbox_policy=file_system_sandbox_policy,
    )
    return records
