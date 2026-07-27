"""Tests for TUI session discovery across the three harness stores.

Fake stores are built under tmp_path by copying the committed fixtures into
each harness's real on-disk layout; no real home directories are touched.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from session_bridge.tui.discovery import (
    SessionEntry,
    discover_sessions,
    scan_claude_code,
    scan_codex,
    scan_hermes,
)

FIXTURES = Path(__file__).parent / "fixtures"


def make_claude_home(tmp_path: Path) -> Path:
    home = tmp_path / ".claude"
    project = home / "projects" / "-Users-x-proj"
    project.mkdir(parents=True)
    shutil.copy(FIXTURES / "claude_sample.jsonl", project / "aaaa-1111.jsonl")
    return home


def make_codex_home(tmp_path: Path) -> Path:
    home = tmp_path / ".codex"
    day = home / "sessions" / "2026" / "07" / "18"
    day.mkdir(parents=True)
    shutil.copy(FIXTURES / "codex_sample.jsonl", day / "rollout-2026-07-18-cx-1.jsonl")
    return home


def make_hermes_home(tmp_path: Path) -> Path:
    home = tmp_path / ".hermes"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    shutil.copy(FIXTURES / "hermes_sample.jsonl", sessions / "20260417_hx-1.jsonl")
    return home


def test_scan_claude_code(tmp_path):
    entries = scan_claude_code(make_claude_home(tmp_path))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.harness == "claude-code"
    assert entry.session_id == "aaaa-1111"
    # cwd must come from the records, not the dashed directory name.
    assert entry.cwd == "/Users/x/proj"
    assert entry.preview == "search for TODO comments"
    assert entry.size == (FIXTURES / "claude_sample.jsonl").stat().st_size
    assert entry.mtime == entry.path.stat().st_mtime


def test_scan_codex(tmp_path):
    entries = scan_codex(make_codex_home(tmp_path))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.harness == "codex"
    assert entry.session_id == "cx-1"
    assert entry.cwd == "/Users/x/dev"
    assert entry.preview == "list the python files"


def test_scan_hermes(tmp_path):
    entries = scan_hermes(make_hermes_home(tmp_path))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.harness == "hermes"
    assert entry.session_id == "20260417_hx-1"
    assert entry.cwd is None
    assert entry.preview == "find my past work on cron jobs"


def test_hermes_session_id_is_full_stem(tmp_path):
    # The real Hermes id is the whole <date>_<time>_<hex> stem (it's what
    # state.db sessions.id holds and what `hermes --resume` expects).
    home = tmp_path / ".hermes"
    (home / "sessions").mkdir(parents=True)
    shutil.copy(
        FIXTURES / "hermes_sample.jsonl",
        home / "sessions" / "20260416_004124_10f12c82.jsonl",
    )
    entries = scan_hermes(home)
    assert entries[0].session_id == "20260416_004124_10f12c82"


def test_discover_sessions_sorted_mtime_desc(tmp_path):
    claude_home = make_claude_home(tmp_path)
    codex_home = make_codex_home(tmp_path)
    hermes_home = make_hermes_home(tmp_path)
    # Force distinct, known mtimes: hermes newest, codex middle, claude oldest.
    claude_file = next(claude_home.glob("projects/*/*.jsonl"))
    codex_file = next(codex_home.glob("sessions/*/*/*/rollout-*.jsonl"))
    hermes_file = next(hermes_home.glob("sessions/*.jsonl"))
    os.utime(claude_file, (1000, 1000))
    os.utime(codex_file, (2000, 2000))
    os.utime(hermes_file, (3000, 3000))
    entries = discover_sessions(
        claude_home=claude_home, codex_home=codex_home, hermes_home=hermes_home
    )
    assert [e.harness for e in entries] == ["hermes", "codex", "claude-code"]
    assert [e.mtime for e in entries] == [3000, 2000, 1000]


def test_missing_home_dirs_return_empty(tmp_path):
    missing = tmp_path / "nope"
    assert scan_claude_code(missing) == []
    assert scan_codex(missing) == []
    assert scan_hermes(missing) == []
    assert (
        discover_sessions(claude_home=missing, codex_home=missing, hermes_home=missing)
        == []
    )


def test_garbage_and_empty_files_are_skipped_or_harmless(tmp_path):
    claude_home = make_claude_home(tmp_path)
    project = next(claude_home.glob("projects/*"))
    (project / "garbage.jsonl").write_bytes(b"\xff\xfe\x00garbage{{{not json\n\xba\xad")
    (project / "empty.jsonl").write_bytes(b"")
    entries = scan_claude_code(claude_home)
    # No exception; the good fixture session is still discovered.
    good = [e for e in entries if e.session_id == "aaaa-1111"]
    assert len(good) == 1
    # Files with no parseable head records yield no cwd/preview.
    for entry in entries:
        if entry.session_id in ("garbage", "empty"):
            assert entry.cwd is None and entry.preview is None


def test_preview_truncation(tmp_path):
    home = tmp_path / ".hermes"
    (home / "sessions").mkdir(parents=True)
    long_text = "x" * 500
    records = [
        {"role": "session_meta", "model": "m", "platform": "hermes"},
        {"role": "user", "content": long_text},
    ]
    (home / "sessions" / "20260101_long-1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )
    (entry,) = scan_hermes(home)
    assert entry.preview is not None
    assert len(entry.preview) <= 120
    assert entry.preview.startswith("xxx")


def test_claude_preview_joins_text_blocks(tmp_path):
    home = tmp_path / ".claude"
    project = home / "projects" / "-Users-x-proj"
    project.mkdir(parents=True)
    records = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "first part"},
                    {"type": "image", "source": {"data": "zzz"}},
                    {"type": "text", "text": "second part"},
                ],
            },
            "cwd": "/Users/x/proj",
        },
    ]
    (project / "blocky.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )
    (entry,) = scan_claude_code(home)
    assert entry.preview == "first part\nsecond part"


def test_session_entry_is_frozen(tmp_path):
    entries = scan_hermes(make_hermes_home(tmp_path))
    with pytest.raises(AttributeError):
        entries[0].harness = "codex"


def test_entry_type(tmp_path):
    entries = discover_sessions(
        claude_home=make_claude_home(tmp_path),
        codex_home=tmp_path / "no-codex",
        hermes_home=tmp_path / "no-hermes",
    )
    assert all(isinstance(e, SessionEntry) for e in entries)
