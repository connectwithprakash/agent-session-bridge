"""Tests for the TUI options model: CLI-command preview and form validation."""

from session_bridge.tui.options import ConvertOptions, build_cli_command, validate_options


def _opts(**kw):
    base = dict(source="claude-code", target="hermes", path="in.jsonl")
    base.update(kw)
    return ConvertOptions(**base)


class TestBuildCliCommand:
    def test_minimal_uses_default_output(self):
        cmd = build_cli_command(_opts())
        assert cmd == (
            "session-bridge convert --from claude-code --to hermes "
            "in.jsonl -o in.hermes.jsonl"
        )

    def test_explicit_output_used_verbatim(self):
        cmd = build_cli_command(_opts(output="custom.jsonl"))
        assert cmd.endswith("-o custom.jsonl")
        assert "in.hermes.jsonl" not in cmd

    def test_all_flags_included(self):
        cmd = build_cli_command(
            _opts(
                target="claude-code",
                no_handshake=True,
                stub_open_calls=True,
                handshake_out="hs.md",
                place_claude_cwd="/proj",
                session_id="abc-123",
                force=True,
            )
        )
        assert "--no-handshake" in cmd
        assert "--stub-open-calls" in cmd
        assert "--handshake-out hs.md" in cmd
        assert "--place-claude-cwd /proj" in cmd
        assert "--session-id abc-123" in cmd
        assert cmd.endswith("--force")

    def test_optional_flags_omitted_by_default(self):
        cmd = build_cli_command(_opts())
        for flag in (
            "--no-handshake",
            "--stub-open-calls",
            "--handshake-out",
            "--place-claude-cwd",
            "--session-id",
            "--force",
        ):
            assert flag not in cmd

    def test_path_with_spaces_is_quoted(self):
        cmd = build_cli_command(_opts(path="my session.jsonl", output="out file.jsonl"))
        assert "'my session.jsonl'" in cmd
        assert "'out file.jsonl'" in cmd


class TestValidateOptions:
    def test_clean_options_pass(self):
        assert validate_options(_opts()) == []

    def test_clean_placement_options_pass(self):
        opts = _opts(
            target="claude-code",
            place_claude_cwd="/proj",
            session_id="abc",
            force=True,
        )
        assert validate_options(opts) == []

    def test_unknown_source_and_target(self):
        errors = validate_options(_opts(source="cursor", target="aider"))
        assert len(errors) == 2
        assert any("source" in e for e in errors)
        assert any("target" in e for e in errors)

    def test_place_requires_claude_code_target(self):
        errors = validate_options(_opts(target="hermes", place_claude_cwd="/proj"))
        assert errors and "claude-code" in errors[0]

    def test_session_id_requires_place(self):
        errors = validate_options(_opts(session_id="abc"))
        assert errors and "session-id" in errors[0]

    def test_force_requires_place(self):
        errors = validate_options(_opts(force=True))
        assert errors and "force" in errors[0]
