"""Headless end-to-end walk of the TUI wizard via textual's Pilot.

Skipped entirely when the optional textual dependency is absent (the pure
modules have their own textual-free tests). Async app driving happens through
``asyncio.run`` inside sync tests so no pytest async plugin is needed.
"""

import asyncio
import shutil
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import Button, DataTable, Select, Static, Switch  # noqa: E402

from session_bridge.tui.app import SessionBridgeApp  # noqa: E402
from session_bridge.tui.screens import (  # noqa: E402
    DryRunScreen,
    OptionsScreen,
    PickerScreen,
    RegisterFormScreen,
    RegisterPlanScreen,
    RegisterResultScreen,
    ResultScreen,
    SummaryScreen,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Mirrors tests/test_hermes_db.py's minimal real-schema DDL.
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


def _make_stores(tmp_path: Path) -> tuple[Path, Path, Path]:
    claude_home = tmp_path / ".claude"
    proj = claude_home / "projects" / "-Users-x-proj"
    proj.mkdir(parents=True)
    shutil.copy(FIXTURES / "claude_sample.jsonl", proj / "aaaa-1111.jsonl")
    hermes_home = tmp_path / ".hermes"
    (hermes_home / "sessions").mkdir(parents=True)
    shutil.copy(
        FIXTURES / "hermes_sample.jsonl",
        hermes_home / "sessions" / "20260417_hx-1.jsonl",
    )
    # TWO db-only sessions: they share the state.db path, which crashed the
    # picker's row keying (DuplicateKey) when keys were path-based.
    conn = sqlite3.connect(hermes_home / "state.db")
    conn.executescript(_SESSIONS_DDL + _MESSAGES_DDL)
    for sid in ("20260801_000001_dbaaa1", "20260801_000002_dbaaa2"):
        conn.execute(
            "INSERT INTO sessions (id, source, model, started_at) VALUES (?, 'cli', 'm', 50.0)",
            (sid,),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, 'user', 'db hello', 51.0)",
            (sid,),
        )
    conn.commit()
    conn.close()
    codex_home = tmp_path / ".codex"  # intentionally absent -> scans to []
    return claude_home, codex_home, hermes_home


def _app(tmp_path: Path) -> SessionBridgeApp:
    claude_home, codex_home, hermes_home = _make_stores(tmp_path)
    return SessionBridgeApp(
        claude_home=claude_home, codex_home=codex_home, hermes_home=hermes_home
    )


def test_convert_flow_end_to_end(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    app = _app(tmp_path)

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            assert isinstance(app.screen, PickerScreen)
            table = app.screen.query_one(DataTable)
            assert table.row_count == 4  # 1 file claude + 1 file hermes + 2 db hermes

            table.focus()
            await pilot.press("enter")
            await pilot.pause(0.5)
            assert isinstance(app.screen, SummaryScreen)
            assert app.screen.session is not None
            assert "source harness" in str(
                app.screen.query_one("#summary-body", Static).render()
            )

            await pilot.press("c")
            await pilot.pause(0.2)
            assert isinstance(app.screen, OptionsScreen)
            opts_screen = app.screen
            opts_screen.query_one("#output").value = str(out_dir / "converted.jsonl")
            target = opts_screen.query_one("#target", Select).value
            assert opts_screen.query_one("#place-group").display == (
                target == "claude-code"
            )

            # Placement enabled with a blank cwd must be a form error.
            opts_screen.query_one("#place", Switch).value = True
            opts_screen.query_one("#place-cwd").value = ""
            opts_screen.query_one("#continue", Button).press()
            await pilot.pause(0.2)
            assert isinstance(app.screen, OptionsScreen)
            assert "placement is enabled but no project cwd" in str(
                opts_screen.query_one("#form-errors", Static).render()
            )
            opts_screen.query_one("#place", Switch).value = False

            opts_screen.query_one("#continue", Button).press()
            await pilot.pause(0.5)
            assert isinstance(app.screen, DryRunScreen)
            assert app.screen.result is not None
            assert "session-bridge convert" in str(
                app.screen.query_one("#dryrun-body", Static).render()
            )
            assert not (out_dir / "converted.jsonl").exists(), "dry run wrote!"

            app.screen.query_one("#write", Button).press()
            await pilot.pause(0.5)
            assert isinstance(app.screen, ResultScreen)
            assert app.screen.outcome.error is None
            assert (out_dir / "converted.jsonl").exists()
            # This flow targets claude-code without placement, so the result
            # screen must warn that the file alone is not resumable.
            body = str(app.screen.query_one("#result-body", Static).render())
            assert "heads up" in body and "Enable placement" in body

            await pilot.press("n")
            await pilot.pause(0.2)
            assert isinstance(app.screen, PickerScreen)

    asyncio.run(drive())


def test_register_flow_hermes_end_to_end(tmp_path):
    app = _app(tmp_path)
    # _make_stores already created state.db with two db-only sessions.
    hermes_db = tmp_path / ".hermes" / "state.db"

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            table = app.screen.query_one(DataTable)
            table.focus()
            await pilot.press("enter")
            await pilot.pause(0.5)
            assert isinstance(app.screen, SummaryScreen)

            await pilot.press("g")
            await pilot.pause(0.2)
            assert isinstance(app.screen, RegisterFormScreen)
            assert str(app.screen.query_one("#store", Select).value) == "hermes"
            # hermes-db left blank -> resolves via the app's hermes_home override
            app.screen.query_one("#reg-continue", Button).press()
            await pilot.pause(0.5)

            assert isinstance(app.screen, RegisterPlanScreen)
            plan = app.screen.plan
            assert plan is not None and plan.error is None
            assert "session-bridge register" in str(
                app.screen.query_one("#plan-body", Static).render()
            )
            n = sqlite3.connect(hermes_db).execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()[0]
            assert n == 2, "plan phase mutated the store (2 pre-seeded db sessions)"

            app.screen.query_one("#register", Button).press()
            await pilot.pause(0.7)
            assert isinstance(app.screen, RegisterResultScreen)
            outcome = app.screen.outcome
            assert outcome.error is None
            assert outcome.backup_path is not None
            rows = {
                r[0]
                for r in sqlite3.connect(hermes_db)
                .execute("SELECT id FROM sessions")
                .fetchall()
            }
            assert len(rows) == 3  # 2 pre-seeded db sessions + the registration
            assert outcome.session_id in rows

    asyncio.run(drive())
