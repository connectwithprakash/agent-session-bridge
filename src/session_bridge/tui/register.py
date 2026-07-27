"""Registration layer behind the TUI's Hermes/Codex register flows.

Split in two so the TUI can preview before committing, mirroring the convert
flow in ``actions.py``:

- ``prepare_hermes_register`` / ``prepare_codex_register`` are PURE — they read
  the source session, compute the loss report, resolve every default the CLI
  would (db path, session id, model), and return a ``RegisterPlan`` the TUI can
  render (including the exact equivalent CLI invocation) without any write.
- ``execute_register`` performs the writes the CLI's ``register`` /
  ``register-codex`` commands would (backup, then SQLite/rollout registration).

Semantics mirror ``cli.cmd_register`` and ``cli.cmd_register_codex`` exactly,
including their asymmetry: the Hermes path never injects a resume handshake
(``hermes --resume`` replays the stored rows as-is), while the Codex path
ALWAYS prepends one to the rollout. Loss reports are computed from the PRE-stub
session so an interrupted tool call is still disclosed even when
``stub_open_calls`` repairs it.

Nothing here raises: every failure — including unexpected filesystem/SQLite
errors — comes back in ``.error`` so screens render it instead of crashing.
"""

from __future__ import annotations

import shlex
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .._ids import UnsafeSessionIdError, validate_session_id
from ..convert import read_session
from ..handshake import handshake_message, stub_open_tool_calls
from ..ir import Session
from ..writers._common import HERMES_DB_CAPS, report_losses
from ..writers.codex_db import (
    CodexRegistrationError,
    infer_codex_model,
    register_codex_session,
    validate_codex_store,
)
from ..writers.hermes_db import (
    HermesRegistrationError,
    backup_hermes_db,
    backup_sqlite_db,
    register_hermes_session,
)

# Same advisory the CLI prints when registering into Hermes without --model:
# Hermes routes the resumed turn by the stored model id, so a cross-harness
# source id it cannot route makes resume silently lose context.
_HERMES_MODEL_NOTE = (
    "stored the source model id; if `hermes --resume` loses context, "
    "re-register with --model set to a Hermes-configured model."
)


@dataclass
class HermesRegisterOptions:
    source: str
    path: str
    db: str | None = None  # None -> <hermes_home or ~/.hermes>/state.db
    model: str | None = None
    title: str | None = None
    session_id: str | None = None
    no_backup: bool = False
    stub_open_calls: bool = False


@dataclass
class CodexRegisterOptions:
    source: str
    path: str
    cwd: str
    codex_home: str | None = None  # None -> ~/.codex
    title: str | None = None
    model: str | None = None
    model_provider: str = "openai"
    session_id: str | None = None
    no_backup: bool = False
    stub_open_calls: bool = False


@dataclass
class RegisterPlan:
    store: str  # "hermes" | "codex"
    session: Session | None  # fully prepared, ready to register (post-stub;
    # post-handshake for codex)
    warnings: list[str]  # report_losses disclosure (computed PRE-stub)
    notes: list[str]  # advisory lines (e.g. hermes model-routing note)
    session_id: str | None
    db_path: Path | None
    model: str | None  # resolved model (codex: inferred when opts.model is None)
    cli_command: str  # equivalent CLI invocation, shlex-quoted
    opts: HermesRegisterOptions | CodexRegisterOptions | None
    error: str | None  # set when planning failed; screens render it


@dataclass
class RegisterOutcome:
    session_id: str | None
    db_path: Path | None
    backup_path: Path | None
    rollout_path: Path | None  # codex only
    resume_hint: str | None
    error: str | None  # None = success


def _error_plan(
    store: str,
    opts: HermesRegisterOptions | CodexRegisterOptions | None,
    error: str,
    *,
    warnings: list[str] | None = None,
    notes: list[str] | None = None,
    session_id: str | None = None,
    db_path: Path | None = None,
    model: str | None = None,
    cli_command: str = "",
) -> RegisterPlan:
    """A failed plan carrying whatever was resolved before the failure."""
    return RegisterPlan(
        store=store,
        session=None,
        warnings=warnings or [],
        notes=notes or [],
        session_id=session_id,
        db_path=db_path,
        model=model,
        cli_command=cli_command,
        opts=opts,
        error=error,
    )


def _hermes_cli_command(
    opts: HermesRegisterOptions, *, db_path: Path, session_id: str
) -> str:
    """The exact equivalent ``session-bridge register`` invocation.

    Uses the resolved db path and session id (not the raw ``None`` defaults) so
    what the TUI shows is what will land in the store.
    """
    parts = [
        "session-bridge",
        "register",
        "--from",
        opts.source,
        opts.path,
        "--db",
        str(db_path),
    ]
    if opts.model:
        parts += ["--model", opts.model]
    if opts.title:
        parts += ["--title", opts.title]
    parts += ["--session-id", session_id]
    if opts.no_backup:
        parts.append("--no-backup")
    if opts.stub_open_calls:
        parts.append("--stub-open-calls")
    return " ".join(shlex.quote(p) for p in parts)


def _codex_cli_command(
    opts: CodexRegisterOptions,
    *,
    codex_home: Path,
    session_id: str,
    model: str | None,
) -> str:
    """The exact equivalent ``session-bridge register-codex`` invocation."""
    parts = [
        "session-bridge",
        "register-codex",
        "--from",
        opts.source,
        opts.path,
        "--cwd",
        opts.cwd,
        "--codex-home",
        str(codex_home),
    ]
    if opts.title:
        parts += ["--title", opts.title]
    if model:
        parts += ["--model", model]
    if opts.model_provider != "openai":
        parts += ["--model-provider", opts.model_provider]
    parts += ["--session-id", session_id]
    if opts.no_backup:
        parts.append("--no-backup")
    if opts.stub_open_calls:
        parts.append("--stub-open-calls")
    return " ".join(shlex.quote(p) for p in parts)


def prepare_hermes_register(
    opts: HermesRegisterOptions, *, hermes_home: Path | None = None
) -> RegisterPlan:
    """Plan a Hermes registration without writing anything.

    Mirrors ``cli.cmd_register``: losses are reported against the DB writer's
    real capabilities (HERMES_DB_CAPS) from the PRE-stub session; no handshake
    is injected (the CLI's register path doesn't either — the stored rows replay
    as-is on resume). Never raises.
    """
    try:
        session = read_session(opts.source, opts.path)
        # PRE-stub, so a genuinely-open tool call is disclosed even when
        # stub_open_calls repairs it below.
        report = report_losses(session, "hermes", caps_override=HERMES_DB_CAPS)
        warnings = list(report.warnings)

        if opts.stub_open_calls:
            session = stub_open_tool_calls(session)

        home = hermes_home if hermes_home is not None else Path("~/.hermes").expanduser()
        db_path = Path(opts.db) if opts.db else home / "state.db"
        session_id = opts.session_id or f"sb_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        # None means register_hermes_session stores the session's own model;
        # resolve it here so the TUI can show what will actually be stored.
        model = opts.model or session.meta.model
        cli_command = _hermes_cli_command(opts, db_path=db_path, session_id=session_id)

        if not db_path.exists():
            return _error_plan(
                "hermes",
                opts,
                f"Hermes state.db not found: {db_path}",
                warnings=warnings,
                session_id=session_id,
                db_path=db_path,
                model=model,
                cli_command=cli_command,
            )
        try:
            validate_session_id(session_id)  # fail fast before any write
        except UnsafeSessionIdError as exc:
            return _error_plan(
                "hermes",
                opts,
                f"invalid session id: {exc}",
                warnings=warnings,
                session_id=session_id,
                db_path=db_path,
                model=model,
                cli_command=cli_command,
            )

        notes: list[str] = []
        if opts.model is None:
            notes.append(_HERMES_MODEL_NOTE)

        return RegisterPlan(
            store="hermes",
            session=session,
            warnings=warnings,
            notes=notes,
            session_id=session_id,
            db_path=db_path,
            model=model,
            cli_command=cli_command,
            opts=opts,
            error=None,
        )
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        # Broad safety net: a screen must render an error, never a traceback.
        # ValueError also covers unknown-harness and JSON parse failures from
        # read_session; UnicodeDecodeError is a ValueError subclass.
        # RuntimeError covers HermesRegistrationError and expanduser's bare
        # RuntimeError on an unresolvable "~user" path.
        return _error_plan("hermes", opts, str(exc))


def prepare_codex_register(
    opts: CodexRegisterOptions, *, codex_home: Path | None = None
) -> RegisterPlan:
    """Plan a Codex registration without writing anything.

    Mirrors ``cli.cmd_register_codex``: losses reported pre-stub, optional
    stubbing, then a resume handshake ALWAYS prepended, store/id validation,
    and model inference from the target store when ``opts.model`` is unset.
    Never raises.

    ``codex_home`` is the app-level store override (tests, isolated stores);
    like ``prepare_hermes_register``'s ``hermes_home``, it fills in when the
    form field (``opts.codex_home``) is blank, so blanking the field cannot
    silently escape an isolated store to the real ``~/.codex``.
    """
    try:
        if opts.codex_home:
            home = Path(opts.codex_home).expanduser()
        elif codex_home is not None:
            home = Path(codex_home)
        else:
            home = Path("~/.codex").expanduser()
        db_path = home / "state_5.sqlite"

        session = read_session(opts.source, opts.path)
        report = report_losses(session, "codex")  # PRE-stub disclosure
        warnings = list(report.warnings)

        if opts.stub_open_calls:
            session = stub_open_tool_calls(session)
        session = session.with_messages(
            (handshake_message(session, report, "codex"),) + session.messages
        )

        session_id = opts.session_id or str(uuid.uuid4())
        cli_command = _codex_cli_command(
            opts, codex_home=home, session_id=session_id, model=opts.model
        )
        try:
            validate_session_id(session_id)
            # register_codex_session additionally requires a UUID-shaped id;
            # check it at plan time so a knowable-bad id fails BEFORE the
            # backup is taken at execute time.
            try:
                uuid.UUID(session_id)
            except ValueError as exc:
                raise CodexRegistrationError(
                    f"Codex session id must be a UUID: {session_id!r}"
                ) from exc
            validate_codex_store(home)
        except (UnsafeSessionIdError, CodexRegistrationError) as exc:
            return _error_plan(
                "codex",
                opts,
                f"invalid Codex registration: {exc}",
                warnings=warnings,
                session_id=session_id,
                db_path=db_path,
                model=opts.model,
                cli_command=cli_command,
            )

        model = opts.model or infer_codex_model(home, opts.model_provider)
        if not model:
            return _error_plan(
                "codex",
                opts,
                "Codex registration needs a target model; set a model because "
                f"no prior {opts.model_provider!r} model was found in {db_path}",
                warnings=warnings,
                session_id=session_id,
                db_path=db_path,
                cli_command=cli_command,
            )
        # Rebuild with the resolved model so the shown command is fully pinned.
        cli_command = _codex_cli_command(
            opts, codex_home=home, session_id=session_id, model=model
        )

        return RegisterPlan(
            store="codex",
            session=session,
            warnings=warnings,
            notes=[],
            session_id=session_id,
            db_path=db_path,
            model=model,
            cli_command=cli_command,
            opts=opts,
            error=None,
        )
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        # RuntimeError covers CodexRegistrationError and expanduser's bare
        # RuntimeError on an unresolvable "~user" path.
        return _error_plan("codex", opts, str(exc))


def execute_register(plan: RegisterPlan) -> RegisterOutcome:
    """Perform the writes for a previously-prepared registration.

    Errors are returned, never raised. Artifacts created before a failure
    (e.g. the backup) stay set in the outcome alongside ``error`` so the user
    knows what actually landed on disk.
    """
    backup_path: Path | None = None
    rollout_path: Path | None = None
    resume_hint: str | None = None

    def outcome(error: str | None) -> RegisterOutcome:
        return RegisterOutcome(
            session_id=plan.session_id,
            db_path=plan.db_path,
            backup_path=backup_path,
            rollout_path=rollout_path,
            resume_hint=resume_hint,
            error=error,
        )

    if plan.error is not None:
        return outcome(plan.error)
    if (
        plan.session is None
        or plan.opts is None
        or plan.db_path is None
        or plan.session_id is None
    ):
        return outcome("register plan is incomplete; re-run the prepare step")

    def _take_backup(backup_fn) -> None:
        # A failed backup must not leave an undisclosed partial file (the
        # backup API creates the destination before copying into it).
        nonlocal backup_path
        backup = (
            f"{plan.db_path}.session-bridge-backup-"
            f"{time.time_ns()}-{uuid.uuid4().hex}"
        )
        try:
            backup_fn(str(plan.db_path), backup)
        except BaseException:
            Path(backup).unlink(missing_ok=True)
            raise
        backup_path = Path(backup)

    try:
        # The plan screen can sit open indefinitely; if the store vanished
        # since planning, fail here rather than let the backup's
        # sqlite3.connect silently create an empty file at the live path.
        if not plan.db_path.exists():
            return outcome(
                f"store no longer exists (moved or deleted since plan): {plan.db_path}"
            )
        if plan.store == "hermes":
            opts = plan.opts
            if not opts.no_backup:
                # WAL-safe backup via the SQLite backup API, same filename
                # pattern as the CLI.
                _take_backup(backup_hermes_db)
            register_hermes_session(
                plan.session,
                str(plan.db_path),
                plan.session_id,
                title=opts.title,
                started_at=time.time(),
                model=opts.model,
            )
            resume_hint = f"hermes --resume {plan.session_id}"
        elif plan.store == "codex":
            opts = plan.opts
            if not opts.no_backup:
                _take_backup(backup_sqlite_db)
            # db_path is always <codex_home>/state_5.sqlite, so the home is its
            # parent — no need to re-resolve opts.codex_home's None default.
            rollout_path = register_codex_session(
                plan.session,
                plan.db_path.parent,
                plan.session_id,
                cwd=opts.cwd,
                title=opts.title or f"resumed from {opts.source}",
                model=plan.model,
                model_provider=opts.model_provider,
            )
            # Same hint the CLI prints, quoted like the convert flow's.
            resume_hint = (
                f"(cd {shlex.quote(opts.cwd)} "
                f"&& codex resume {shlex.quote(plan.session_id)})"
            )
        else:
            return outcome(f"unknown register store: {plan.store!r}")
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        # Covers HermesRegistrationError / CodexRegistrationError (both
        # RuntimeError subclasses) plus any bare RuntimeError.
        RuntimeError,
    ) as exc:
        return outcome(str(exc))
    return outcome(None)
