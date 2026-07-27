"""Options model shared by the TUI form and its actions layer.

``ConvertOptions`` mirrors the ``convert`` subcommand's flags one-to-one so the
TUI can show the exact CLI invocation it is about to perform
(``build_cli_command``) and validate a form before any work happens
(``validate_options``). Keeping this module free of textual imports means the
option/validation logic is plain-Python testable and reusable outside the TUI.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from ..convert import HARNESSES, default_output_name


@dataclass
class ConvertOptions:
    source: str
    target: str
    path: str
    output: str | None = None  # None -> default_output_name(path, target)
    no_handshake: bool = False
    stub_open_calls: bool = False
    handshake_out: str | None = None
    place_claude_cwd: str | None = None  # claude-code target only
    session_id: str | None = None
    force: bool = False


def resolve_output(opts: ConvertOptions) -> str:
    """The output path a conversion will actually write to."""
    return opts.output or default_output_name(opts.path, opts.target)


def validate_options(opts: ConvertOptions) -> list[str]:
    """Human-readable errors for an invalid form; empty list means OK.

    Mirrors the CLI's pre-write validation (see ``cli.cmd_convert``) so the
    TUI rejects the same combinations the CLI would.
    """
    errors: list[str] = []
    if opts.source not in HARNESSES:
        errors.append(f"unknown source harness '{opts.source}'; choose from {HARNESSES}")
    if opts.target not in HARNESSES:
        errors.append(f"unknown target harness '{opts.target}'; choose from {HARNESSES}")
    if opts.place_claude_cwd and opts.target != "claude-code":
        errors.append("place-claude-cwd only applies when target is claude-code")
    if opts.session_id and not opts.place_claude_cwd:
        errors.append("session-id only applies together with place-claude-cwd")
    if opts.force and not opts.place_claude_cwd:
        errors.append("force only applies together with place-claude-cwd")
    return errors


def build_cli_command(opts: ConvertOptions) -> str:
    """The exact equivalent ``session-bridge convert`` invocation.

    Uses the resolved output (not the raw ``None``) so what the TUI shows is
    what will be written.
    """
    parts = [
        "session-bridge",
        "convert",
        "--from",
        opts.source,
        "--to",
        opts.target,
        opts.path,
        "-o",
        resolve_output(opts),
    ]
    if opts.no_handshake:
        parts.append("--no-handshake")
    if opts.stub_open_calls:
        parts.append("--stub-open-calls")
    if opts.handshake_out:
        parts += ["--handshake-out", opts.handshake_out]
    if opts.place_claude_cwd:
        parts += ["--place-claude-cwd", opts.place_claude_cwd]
    if opts.session_id:
        parts += ["--session-id", opts.session_id]
    if opts.force:
        parts.append("--force")
    return " ".join(shlex.quote(p) for p in parts)
