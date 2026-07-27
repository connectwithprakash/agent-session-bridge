"""Parity between tui.summary.summarize_session and the `inspect` CLI command.

Rather than duplicating expected values, these tests run cmd_inspect on the
same fixture and assert every summary value appears in its stdout — so the two
surfaces cannot drift apart without a test failure.
"""

from pathlib import Path

from session_bridge.cli import main
from session_bridge.convert import read_session
from session_bridge.tui.summary import summarize_session

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_LABELS = [
    "source harness",
    "session id",
    "model",
    "cwd",
    "permission",
    "messages",
    "text blocks",
    "reasoning",
    "tool calls",
    "tool results",
    "tool schemas",
    "open tool calls",
    "queued user input",
    "active goal",
]


def _assert_parity_with_inspect(fixture: Path, capsys) -> list[tuple[str, str]]:
    session = read_session("claude-code", str(fixture))
    rows = summarize_session(session)

    rc = main(["inspect", "--from", "claude-code", str(fixture)])
    assert rc == 0
    out = capsys.readouterr().out

    assert [label for label, _ in rows] == EXPECTED_LABELS
    for label, value in rows:
        assert isinstance(value, str)
        assert value in out, f"{label!r} value {value!r} missing from inspect output"
    return rows


def test_summary_matches_inspect_sample(capsys):
    _assert_parity_with_inspect(FIXTURES / "claude_sample.jsonl", capsys)


def test_summary_matches_inspect_pending(capsys):
    rows = _assert_parity_with_inspect(FIXTURES / "claude_pending.jsonl", capsys)
    by_label = dict(rows)
    assert by_label["open tool calls"] != "[]"


def test_all_values_are_strings():
    session = read_session("claude-code", str(FIXTURES / "claude_sample.jsonl"))
    for label, value in summarize_session(session):
        assert isinstance(label, str) and isinstance(value, str)
