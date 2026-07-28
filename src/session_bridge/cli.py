"""session-bridge CLI.

    session-bridge inspect --from claude-code SESSION.jsonl
    session-bridge convert --from codex --to hermes SESSION.jsonl -o out.jsonl
    session-bridge convert --from claude-code --to codex SESSION.jsonl --no-handshake
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .convert import (
    HARNESSES,
    convert,
    default_output_name,
    dump_jsonl,
    now_codex_timestamp,
    read_session,
)
from .ir import BlockType


def _count_blocks(session, block_type):
    return sum(1 for m in session.messages for b in m.content if b.type is block_type)


def cmd_inspect(args: argparse.Namespace) -> int:
    session = read_session(args.source, args.path)
    m = session.meta
    print(f"source harness : {m.source_harness}")
    print(f"session id     : {m.session_id}")
    print(f"model          : {m.model}  (provider: {m.model_provider})")
    print(f"cwd            : {m.cwd}")
    print(f"permission     : {m.permission_mode}")
    print(f"messages       : {len(session.messages)}")
    print(f"  text blocks    : {_count_blocks(session, BlockType.TEXT)}")
    print(f"  reasoning      : {_count_blocks(session, BlockType.REASONING)}")
    print(f"  tool calls     : {_count_blocks(session, BlockType.TOOL_CALL)}")
    print(f"  tool results   : {_count_blocks(session, BlockType.TOOL_RESULT)}")
    print(f"tool schemas   : {len(session.tools)}")
    p = session.pending
    print("pending state  :")
    print(f"  open tool calls    : {list(p.open_tool_calls)}")
    print(f"  queued user input  : {len(p.queued_user_messages)}")
    print(f"  active goal        : {p.active_goal or '-'}")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    # Validate incompatible flags before writing anything, so an invalid combo
    # doesn't leave a stray -o output file on disk alongside the error.
    if args.place_claude_cwd and args.target != "claude-code":
        print("--place-claude-cwd only applies when --to claude-code", file=sys.stderr)
        return 2

    # Stamp Codex output with the real current time so the session isn't dated to
    # the writer's placeholder epoch (which can hide it from Codex's recency sort).
    codex_ts = now_codex_timestamp() if args.target == "codex" else None

    result = convert(
        args.source,
        args.target,
        args.path,
        inject_handshake=not args.no_handshake,
        codex_timestamp=codex_ts,
        stub_open_calls=args.stub_open_calls,
    )
    out = args.output or default_output_name(args.path, args.target)
    dump_jsonl(result.records, out)
    print(f"wrote {len(result.records)} records -> {out}")

    if result.report.warnings:
        print(f"\n{len(result.report.warnings)} conversion note(s):", file=sys.stderr)
        for w in result.report.warnings:
            print(f"  - {w}", file=sys.stderr)
    else:
        print("\nlossless conversion (no warnings).", file=sys.stderr)

    if args.handshake_out:
        Path(args.handshake_out).write_text(result.handshake, encoding="utf-8")
        print(f"wrote resume handshake -> {args.handshake_out}", file=sys.stderr)

    if args.place_claude_cwd:
        import shlex
        import uuid

        from ._ids import UnsafeSessionIdError
        from .place import SessionExistsError, UnsafeCwdError, place_claude_code

        session_id = args.session_id or str(uuid.uuid4())
        try:
            placed = place_claude_code(
                result.records,
                args.place_claude_cwd,
                session_id,
                overwrite=args.force,
            )
        except UnsafeSessionIdError as exc:
            print(f"invalid --session-id: {exc}", file=sys.stderr)
            return 2
        except UnsafeCwdError as exc:
            print(f"invalid --place-claude-cwd: {exc}", file=sys.stderr)
            return 2
        except SessionExistsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"placed resumable session -> {placed}", file=sys.stderr)
        print(
            f"resume with:  (cd {shlex.quote(args.place_claude_cwd)} "
            f"&& claude --resume {shlex.quote(session_id)})",
            file=sys.stderr,
        )
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    """Register a converted session into Hermes's SQLite store so it resumes.

    Takes a backup of the DB first (unless --no-backup). Claude Code needs no
    registration — use `convert --place-claude-cwd` for that.
    """
    import time
    import uuid

    from ._ids import UnsafeSessionIdError, validate_session_id
    from .handshake import stub_open_tool_calls
    from .writers._common import HERMES_DB_CAPS, report_losses
    from .writers.hermes_db import (
        HermesRegistrationError,
        backup_hermes_db,
        register_hermes_session,
    )

    session = read_session(args.source, args.path)

    # Surface conversion losses on the register path too (previously silent):
    # e.g. orphaned tool calls that break resume, dropped tool schemas, etc.
    # Report from the PRE-stub session so an interrupted call is still disclosed.
    # Use the DB writer's real capabilities (HERMES_DB_CAPS) rather than the
    # "hermes" file-writer caps: the state.db has no tool-catalog column, so a
    # hermes-sourced session's tool schemas ARE dropped here and must be warned.
    reg_report = report_losses(session, "hermes", caps_override=HERMES_DB_CAPS)
    if reg_report.warnings:
        print(f"\n{len(reg_report.warnings)} conversion note(s):", file=sys.stderr)
        for w in reg_report.warnings:
            print(f"  - {w}", file=sys.stderr)

    # register is the command that makes `hermes --resume` work, so it needs the
    # same open-call remediation convert has: a genuinely-open tool call is
    # written into state.db in a shape the provider rejects on resume. With
    # --stub-open-calls, append a synthetic interrupted result so the registered
    # session is actually resumable (the warning above still discloses it).
    if args.stub_open_calls:
        session = stub_open_tool_calls(session)

    db_path = args.db or os.path.expanduser("~/.hermes/state.db")
    if not os.path.exists(db_path):
        print(f"Hermes state.db not found: {db_path}", file=sys.stderr)
        return 2

    session_id = args.session_id or f"sb_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    try:
        validate_session_id(session_id)  # fail fast before backup/writes
    except UnsafeSessionIdError as exc:
        print(f"invalid --session-id: {exc}", file=sys.stderr)
        return 2

    if not args.no_backup:
        backup = f"{db_path}.session-bridge-backup-{time.time_ns()}-{uuid.uuid4().hex}"
        # WAL-safe: a plain file copy would miss committed rows still in the
        # sibling -wal file (Hermes runs WAL with the gateway holding the DB
        # open). The SQLite backup API reads through the live state.
        backup_hermes_db(db_path, backup)
        print(f"backed up state.db -> {backup}", file=sys.stderr)

    try:
        register_hermes_session(
            session,
            db_path,
            session_id,
            title=args.title,
            started_at=time.time(),
            model=args.model,
        )
    except HermesRegistrationError as exc:
        print(f"registration failed: {exc}", file=sys.stderr)
        return 1

    print(f"registered session {session_id} into {db_path}")
    if not args.model:
        print(
            "note: stored the source model id; if `hermes --resume` loses context, "
            "re-register with --model set to a Hermes-configured model.",
            file=sys.stderr,
        )
    print(f"resume with:  hermes --resume {session_id}", file=sys.stderr)
    return 0


def cmd_register_codex(args: argparse.Namespace) -> int:
    """Register a converted session into Codex's index and rollout store."""
    import time
    import uuid

    from ._ids import UnsafeSessionIdError, validate_session_id
    from .handshake import handshake_message, stub_open_tool_calls
    from .writers._common import report_losses
    from .writers.codex_db import (
        CodexRegistrationError,
        infer_codex_model,
        register_codex_session,
        validate_codex_store,
    )
    from .writers.hermes_db import backup_sqlite_db

    session = read_session(args.source, args.path)
    report = report_losses(session, "codex")
    if report.warnings:
        print(f"\n{len(report.warnings)} conversion note(s):", file=sys.stderr)
        for warning in report.warnings:
            print(f"  - {warning}", file=sys.stderr)

    if args.stub_open_calls:
        session = stub_open_tool_calls(session)
    session = session.with_messages((handshake_message(session, report, "codex"),) + session.messages)

    session_id = args.session_id or str(uuid.uuid4())
    try:
        validate_session_id(session_id)
        validate_codex_store(args.codex_home)
    except (UnsafeSessionIdError, CodexRegistrationError) as exc:
        print(f"invalid Codex registration: {exc}", file=sys.stderr)
        return 2

    db_path = Path(args.codex_home).expanduser() / "state_5.sqlite"
    model = args.model or infer_codex_model(args.codex_home, args.model_provider)
    if not model:
        print(
            "Codex registration needs a target model; pass --model because no prior "
            f"{args.model_provider!r} model was found in {db_path}",
            file=sys.stderr,
        )
        return 2
    if not args.no_backup:
        backup = f"{db_path}.session-bridge-backup-{time.time_ns()}-{uuid.uuid4().hex}"
        backup_sqlite_db(str(db_path), backup)
        print(f"backed up Codex state_5.sqlite -> {backup}", file=sys.stderr)

    try:
        rollout = register_codex_session(
            session,
            args.codex_home,
            session_id,
            cwd=args.cwd,
            title=args.title or f"resumed from {args.source}",
            model=model,
            model_provider=args.model_provider,
        )
    except CodexRegistrationError as exc:
        print(f"Codex registration failed: {exc}", file=sys.stderr)
        return 1

    print(f"registered session {session_id} into {db_path}")
    print(f"using Codex model {args.model_provider}/{model}")
    print(f"wrote Codex rollout -> {rollout}")
    print(f"resume with:  (cd {args.cwd} && codex resume {session_id})", file=sys.stderr)
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    """Launch the interactive TUI (requires the optional 'textual' dependency)."""
    try:
        from .tui.app import run_tui
    except ImportError:
        # ImportError, not just ModuleNotFoundError: also covers a broken or
        # half-installed textual, which should get the same actionable hint.
        print(
            "the TUI needs the optional 'textual' dependency:\n"
            "  pip install 'agent-session-bridge[tui]'",
            file=sys.stderr,
        )
        return 2
    return run_tui()


def cmd_install_skill(args: argparse.Namespace) -> int:
    """Distribute the packaged session-handoff skill to installed harnesses."""
    from pathlib import Path

    from .skill_install import HARNESS_HOMES, install_skill

    homes = {name: Path(path) for name, path in HARNESS_HOMES.items()}
    results = install_skill(homes, copy=args.copy, force=args.force)
    failed = False
    for r in results:
        if r.action == "error":
            failed = True
            print(f"{r.harness}: ERROR — {r.detail}", file=sys.stderr)
        else:
            print(f"{r.harness}: {r.action} — {r.detail}")
    if all(r.action == "skipped" for r in results):
        print(
            "no harness homes found (~/.claude, ~/.codex, ~/.hermes) — nothing installed",
            file=sys.stderr,
        )
        return 1
    return 1 if failed else 0


def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("agent-session-bridge")
    except PackageNotFoundError:  # running from a source tree without install
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="session-bridge", description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {_package_version()}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    insp = sub.add_parser("inspect", help="parse a session and print its structure")
    insp.add_argument("--from", dest="source", required=True, choices=HARNESSES)
    insp.add_argument("path")
    insp.set_defaults(func=cmd_inspect)

    conv = sub.add_parser("convert", help="convert a session between harnesses")
    conv.add_argument("--from", dest="source", required=True, choices=HARNESSES)
    conv.add_argument("--to", dest="target", required=True, choices=HARNESSES)
    conv.add_argument("path")
    conv.add_argument("-o", "--output", help="output JSONL path")
    conv.add_argument("--handshake-out", help="also write the resume handshake to this path")
    conv.add_argument("--no-handshake", action="store_true",
                      help="do not prepend the resume handshake message")
    conv.add_argument("--stub-open-calls", action="store_true",
                      help="append a synthetic interrupted tool_result for each "
                           "still-open tool call, so the output is a valid transcript "
                           "a provider will accept on resume (a call with no result "
                           "is a 400 on OpenAI Responses / rejected by Anthropic)")
    conv.add_argument("--place-claude-cwd", metavar="CWD",
                      help="also place the converted session under Claude Code's "
                           "project dir for this cwd, so `claude --resume` finds it "
                           "(only valid with --to claude-code)")
    conv.add_argument("--session-id",
                      help="session id to use when placing (default: a fresh uuid)")
    conv.add_argument("--force", action="store_true",
                      help="overwrite an existing placed transcript at the same "
                           "--session-id (default: fail rather than clobber it)")
    conv.set_defaults(func=cmd_convert)

    reg = sub.add_parser(
        "register",
        help="register a session into Hermes's SQLite store so `hermes --resume` finds it",
    )
    reg.add_argument("--from", dest="source", required=True, choices=HARNESSES)
    reg.add_argument("path")
    reg.add_argument("--db", help="path to Hermes state.db (default: ~/.hermes/state.db)")
    reg.add_argument("--model",
                     help="model id to store; set to a Hermes-configured model so resume "
                          "keeps context (a cross-harness source id may not route)")
    reg.add_argument("--title", help="session title (must be unique in the store)")
    reg.add_argument("--session-id", help="session id to use (default: a generated sb_ id)")
    reg.add_argument("--no-backup", action="store_true",
                     help="skip backing up state.db first (not recommended)")
    reg.add_argument("--stub-open-calls", action="store_true",
                     help="append a synthetic interrupted tool_result for each "
                          "still-open tool call before registering, so the stored "
                          "session is resumable (a call with no result breaks "
                          "`hermes --resume`)")
    reg.set_defaults(func=cmd_register)

    codex_reg = sub.add_parser(
        "register-codex",
        help="register a session into Codex's local store so `codex resume` finds it",
    )
    codex_reg.add_argument("--from", dest="source", required=True, choices=HARNESSES)
    codex_reg.add_argument("path")
    codex_reg.add_argument(
        "--codex-home", default=os.path.expanduser("~/.codex"),
        help="Codex home containing state_5.sqlite (default: ~/.codex)",
    )
    codex_reg.add_argument(
        "--cwd", required=True,
        help="existing project directory Codex uses to discover the resumed session",
    )
    codex_reg.add_argument("--title", help="title shown in Codex's resume picker")
    codex_reg.add_argument(
        "--model",
        help="target Codex model; defaults to the most recently used model for --model-provider",
    )
    codex_reg.add_argument(
        "--model-provider",
        default="openai",
        help="target Codex model provider (default: openai; never inferred from the source)",
    )
    codex_reg.add_argument("--session-id", help="UUID to use (default: a generated UUID)")
    codex_reg.add_argument(
        "--no-backup", action="store_true",
        help="skip backing up state_5.sqlite first (not recommended)",
    )
    codex_reg.add_argument(
        "--stub-open-calls", action="store_true",
        help="append a synthetic interrupted tool_result for each still-open tool call "
             "before registering, so the resumed transcript is provider-valid",
    )
    codex_reg.set_defaults(func=cmd_register_codex)

    tui = sub.add_parser(
        "tui",
        help="interactive session picker/converter "
             "(requires: pip install 'agent-session-bridge[tui]')",
    )
    tui.set_defaults(func=cmd_tui)

    skill = sub.add_parser(
        "install-skill",
        help="link the session-handoff agent skill into every installed "
             "harness's skills dir (~/.claude, ~/.codex, ~/.hermes)",
    )
    skill.add_argument(
        "--copy", action="store_true",
        help="copy instead of symlink (survives uninstalling session-bridge, "
             "but goes stale on upgrades)",
    )
    skill.add_argument(
        "--force", action="store_true",
        help="replace an existing differing skill at the target path",
    )
    skill.set_defaults(func=cmd_install_skill)
    return parser


def main(argv: list[str] | None = None) -> int:
    import json
    import sqlite3

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:
        # Clean error for common filesystem failures instead of a raw traceback,
        # matching the handling for other error classes in the commands.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except UnicodeDecodeError as exc:
        print(f"error: file is not valid UTF-8: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        # A hand-edited or tool-mangled interior line in a session file: the
        # readers re-raise it by design; surface it cleanly, not as a traceback.
        print(f"error: not a valid session file (JSON parse error): {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        # e.g. --db pointing at a file that is not a valid SQLite database.
        print(f"error: SQLite failure: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # Catch-all for filesystem failures not covered above (e.g. ENAMETOOLONG,
        # ENOSPC). Keep this last so the specific handlers above win.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
