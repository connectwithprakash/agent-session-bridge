"""CLI integration for the `tui` subcommand: lazy import and missing-dep hint."""

import sys

from session_bridge.cli import build_parser, main


def test_tui_subcommand_registered():
    parser = build_parser()
    args = parser.parse_args(["tui"])
    assert args.func.__name__ == "cmd_tui"


def test_tui_missing_textual_prints_install_hint(monkeypatch, capsys):
    # Poisoning sys.modules makes `import textual` raise plain ImportError,
    # which is why cmd_tui catches ImportError rather than ModuleNotFoundError.
    monkeypatch.setitem(sys.modules, "textual", None)
    monkeypatch.delitem(sys.modules, "session_bridge.tui.app", raising=False)
    rc = main(["tui"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "session-bridge[tui]" in err
