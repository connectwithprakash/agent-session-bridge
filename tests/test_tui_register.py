"""Tests for the TUI register layer: pure planning, then explicit SQLite writes."""

import sqlite3
import uuid
from pathlib import Path

from session_bridge.handshake import HANDSHAKE_MARKER, INTERRUPTED_RESULT_TEXT
from session_bridge.ir import BlockType
from session_bridge.tui.register import (
    CodexRegisterOptions,
    HermesRegisterOptions,
    execute_register,
    prepare_codex_register,
    prepare_hermes_register,
)

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_SAMPLE = FIXTURES / "claude_sample.jsonl"
CLAUDE_PENDING = FIXTURES / "claude_pending.jsonl"

# Minimal schema mirroring the real Hermes state.db (see test_hermes_db.py).
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
CREATE UNIQUE INDEX idx_sessions_title_unique ON sessions(title) WHERE title IS NOT NULL;
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

# Minimal schema mirroring the real Codex state_5.sqlite (see test_codex_db.py).
_THREADS_DDL = """
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    cwd TEXT NOT NULL,
    title TEXT NOT NULL,
    sandbox_policy TEXT NOT NULL,
    approval_mode TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    has_user_event INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    cli_version TEXT NOT NULL DEFAULT '',
    first_user_message TEXT NOT NULL DEFAULT '',
    memory_mode TEXT NOT NULL DEFAULT 'enabled',
    model TEXT,
    reasoning_effort TEXT,
    created_at_ms INTEGER,
    updated_at_ms INTEGER,
    thread_source TEXT,
    preview TEXT NOT NULL DEFAULT '',
    recency_at INTEGER NOT NULL DEFAULT 0,
    recency_at_ms INTEGER NOT NULL DEFAULT 0,
    history_mode TEXT NOT NULL DEFAULT 'legacy',
    name TEXT
);
"""


def _make_hermes_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(_SESSIONS_DDL + _MESSAGES_DDL)
    conn.commit()
    conn.close()


def _make_codex_home(path):
    path.mkdir()
    conn = sqlite3.connect(path / "state_5.sqlite")
    conn.executescript(_THREADS_DDL)
    conn.commit()
    conn.close()


def _seed_codex_model(home, model, provider="openai"):
    """Add a prior thread carrying model metadata so inference has a source."""
    conn = sqlite3.connect(home / "state_5.sqlite")
    conn.execute(
        "INSERT INTO threads (id, rollout_path, created_at, updated_at, source, "
        "model_provider, cwd, title, sandbox_policy, approval_mode, model, "
        "recency_at_ms, updated_at_ms) "
        "VALUES (?, ?, 1, 1, 'cli', ?, '/tmp', 'seed', '{}', 'on-request', ?, 1, 1)",
        (str(uuid.uuid4()), "/tmp/seed-rollout.jsonl", provider, model),
    )
    conn.commit()
    conn.close()


def _hermes_opts(db, **kw):
    base = dict(source="claude-code", path=str(CLAUDE_SAMPLE), db=str(db))
    base.update(kw)
    return HermesRegisterOptions(**base)


def _codex_opts(home, cwd, **kw):
    base = dict(
        source="claude-code",
        path=str(CLAUDE_SAMPLE),
        cwd=str(cwd),
        codex_home=str(home),
    )
    base.update(kw)
    return CodexRegisterOptions(**base)


class TestPrepareHermes:
    def test_happy_plan(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db))
        assert plan.error is None
        assert plan.store == "hermes"
        assert plan.session is not None
        assert plan.session_id.startswith("sb_")
        assert plan.db_path == db
        assert "register --from" in plan.cli_command
        assert str(db) in plan.cli_command

    def test_no_handshake_injected(self, tmp_path):
        # The CLI's register path does not inject a handshake (unlike codex);
        # preserve the asymmetry.
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db))
        assert HANDSHAKE_MARKER not in plan.session.messages[0].text()

    def test_warnings_disclose_losses(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db))
        # A claude-code source into the Hermes DB is lossy (thread topology,
        # reasoning signatures, permission posture at minimum).
        assert plan.warnings

    def test_model_none_gets_routing_note(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db))
        assert any("--model" in note for note in plan.notes)

    def test_explicit_model_suppresses_note(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db, model="moonshotai/kimi-k3"))
        assert plan.notes == []
        assert plan.model == "moonshotai/kimi-k3"

    def test_missing_db_is_error_not_raise(self, tmp_path):
        plan = prepare_hermes_register(_hermes_opts(tmp_path / "nope.db"))
        assert plan.error is not None
        assert "not found" in plan.error
        assert plan.session is None

    def test_hermes_home_default_db(self, tmp_path):
        opts = HermesRegisterOptions(source="claude-code", path=str(CLAUDE_SAMPLE))
        _make_hermes_db(tmp_path / "state.db")
        plan = prepare_hermes_register(opts, hermes_home=tmp_path)
        assert plan.error is None
        assert plan.db_path == tmp_path / "state.db"

    def test_bad_session_id_is_error_not_raise(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db, session_id="../evil"))
        assert plan.error is not None
        assert "session id" in plan.error

    def test_prepare_writes_nothing(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        before = sorted(p.name for p in tmp_path.iterdir())
        prepare_hermes_register(_hermes_opts(db))
        assert sorted(p.name for p in tmp_path.iterdir()) == before


class TestExecuteHermes:
    def test_registers_into_db_with_backup(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db, title="tui reg"))
        outcome = execute_register(plan)
        assert outcome.error is None
        assert outcome.session_id == plan.session_id
        assert outcome.resume_hint == f"hermes --resume {plan.session_id}"
        assert outcome.rollout_path is None
        # session row landed
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT title FROM sessions WHERE id = ?", (plan.session_id,)
        ).fetchone()
        n_msgs = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (plan.session_id,)
        ).fetchone()[0]
        conn.close()
        assert row == ("tui reg",)
        assert n_msgs > 0
        # backup taken by default, same filename pattern as the CLI
        backups = list(tmp_path.glob("state.db.session-bridge-backup-*"))
        assert backups
        assert outcome.backup_path in backups

    def test_no_backup_skips_backup(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db, no_backup=True))
        outcome = execute_register(plan)
        assert outcome.error is None
        assert outcome.backup_path is None
        assert not list(tmp_path.glob("state.db.session-bridge-backup-*"))

    def test_duplicate_session_id_is_error_not_raise(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        first = prepare_hermes_register(_hermes_opts(db, session_id="sb_dup"))
        second = prepare_hermes_register(_hermes_opts(db, session_id="sb_dup"))
        assert execute_register(first).error is None
        outcome = execute_register(second)
        assert outcome.error is not None
        assert "already exists" in outcome.error

    def test_failed_plan_passes_through(self, tmp_path):
        plan = prepare_hermes_register(_hermes_opts(tmp_path / "nope.db"))
        outcome = execute_register(plan)
        assert outcome.error == plan.error


class TestPrepareCodex:
    def test_happy_plan_infers_model(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-5.6-luna")
        plan = prepare_codex_register(_codex_opts(home, tmp_path))
        assert plan.error is None
        assert plan.store == "codex"
        assert plan.model == "gpt-5.6-luna"
        assert plan.db_path == home / "state_5.sqlite"
        uuid.UUID(plan.session_id)  # default id is a real UUID
        assert "register-codex" in plan.cli_command
        assert "gpt-5.6-luna" in plan.cli_command

    def test_handshake_is_first_message(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-5.6-luna")
        plan = prepare_codex_register(_codex_opts(home, tmp_path))
        assert HANDSHAKE_MARKER in plan.session.messages[0].text()

    def test_explicit_model_override_wins(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-old")
        plan = prepare_codex_register(_codex_opts(home, tmp_path, model="gpt-new"))
        assert plan.error is None
        assert plan.model == "gpt-new"

    def test_no_inferable_model_is_error(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)  # empty threads table -> nothing to infer
        plan = prepare_codex_register(_codex_opts(home, tmp_path))
        assert plan.error is not None
        assert "model" in plan.error
        assert "'openai'" in plan.error
        assert str(home / "state_5.sqlite") in plan.error

    def test_invalid_store_is_error_not_raise(self, tmp_path):
        home = tmp_path / "codex"
        home.mkdir()  # no state_5.sqlite
        plan = prepare_codex_register(_codex_opts(home, tmp_path))
        assert plan.error is not None
        assert "state_5.sqlite" in plan.error

    def test_bad_session_id_is_error_not_raise(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-5.6-luna")
        plan = prepare_codex_register(
            _codex_opts(home, tmp_path, session_id="../evil")
        )
        assert plan.error is not None
        assert "session id" in plan.error


class TestExecuteCodex:
    def test_registers_rollout_and_thread_row(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-5.6-luna")
        plan = prepare_codex_register(_codex_opts(home, tmp_path, title="tui codex"))
        outcome = execute_register(plan)
        assert outcome.error is None
        assert outcome.rollout_path is not None
        assert outcome.rollout_path.is_file()
        assert plan.session_id in outcome.rollout_path.name
        assert "codex resume" in outcome.resume_hint
        assert str(tmp_path) in outcome.resume_hint
        conn = sqlite3.connect(home / "state_5.sqlite")
        row = conn.execute(
            "SELECT title, model, model_provider, rollout_path FROM threads "
            "WHERE id = ?",
            (plan.session_id,),
        ).fetchone()
        conn.close()
        assert row == (
            "tui codex",
            "gpt-5.6-luna",
            "openai",
            str(outcome.rollout_path),
        )
        # backup taken by default
        backups = list(home.glob("state_5.sqlite.session-bridge-backup-*"))
        assert backups
        assert outcome.backup_path in backups

    def test_no_backup_skips_backup(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-5.6-luna")
        plan = prepare_codex_register(_codex_opts(home, tmp_path, no_backup=True))
        outcome = execute_register(plan)
        assert outcome.error is None
        assert outcome.backup_path is None
        assert not list(home.glob("state_5.sqlite.session-bridge-backup-*"))

    def test_default_title_names_source(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-5.6-luna")
        plan = prepare_codex_register(_codex_opts(home, tmp_path))
        assert execute_register(plan).error is None
        conn = sqlite3.connect(home / "state_5.sqlite")
        title = conn.execute(
            "SELECT title FROM threads WHERE id = ?", (plan.session_id,)
        ).fetchone()[0]
        conn.close()
        assert title == "resumed from claude-code"

    def test_duplicate_session_id_is_error_not_raise(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-5.6-luna")
        session_id = str(uuid.uuid4())
        first = prepare_codex_register(_codex_opts(home, tmp_path, session_id=session_id))
        second = prepare_codex_register(_codex_opts(home, tmp_path, session_id=session_id))
        assert execute_register(first).error is None
        outcome = execute_register(second)
        assert outcome.error is not None
        assert "already exists" in outcome.error


class TestStubOpenCalls:
    def test_hermes_stub_clears_open_calls_but_warns(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(
            _hermes_opts(db, path=str(CLAUDE_PENDING), stub_open_calls=True)
        )
        assert plan.error is None
        # post-stub session has no open calls...
        assert plan.session.pending.open_tool_calls == ()
        stub = plan.session.messages[-1]
        assert any(
            b.type is BlockType.TOOL_RESULT
            and b.is_error
            and b.text == INTERRUPTED_RESULT_TEXT
            for b in stub.content
        )
        # ...while the warnings still disclose them (report is pre-stub)
        assert any("no matching result" in w for w in plan.warnings)

    def test_codex_stub_clears_open_calls_but_warns(self, tmp_path):
        home = tmp_path / "codex"
        _make_codex_home(home)
        _seed_codex_model(home, "gpt-5.6-luna")
        plan = prepare_codex_register(
            _codex_opts(home, tmp_path, path=str(CLAUDE_PENDING), stub_open_calls=True)
        )
        assert plan.error is None
        assert plan.session.pending.open_tool_calls == ()
        # handshake still first, stub result last
        assert HANDSHAKE_MARKER in plan.session.messages[0].text()
        assert any(
            b.type is BlockType.TOOL_RESULT and b.text == INTERRUPTED_RESULT_TEXT
            for b in plan.session.messages[-1].content
        )
        assert any("no matching result" in w for w in plan.warnings)

    def test_without_stub_open_calls_survive_in_plan(self, tmp_path):
        db = tmp_path / "state.db"
        _make_hermes_db(db)
        plan = prepare_hermes_register(_hermes_opts(db, path=str(CLAUDE_PENDING)))
        assert plan.error is None
        assert plan.session.pending.open_tool_calls
        assert any("no matching result" in w for w in plan.warnings)


# ---- review-round fixes (register slice) ----


def test_prepare_codex_unresolvable_home_returns_error_not_raise(tmp_path):
    # Path("~nosuchuser").expanduser() raises bare RuntimeError; the
    # never-raise contract must convert it into plan.error.
    opts = CodexRegisterOptions(
        source="claude-code",
        path=str(FIXTURES / "claude_sample.jsonl"),
        cwd=str(tmp_path),
        codex_home="~nonexistent_user_xyz/codex",
    )
    plan = prepare_codex_register(opts)
    assert plan.error is not None


def test_prepare_codex_rejects_non_uuid_id_at_plan_time(tmp_path):
    home = tmp_path / ".codex"
    _make_codex_home(home)
    _seed_codex_model(home, "gpt-5.2")
    opts = CodexRegisterOptions(
        source="claude-code",
        path=str(FIXTURES / "claude_sample.jsonl"),
        cwd=str(tmp_path),
        codex_home=str(home),
        session_id="sb_1753600000_ab12cd",  # charset-valid but not a UUID
    )
    plan = prepare_codex_register(opts)
    assert plan.error is not None and "UUID" in plan.error
    # The knowable-bad id must fail BEFORE execute, so no backup is created.
    outcome = execute_register(plan)
    assert outcome.error is not None
    assert not list(home.glob("state_5.sqlite.session-bridge-backup-*"))


def test_prepare_codex_home_override_kwarg_fills_blank_field(tmp_path):
    # Blanking the form's codex-home field must fall back to the app-level
    # isolated-store override, not escape to the real ~/.codex.
    home = tmp_path / ".codex"
    _make_codex_home(home)
    _seed_codex_model(home, "gpt-5.2")
    opts = CodexRegisterOptions(
        source="claude-code",
        path=str(FIXTURES / "claude_sample.jsonl"),
        cwd=str(tmp_path),
        codex_home=None,
    )
    plan = prepare_codex_register(opts, codex_home=home)
    assert plan.error is None
    assert plan.db_path == home / "state_5.sqlite"


def test_execute_errors_when_store_vanished_after_plan(tmp_path):
    db = tmp_path / "state.db"
    _make_hermes_db(db)
    opts = HermesRegisterOptions(
        source="claude-code",
        path=str(FIXTURES / "claude_sample.jsonl"),
        db=str(db),
    )
    plan = prepare_hermes_register(opts)
    assert plan.error is None
    db.unlink()
    outcome = execute_register(plan)
    assert outcome.error is not None and "no longer exists" in outcome.error
    # The guard must run before any sqlite3.connect recreates the store,
    # and no backup file may be left behind.
    assert not db.exists()
    assert not list(tmp_path.glob("state.db.session-bridge-backup-*"))
    assert outcome.backup_path is None


def test_prepare_codex_plan_leaves_store_bytes_untouched(tmp_path):
    # The plan phase must be strictly read-only on the live store.
    home = tmp_path / ".codex"
    _make_codex_home(home)
    _seed_codex_model(home, "gpt-5.2")
    before = (home / "state_5.sqlite").read_bytes()
    opts = CodexRegisterOptions(
        source="claude-code",
        path=str(FIXTURES / "claude_sample.jsonl"),
        cwd=str(tmp_path),
        codex_home=str(home),
    )
    plan = prepare_codex_register(opts)
    assert plan.error is None
    assert (home / "state_5.sqlite").read_bytes() == before
