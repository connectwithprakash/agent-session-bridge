"""Headless end-to-end walk of the TUI wizard via textual's Pilot.

Skipped entirely when the optional textual dependency is absent (the pure
modules have their own textual-free tests). Async app driving happens through
``asyncio.run`` inside sync tests so no pytest async plugin is needed.
"""

import asyncio
import os
import shutil
import sqlite3
import time
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
    TranscriptScreen,
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


async def _settle(pilot, app, screen_cls, ready=None, timeout: float = 10.0) -> None:
    """Wait until the app lands on ``screen_cls`` (and ``ready()`` holds)
    instead of racing a fixed pause.

    Fixed pauses flake on slow CI runners (discovery and registration do real
    filesystem/SQLite work in workers); polling keeps the fast case fast and
    the slow case green. ``ready`` guards state that appears after the screen
    itself, e.g. the picker's worker-populated rows.
    """
    def _ok() -> bool:
        if not isinstance(app.screen, screen_cls):
            return False
        return ready() if ready is not None else True

    waited = 0.0
    while not _ok() and waited < timeout:
        await pilot.pause(0.1)
        waited += 0.1
    assert isinstance(app.screen, screen_cls), (
        f"expected {screen_cls.__name__}, on {type(app.screen).__name__} after {timeout}s"
    )
    assert _ok(), f"screen {screen_cls.__name__} present but ready() never held"


def _rows(app, n: int):
    """ready-predicate: the picker's DataTable has been populated with n rows."""
    from textual.widgets import DataTable as _DT

    return lambda: app.screen.query_one(_DT).row_count >= n


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
    for sid, content in (
        ("20260801_000001_dbaaa1", "db hello"),
        # Markup-hostile content real cron sessions carry: rich.escape leaves
        # "[IMPORTANT:" alone and textual's parser then rejects it.
        ("20260801_000002_dbaaa2", "[IMPORTANT: cron job [/] do not [b]break"),
    ):
        conn.execute(
            "INSERT INTO sessions (id, source, model, started_at) VALUES (?, 'cli', 'm', 50.0)",
            (sid,),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, 'user', ?, 51.0)",
            (sid, content),
        )
    conn.commit()
    conn.close()
    # The claude entry is the newest so it sits on row 0: the register flow
    # test selects it and can still target the hermes store (the source
    # harness is filtered out of register targets).
    now = time.time()
    os.utime(proj / "aaaa-1111.jsonl", (now + 5, now + 5))
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
            await _settle(pilot, app, PickerScreen, ready=_rows(app, 4))
            table = app.screen.query_one(DataTable)
            assert table.row_count == 4  # 1 file claude + 1 file hermes + 2 db hermes

            table.focus()
            await pilot.press("enter")
            await _settle(pilot, app, SummaryScreen)
            assert app.screen.session is not None
            assert "source harness" in str(
                app.screen.query_one("#summary-body", Static).render()
            )

            await pilot.press("c")
            await _settle(pilot, app, OptionsScreen)
            opts_screen = app.screen
            opts_screen.query_one("#output").value = str(out_dir / "converted.jsonl")
            # Row 0 is a claude-code source, so the default target is codex
            # and the placement group starts hidden.
            assert opts_screen.query_one("#place-group").display is False
            opts_screen.query_one("#target", Select).value = "claude-code"
            await pilot.pause(0.2)
            assert opts_screen.query_one("#place-group").display is True
            opts_screen.query_one("#output").value = str(out_dir / "converted.jsonl")

            # Placement enabled with a blank cwd must be a form error.
            opts_screen.query_one("#place", Switch).value = True
            opts_screen.query_one("#place-cwd").value = ""
            opts_screen.query_one("#continue", Button).press()
            # invalid form: same screen, the error text appears asynchronously
            await _settle(
                pilot, app, OptionsScreen,
                ready=lambda: str(opts_screen.query_one("#form-errors", Static).render()) != "",
            )
            assert "placement is enabled but no project cwd" in str(
                opts_screen.query_one("#form-errors", Static).render()
            )
            opts_screen.query_one("#place", Switch).value = False

            opts_screen.query_one("#continue", Button).press()
            await _settle(pilot, app, DryRunScreen)
            assert app.screen.result is not None
            assert "session-bridge convert" in str(
                app.screen.query_one("#dryrun-body", Static).render()
            )
            assert not (out_dir / "converted.jsonl").exists(), "dry run wrote!"

            app.screen.query_one("#write", Button).press()
            await _settle(pilot, app, ResultScreen)
            assert app.screen.outcome.error is None
            assert (out_dir / "converted.jsonl").exists()
            # This flow targets claude-code without placement, so the result
            # screen must warn that the file alone is not resumable.
            body = str(app.screen.query_one("#result-body", Static).render())
            assert "heads up" in body and "Enable placement" in body

            await pilot.press("n")
            await _settle(pilot, app, PickerScreen, ready=_rows(app, 4))
            # Cursor through every row: the detail pane must survive
            # markup-hostile previews and duplicate-path db sessions.
            table = app.screen.query_one(DataTable)
            table.focus()
            for _ in range(table.row_count):
                await pilot.press("down")
            await _settle(pilot, app, PickerScreen, ready=_rows(app, 4))

    asyncio.run(drive())


def test_register_flow_hermes_end_to_end(tmp_path):
    app = _app(tmp_path)
    # _make_stores already created state.db with two db-only sessions.
    hermes_db = tmp_path / ".hermes" / "state.db"

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(pilot, app, PickerScreen, ready=_rows(app, 4))
            table = app.screen.query_one(DataTable)
            table.focus()
            await pilot.press("enter")
            await _settle(pilot, app, SummaryScreen)

            await pilot.press("g")
            await _settle(pilot, app, RegisterFormScreen)
            assert str(app.screen.query_one("#store", Select).value) == "hermes"
            # A claude-code source can target both stores; the note points
            # Claude Code seekers at Convert-with-placement instead.
            store_values = {v for _, v in app.screen.query_one("#store", Select)._options}
            assert store_values == {"hermes", "codex"}
            note = str(app.screen.query_one("#register-note", Static).render())
            assert "Claude Code has no store" in note
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
            await _settle(pilot, app, RegisterResultScreen)
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


def test_register_targets_exclude_source_harness(tmp_path):
    """A hermes-source session must not offer hermes as a register target
    (it would duplicate the session in its own store)."""
    app = _app(tmp_path)

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(pilot, app, PickerScreen, ready=_rows(app, 4))
            table = app.screen.query_one(DataTable)
            table.focus()
            await pilot.press("down")  # row 1: the hermes file session
            await pilot.press("enter")
            await _settle(pilot, app, SummaryScreen)
            assert app.screen.entry.harness == "hermes"
            await pilot.press("g")
            await _settle(pilot, app, RegisterFormScreen)
            store_values = {v for _, v in app.screen.query_one("#store", Select)._options}
            assert store_values == {"codex"}

    asyncio.run(drive())


def test_summary_shows_store_session_id_for_hermes(tmp_path):
    """Hermes transcripts carry no id in-band; the summary falls back to the
    store's id instead of showing None."""
    app = _app(tmp_path)

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(pilot, app, PickerScreen, ready=_rows(app, 4))
            table = app.screen.query_one(DataTable)
            table.focus()
            await pilot.press("down")
            await pilot.press("enter")
            await _settle(pilot, app, SummaryScreen)
            body = str(app.screen.query_one("#summary-body", Static).render())
            assert "20260417_hx-1 (from store)" in body

    asyncio.run(drive())


def test_transcript_viewer_from_summary(tmp_path):
    """`v` on the summary opens the full conversation: both roles, reasoning,
    tool calls, and tool results are all rendered."""
    app = _app(tmp_path)

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(pilot, app, PickerScreen, ready=_rows(app, 4))
            table = app.screen.query_one(DataTable)
            table.focus()
            await pilot.press("enter")  # row 0: the claude session
            await _settle(pilot, app, SummaryScreen)
            await pilot.press("v")
            await _settle(pilot, app, TranscriptScreen)
            body = str(app.screen.query_one("#transcript-body", Static).render())
            assert "search for TODO comments" in body
            assert "thinking · I'll grep for TODO." in body
            assert "→ Grep" in body
            assert "found 3 TODOs" in body
            await pilot.press("escape")
            assert isinstance(app.screen, SummaryScreen)

    asyncio.run(drive())


def test_transcript_viewer_survives_markup_hostile_db_session(tmp_path):
    """The viewer renders db-backed sessions whose content is textual-markup
    poison (the class of input that crashed the picker before escape())."""
    app = _app(tmp_path)

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            picker = app.screen
            table = picker.query_one(DataTable)
            table.focus()
            idx = next(
                i
                for i, e in enumerate(picker.entries)
                if e.session_id == "20260801_000002_dbaaa2"
            )
            for _ in range(idx):
                await pilot.press("down")
            await pilot.press("enter")
            await _settle(pilot, app, SummaryScreen)
            await pilot.press("v")
            await _settle(pilot, app, TranscriptScreen)
            body = str(app.screen.query_one("#transcript-body", Static).render())
            assert "IMPORTANT: cron job" in body

    asyncio.run(drive())


def test_transcript_markup_truncates_huge_tool_results():
    """Prose is never cut; tool results beyond the preview cap disclose how
    much was held back instead of flooding the view."""
    from session_bridge.ir import (
        ContentBlock,
        Message,
        Role,
        Session,
        SessionMeta,
    )
    from session_bridge.tui.screens import _transcript_markup

    session = Session(
        meta=SessionMeta(source_harness="claude-code"),
        messages=(
            Message(
                role=Role.ASSISTANT,
                content=(ContentBlock.tool_call("c1", "Bash", {"command": "cat big"}),),
                timestamp="2026-08-02T21:00:00.000Z",
            ),
            Message(
                role=Role.TOOL,
                content=(ContentBlock.tool_result("c1", "x" * 5000),),
            ),
        ),
    )
    markup = _transcript_markup(session)
    assert "→ Bash" in markup
    assert "2026-08-02 21:00:00" in markup
    assert "(+3000 more chars)" in markup
    assert "x" * 2001 not in markup
