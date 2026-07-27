import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from session_bridge.ir import ContentBlock, Message, Role, Session, SessionMeta
from session_bridge.readers.codex import read_codex
from session_bridge.writers.codex_db import CodexRegistrationError, register_codex_session


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


def _make_codex_home(path):
    path.mkdir()
    conn = sqlite3.connect(path / "state_5.sqlite")
    conn.executescript(_THREADS_DDL)
    conn.commit()
    conn.close()


def _sample_session():
    return Session(
        meta=SessionMeta(
            source_harness="hermes",
            model="gpt-5.6-luna",
            model_provider="openai",
        ),
        messages=(
            Message(role=Role.USER, content=(ContentBlock.text_block("remember CEDAR"),)),
            Message(role=Role.ASSISTANT, content=(ContentBlock.text_block("CEDAR recorded."),)),
        ),
    )


def test_registers_thread_and_indexed_rollout(tmp_path):
    home = tmp_path / "codex"
    _make_codex_home(home)
    session_id = str(uuid.uuid4())

    rollout = register_codex_session(
        _sample_session(),
        home,
        session_id,
        cwd=str(tmp_path),
        title="imported CEDAR session",
        started_at=1_700_000_000.0,
    )

    assert rollout.is_file()
    assert session_id in rollout.name
    header = json.loads(rollout.read_text(encoding="utf-8").splitlines()[0])
    assert header["payload"]["cli_version"] == "0.145.0"
    parsed = read_codex(rollout)
    assert parsed.meta.session_id == session_id
    assert parsed.meta.cwd == str(tmp_path.resolve())
    assert [message.text() for message in parsed.messages] == [
        "remember CEDAR",
        "CEDAR recorded.",
    ]

    conn = sqlite3.connect(home / "state_5.sqlite")
    row = conn.execute(
        "SELECT rollout_path, cwd, title, model, has_user_event, preview "
        "FROM threads WHERE id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    assert row == (
        str(rollout),
        str(tmp_path.resolve()),
        "imported CEDAR session",
        "gpt-5.6-luna",
        1,
        "remember CEDAR",
    )

    with sqlite3.connect(home / "state_5.sqlite") as policy_conn:
        thread_policy = json.loads(
            policy_conn.execute(
                "SELECT sandbox_policy FROM threads WHERE id = ?", (session_id,)
            ).fetchone()[0]
        )
    turn_context = next(
        json.loads(line)["payload"]
        for line in rollout.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["type"] == "turn_context"
    )
    assert thread_policy["type"] == "managed"
    assert thread_policy["network"] == "restricted"
    assert turn_context["approval_policy"] == "on-request"
    assert turn_context["sandbox_policy"]["type"] == "workspace-write"
    assert turn_context["file_system_sandbox_policy"] == thread_policy["file_system"]


def test_cross_provider_registration_uses_target_model_metadata(tmp_path):
    home = tmp_path / "codex"
    _make_codex_home(home)
    source = Session(
        meta=SessionMeta(
            source_harness="claude-code",
            model="claude-sonnet-5",
            model_provider="anthropic",
        ),
        messages=(Message(role=Role.USER, content=(ContentBlock.text_block("remember LARCH"),)),),
    )
    session_id = str(uuid.uuid4())

    rollout = register_codex_session(
        source,
        home,
        session_id,
        cwd=str(tmp_path),
        title="imported LARCH session",
        model="gpt-5.6-luna",
    )

    records = [json.loads(line) for line in rollout.read_text(encoding="utf-8").splitlines()]
    assert records[0]["payload"]["model_provider"] == "openai"
    assert records[1]["payload"]["model"] == "gpt-5.6-luna"
    with sqlite3.connect(home / "state_5.sqlite") as conn:
        assert conn.execute(
            "SELECT model_provider, model FROM threads WHERE id = ?", (session_id,)
        ).fetchone() == ("openai", "gpt-5.6-luna")


def test_rejects_non_codex_db_without_creating_a_rollout(tmp_path):
    home = tmp_path / "codex"
    home.mkdir()
    sqlite3.connect(home / "state_5.sqlite").close()

    with pytest.raises(CodexRegistrationError, match="missing table: threads"):
        register_codex_session(
            _sample_session(), home, str(uuid.uuid4()), cwd=str(tmp_path), title="test"
        )
    assert not (home / "sessions").exists()


def test_rejects_non_uuid_session_id(tmp_path):
    home = tmp_path / "codex"
    _make_codex_home(home)

    with pytest.raises(CodexRegistrationError, match="must be a UUID"):
        register_codex_session(
            _sample_session(), home, "safe-but-not-a-uuid", cwd=str(tmp_path), title="test"
        )


def test_rejects_missing_target_cwd_before_writing(tmp_path):
    home = tmp_path / "codex"
    _make_codex_home(home)

    with pytest.raises(CodexRegistrationError, match="cwd does not exist"):
        register_codex_session(
            _sample_session(),
            home,
            str(uuid.uuid4()),
            cwd=str(tmp_path / "not-here"),
            title="test",
        )
    assert not (home / "sessions").exists()


def test_index_failure_removes_new_rollout(tmp_path):
    home = tmp_path / "codex"
    _make_codex_home(home)
    conn = sqlite3.connect(home / "state_5.sqlite")
    conn.execute(
        "CREATE TRIGGER reject_thread BEFORE INSERT ON threads "
        "BEGIN SELECT RAISE(ABORT, 'intentional test failure'); END"
    )
    conn.commit()
    conn.close()

    with pytest.raises(CodexRegistrationError, match="intentional test failure"):
        register_codex_session(
            _sample_session(), home, str(uuid.uuid4()), cwd=str(tmp_path), title="test"
        )
    assert not list((home / "sessions").rglob("*.jsonl"))


def test_concurrent_same_id_keeps_winner_rollout(tmp_path):
    home = tmp_path / "codex"
    _make_codex_home(home)
    session_id = str(uuid.uuid4())

    def register():
        return register_codex_session(
            _sample_session(),
            home,
            session_id,
            cwd=str(tmp_path),
            title="concurrent registration",
            started_at=1_700_000_000.0,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(register) for _ in range(2)]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except CodexRegistrationError as exc:
            outcomes.append(exc)

    rollouts = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
    assert len(rollouts) == 1
    assert rollouts[0].is_file()
    with sqlite3.connect(home / "state_5.sqlite") as conn:
        indexed = conn.execute(
            "SELECT rollout_path FROM threads WHERE id = ?", (session_id,)
        ).fetchone()[0]
    assert indexed == str(rollouts[0])
    assert Path(indexed).is_file()


def test_cli_register_codex_backs_up_and_adds_handshake(tmp_path):
    from session_bridge.cli import main

    home = tmp_path / "codex"
    _make_codex_home(home)
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps(
            {
                "parentUuid": None,
                "type": "user",
                "message": {"role": "user", "content": "remember MAPLE"},
                "uuid": "u1",
                "sessionId": "original",
                "cwd": str(tmp_path),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    session_id = str(uuid.uuid4())

    rc = main(
        [
            "register-codex",
            "--from",
            "claude-code",
            str(source),
            "--codex-home",
            str(home),
            "--cwd",
            str(tmp_path),
            "--title",
            "imported MAPLE session",
            "--model",
            "gpt-5.6-luna",
            "--session-id",
            session_id,
        ]
    )
    assert rc == 0
    assert list(home.glob("state_5.sqlite.session-bridge-backup-*"))

    conn = sqlite3.connect(home / "state_5.sqlite")
    rollout_path = conn.execute(
        "SELECT rollout_path FROM threads WHERE id = ?", (session_id,)
    ).fetchone()[0]
    conn.close()
    parsed = read_codex(rollout_path)
    assert "resume handshake" in parsed.messages[0].text().lower()

    second_id = str(uuid.uuid4())
    assert main(
        [
            "register-codex",
            "--from",
            "claude-code",
            str(source),
            "--codex-home",
            str(home),
            "--cwd",
            str(tmp_path),
            "--model",
            "gpt-5.6-luna",
            "--session-id",
            second_id,
        ]
    ) == 0
    assert len(list(home.glob("state_5.sqlite.session-bridge-backup-*"))) == 2
