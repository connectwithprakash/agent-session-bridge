"""The session-bridge TUI application shell.

Importing this module requires textual (the ``[tui]`` extra); cli.py imports it
lazily and prints an install hint when the import fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import App

from .screens import PickerScreen


class SessionBridgeApp(App):
    """Linear convert wizard: pick a session, inspect, configure, dry-run, write."""

    TITLE = "session-bridge"
    CSS = """
    #picker-status { padding: 0 1; color: $text-muted; }
    #sessions { height: 1fr; }
    VerticalScroll { padding: 1 2; }
    .switch-row { height: auto; align-vertical: middle; }
    .switch-row Label { padding: 1 0 0 1; }
    #place-group { border: round $primary; padding: 0 1; margin: 1 0; }
    #form-errors { color: $error; }
    #dryrun-buttons { height: auto; padding: 0 2 1 2; }
    #dryrun-buttons Button { margin-right: 2; }
    #plan-buttons { height: auto; padding: 0 2 1 2; }
    #plan-buttons Button { margin-right: 2; }
    Label { margin-top: 1; }
    """

    def __init__(
        self,
        *,
        claude_home: Optional[Path] = None,
        codex_home: Optional[Path] = None,
        hermes_home: Optional[Path] = None,
    ) -> None:
        super().__init__()
        # Explicit store overrides (tests and unusual layouts); None means the
        # discovery module's real defaults (~/.claude, ~/.codex, ~/.hermes).
        self.claude_home = claude_home
        self.codex_home = codex_home
        self.hermes_home = hermes_home

    def on_mount(self) -> None:
        self.push_screen(PickerScreen())


def run_tui(
    *,
    claude_home: Optional[Path] = None,
    codex_home: Optional[Path] = None,
    hermes_home: Optional[Path] = None,
) -> int:
    SessionBridgeApp(
        claude_home=claude_home,
        codex_home=codex_home,
        hermes_home=hermes_home,
    ).run()
    return 0
