"""Tests for the TUI actions layer: pure conversion, then explicit writes."""

import json
from pathlib import Path

from session_bridge.tui.actions import WriteOutcome, execute_writes, run_conversion
from session_bridge.tui.options import ConvertOptions

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_SAMPLE = FIXTURES / "claude_sample.jsonl"

# The codex writer's placeholder date, used when no real timestamp is passed.
CODEX_PLACEHOLDER_TS = "2000-01-01T00:00:00.000Z"


def _opts(**kw):
    base = dict(source="claude-code", target="hermes", path=str(CLAUDE_SAMPLE))
    base.update(kw)
    return ConvertOptions(**base)


class TestRunConversion:
    def test_pure_no_files_created(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = run_conversion(_opts())
        assert result.records
        assert result.report is not None
        assert list(tmp_path.iterdir()) == []

    def test_codex_target_gets_real_timestamp(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = run_conversion(_opts(target="codex"))
        meta = next(r for r in result.records if r.get("type") == "session_meta")
        assert meta["timestamp"] != CODEX_PLACEHOLDER_TS
        assert meta["payload"]["timestamp"] != CODEX_PLACEHOLDER_TS
        assert list(tmp_path.iterdir()) == []

    def test_no_handshake_respected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with_hs = run_conversion(_opts())
        without_hs = run_conversion(_opts(no_handshake=True))
        assert len(without_hs.records) < len(with_hs.records)


class TestExecuteWrites:
    def test_writes_output_jsonl(self, tmp_path):
        out = tmp_path / "out.jsonl"
        opts = _opts(output=str(out))
        outcome = execute_writes(run_conversion(opts), opts)
        assert outcome.error is None
        assert outcome.output_path == out
        lines = out.read_text(encoding="utf-8").splitlines()
        assert outcome.record_count == len(lines) > 0
        json.loads(lines[0])  # valid JSONL
        assert outcome.handshake_path is None
        assert outcome.placed_path is None
        assert outcome.resume_hint is None

    def test_handshake_out_written(self, tmp_path):
        hs = tmp_path / "handshake.md"
        opts = _opts(output=str(tmp_path / "out.jsonl"), handshake_out=str(hs))
        result = run_conversion(opts)
        outcome = execute_writes(result, opts)
        assert outcome.error is None
        assert outcome.handshake_path == hs
        assert hs.read_text(encoding="utf-8") == result.handshake

    def test_placement_with_resume_hint(self, tmp_path):
        home = tmp_path / ".claude"
        opts = _opts(
            target="claude-code",
            output=str(tmp_path / "out.jsonl"),
            place_claude_cwd=str(tmp_path),
            session_id="tui-test-session",
        )
        outcome = execute_writes(run_conversion(opts), opts, claude_home=home)
        assert outcome.error is None
        assert outcome.placed_path is not None
        assert outcome.placed_path.name == "tui-test-session.jsonl"
        assert outcome.placed_path.is_relative_to(home / "projects")
        assert outcome.placed_path.exists()
        assert "claude --resume tui-test-session" in outcome.resume_hint

    def test_duplicate_session_id_errors_without_raising(self, tmp_path):
        home = tmp_path / ".claude"

        def opts_for(name):
            return _opts(
                target="claude-code",
                output=str(tmp_path / name),
                place_claude_cwd=str(tmp_path),
                session_id="dup-session",
            )

        first = opts_for("out1.jsonl")
        assert execute_writes(run_conversion(first), first, claude_home=home).error is None

        second = opts_for("out2.jsonl")
        outcome = execute_writes(run_conversion(second), second, claude_home=home)
        assert isinstance(outcome, WriteOutcome)
        assert outcome.error is not None
        assert "already exists" in outcome.error
        # Partial success: the JSONL dump happened before placement failed.
        assert outcome.output_path == tmp_path / "out2.jsonl"
        assert outcome.output_path.exists()
        assert outcome.placed_path is None
        assert outcome.resume_hint is None

    def test_force_overwrites_duplicate(self, tmp_path):
        home = tmp_path / ".claude"
        opts = _opts(
            target="claude-code",
            output=str(tmp_path / "out.jsonl"),
            place_claude_cwd=str(tmp_path),
            session_id="dup-session",
        )
        assert execute_writes(run_conversion(opts), opts, claude_home=home).error is None
        opts.force = True
        outcome = execute_writes(run_conversion(opts), opts, claude_home=home)
        assert outcome.error is None
        assert outcome.placed_path is not None
