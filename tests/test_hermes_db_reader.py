"""Reading sessions straight from Hermes's state.db (db-only sessions)."""

import json
import sqlite3
from pathlib import Path

import pytest

from session_bridge.cli import main
from session_bridge.ir import BlockType, Role
from session_bridge.readers.hermes import read_hermes
from session_bridge.readers.hermes_db import (
    HermesDbError,
    export_hermes_records,
    list_hermes_db_sessions,
    read_hermes_db,
)
from session_bridge.tui.actions import materialize
from session_bridge.tui.discovery import SessionEntry, scan_hermes

_SESSIONS_DDL = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    model TEXT,
    started_at REAL NOT NULL,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    title TEXT,
    cwd TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
"""
_MESSAGES_DDL = """
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    reasoning TEXT
);
"""


def _make_db(path: Path, session_id: str = "20260802_150838_12522c") -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(_SESSIONS_DDL + _MESSAGES_DDL)
    conn.execute(
        "INSERT INTO sessions (id, source, model, started_at, cwd) "
        "VALUES (?, 'cli', 'gpt-5.6-terra', 100.0, '/Users/x/proj')",
        (session_id,),
    )
    rows = [
        (session_id, "user", "convert me please", None, None, 101.0, None),
        (
            session_id,
            "assistant",
            None,
            None,
            json.dumps([{"id": "call-1", "function": {"name": "look", "arguments": "{\"q\": 1}"}}]),
            102.0,
            "thinking about it",
        ),
        (session_id, "tool", "the answer", "call-1", None, 103.0, None),
        (session_id, "assistant", "done, here you go", None, None, 104.0, None),
    ]
    conn.executemany(
        "INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, timestamp, reasoning) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return path


def test_read_hermes_db_builds_full_session(tmp_path):
    db = _make_db(tmp_path / "state.db")
    session = read_hermes_db(db, "20260802_150838_12522c")
    assert session.meta.model == "gpt-5.6-terra"
    assert session.meta.session_id == "20260802_150838_12522c"
    assert session.meta.cwd == "/Users/x/proj"
    roles = [m.role for m in session.messages]
    assert roles == [Role.USER, Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    kinds = [b.type for b in session.messages[1].content]
    assert BlockType.REASONING in kinds and BlockType.TOOL_CALL in kinds
    assert session.messages[2].content[0].call_id == "call-1"
    assert not session.pending.open_tool_calls


def test_export_parses_identically_through_file_reader(tmp_path):
    db = _make_db(tmp_path / "state.db")
    records = export_hermes_records(db, "20260802_150838_12522c")
    f = tmp_path / "export.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    from_file = read_hermes(f)
    from_db = read_hermes_db(db, "20260802_150838_12522c")
    assert [m.role for m in from_file.messages] == [m.role for m in from_db.messages]
    assert [m.text() for m in from_file.messages] == [m.text() for m in from_db.messages]


def test_db_errors_are_typed_not_raw(tmp_path):
    with pytest.raises(HermesDbError):
        read_hermes_db(tmp_path / "missing.db", "x")
    foreign = tmp_path / "foreign.db"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()
    with pytest.raises(HermesDbError):
        read_hermes_db(foreign, "x")
    db = _make_db(tmp_path / "state.db")
    with pytest.raises(HermesDbError):
        read_hermes_db(db, "no-such-session")


def test_discovery_lists_db_only_sessions(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_db(home / "state.db")
    entries = scan_hermes(home)
    (entry,) = entries
    assert entry.db_backed is True
    assert entry.session_id == "20260802_150838_12522c"
    assert entry.preview == "convert me please"
    assert entry.cwd == "/Users/x/proj"
    assert entry.last_preview == "done, here you go"
    assert entry.last_role == "assistant"
    assert entry.mtime == 104.0


def test_discovery_prefers_db_over_stale_jsonl_export(tmp_path):
    home = tmp_path / ".hermes"
    (home / "sessions").mkdir(parents=True)
    _make_db(home / "state.db")
    # A stale export of the SAME session, plus a file-only session.
    (home / "sessions" / "20260802_150838_12522c.jsonl").write_text(
        json.dumps({"role": "user", "content": "stale copy"}) + "\n"
    )
    (home / "sessions" / "20260101_000000_fileonly.jsonl").write_text(
        json.dumps({"role": "user", "content": "file only"}) + "\n"
    )
    entries = scan_hermes(home)
    by_id = {e.session_id: e for e in entries}
    assert len(entries) == 2
    assert by_id["20260802_150838_12522c"].db_backed is True
    assert by_id["20260101_000000_fileonly"].db_backed is False


def test_materialize_gives_db_entry_a_readable_file(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    db = _make_db(home / "state.db")
    (entry,) = scan_hermes(home)
    materialized = materialize(entry)
    assert materialized.db_backed is False
    assert materialized.path != db
    session = read_hermes(materialized.path)
    assert [m.text() for m in session.messages][0] == "convert me please"
    # file-backed entries pass through untouched
    assert materialize(materialized) is materialized


def test_cli_export_hermes(tmp_path, capsys, monkeypatch):
    db = _make_db(tmp_path / "state.db")
    out = tmp_path / "exported.jsonl"
    rc = main(["export-hermes", "20260802_150838_12522c", "--db", str(db), "-o", str(out)])
    assert rc == 0
    assert out.exists()
    session = read_hermes(out)
    assert len(session.messages) == 4
    # refuses to overwrite without --force
    rc = main(["export-hermes", "20260802_150838_12522c", "--db", str(db), "-o", str(out)])
    assert rc == 2
    rc = main(["export-hermes", "20260802_150838_12522c", "--db", str(db), "-o", str(out), "--force"])
    assert rc == 0
    # unknown session is a clean error
    rc = main(["export-hermes", "nope", "--db", str(db), "-o", str(tmp_path / "x.jsonl")])
    assert rc == 2
