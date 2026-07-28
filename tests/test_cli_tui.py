"""CLI integration for the `tui` subcommand: lazy import and missing-dep hint."""

import sys

from session_bridge.cli import build_parser, main


def test_tui_subcommand_registered():
    parser = build_parser()
    args = parser.parse_args(["tui"])
    assert args.func.__name__ == "cmd_tui"


def test_version_flag_prints_version(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("session-bridge ")
    assert out.strip() != "session-bridge unknown"


def test_tui_missing_textual_prints_install_hint(monkeypatch, capsys):
    # Poisoning sys.modules makes `import textual` raise plain ImportError,
    # which is why cmd_tui catches ImportError rather than ModuleNotFoundError.
    # Poison every cached textual submodule too: other test modules (the Pilot
    # suite) import textual at collection time, and a cached `textual.app`
    # would satisfy `from textual.app import ...` despite the poisoned parent.
    for name in list(sys.modules):
        if name == "textual" or name.startswith("textual."):
            monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "textual", None)
    monkeypatch.delitem(sys.modules, "session_bridge.tui.app", raising=False)
    monkeypatch.delitem(sys.modules, "session_bridge.tui.screens", raising=False)
    rc = main(["tui"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "agent-session-bridge[tui]" in err
