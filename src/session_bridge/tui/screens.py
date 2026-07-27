"""Textual screens for the session-bridge TUI convert wizard.

Linear flow: PickerScreen -> SummaryScreen -> OptionsScreen -> DryRunScreen ->
ResultScreen. Screens pass data forward via constructor args; ``escape`` pops
back. All parsing/conversion/writing runs in thread workers so the UI never
blocks, and every failure renders as a panel — a traceback escaping textual
would corrupt the terminal.

This module is the only one (besides app.py) that imports textual; all logic
lives in the textual-free sibling modules (discovery/options/summary/actions).
"""

from __future__ import annotations

from datetime import datetime

# Session content (ids, cwds, previews, error text) is untrusted and must never
# reach a markup-parsing sink unescaped: "[red]" in a transcript would otherwise
# raise MarkupError and take down the whole app.
from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
)

from ..convert import HARNESSES, ConversionResult, default_output_name, read_session
from ..ir import Session
from .actions import execute_writes, run_conversion
from .discovery import SessionEntry, discover_sessions
from .options import ConvertOptions, build_cli_command, resolve_output, validate_options
from .summary import summarize_session


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def _one_line(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class PickerScreen(Screen):
    """Discovered sessions across all three harness stores, newest first."""

    BINDINGS = [
        ("r", "rescan", "Rescan"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[SessionEntry] = []
        self._by_key: dict[str, SessionEntry] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("scanning session stores…", id="picker-status")
        yield DataTable(id="sessions")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("harness", "session id", "cwd", "modified", "size", "preview")
        self._load()

    @work(thread=True, exclusive=True)
    def _load(self) -> None:
        app = self.app
        entries = discover_sessions(
            claude_home=getattr(app, "claude_home", None),
            codex_home=getattr(app, "codex_home", None),
            hermes_home=getattr(app, "hermes_home", None),
        )
        app.call_from_thread(self._populate, entries)

    def _populate(self, entries: list[SessionEntry]) -> None:
        self.entries = entries
        self._by_key = {str(e.path): e for e in entries}
        status = self.query_one("#picker-status", Static)
        table = self.query_one(DataTable)
        table.clear()
        for e in entries:
            table.add_row(
                e.harness,
                escape(_one_line(e.session_id or "?", 40)),
                escape(_one_line(e.cwd or "-", 40)),
                datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M"),
                _human_size(e.size),
                escape(_one_line(e.preview or "")),
                key=str(e.path),
            )
        status.update(
            f"{len(entries)} session(s) found — enter to select, r to rescan, q to quit"
            if entries
            else "no sessions found in ~/.claude, ~/.codex, or ~/.hermes — r to rescan"
        )

    def action_rescan(self) -> None:
        self.query_one("#picker-status", Static).update("rescanning…")
        self._load()

    def action_quit(self) -> None:
        self.app.exit()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Resolve by row key, not cursor index: a rescan can repopulate the
        # table between the selection event being posted and handled.
        entry = self._by_key.get(event.row_key.value or "")
        if entry is not None:
            self.app.push_screen(SummaryScreen(entry))


class SummaryScreen(Screen):
    """Full parse of the chosen session (inspect-equivalent), kept for later screens."""

    BINDINGS = [
        ("c", "convert", "Convert"),
        ("g", "register", "Register"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, entry: SessionEntry) -> None:
        super().__init__()
        self.entry = entry
        self.session: Session | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static(f"parsing {escape(str(self.entry.path))}…", id="summary-body")
        yield Footer()

    def on_mount(self) -> None:
        self._parse()

    @work(thread=True, exclusive=True)
    def _parse(self) -> None:
        try:
            session = read_session(self.entry.harness, self.entry.path)
        except Exception as exc:  # any parse failure -> panel, never a crash
            self.app.call_from_thread(self._show_error, exc)
            return
        self.app.call_from_thread(self._render_summary, session)

    def _show_error(self, exc: Exception) -> None:
        self.query_one("#summary-body", Static).update(
            f"[b red]could not parse this session[/]\n\n{escape(str(exc))}\n\nescape to go back"
        )

    # NB: not `_render` — that name is textual's internal Widget._render hook.
    def _render_summary(self, session: Session) -> None:
        self.session = session
        rows = summarize_session(session)
        width = max(len(label) for label, _ in rows)
        body = "\n".join(
            f"[b]{label:<{width}}[/]  {escape(value)}" for label, value in rows
        )
        self.query_one("#summary-body", Static).update(
            body + "\n\n[dim]c to configure a conversion, escape to go back[/]"
        )

    def action_convert(self) -> None:
        if self.session is not None:
            self.app.push_screen(OptionsScreen(self.entry, self.session))

    def action_register(self) -> None:
        if self.session is not None:
            self.app.push_screen(RegisterFormScreen(self.entry))


class OptionsScreen(Screen):
    """Convert options form; placement fields only exist for a claude-code target."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, entry: SessionEntry, session: Session) -> None:
        super().__init__()
        self.entry = entry
        self.session = session
        # Default to converting *away* from the source harness.
        self.initial_target = next(h for h in HARNESSES if h != entry.harness)
        self._auto_output = default_output_name(entry.path, self.initial_target)

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label("Target harness")
            yield Select(
                [(h, h) for h in HARNESSES],
                value=self.initial_target,
                allow_blank=False,
                id="target",
            )
            yield Label("Output path")
            yield Input(
                value=default_output_name(self.entry.path, self.initial_target),
                id="output",
            )
            with Horizontal(classes="switch-row"):
                yield Switch(value=True, id="handshake")
                yield Label("prepend resume handshake")
            with Horizontal(classes="switch-row"):
                yield Switch(value=False, id="stub")
                yield Label("stub open tool calls (synthetic interrupted results)")
            yield Label("Also write handshake markdown to (optional)")
            yield Input(placeholder="e.g. resume.md", id="handshake-out")
            with Vertical(id="place-group"):
                with Horizontal(classes="switch-row"):
                    yield Switch(value=False, id="place")
                    yield Label("place under ~/.claude/projects so `claude --resume` finds it")
                yield Label("Project cwd for placement")
                yield Input(value=self.entry.cwd or "", id="place-cwd")
                yield Label("Session id (blank: fresh uuid)")
                yield Input(id="session-id")
                with Horizontal(classes="switch-row"):
                    yield Switch(value=False, id="force")
                    yield Label("overwrite an existing transcript at that id")
            yield Static("", id="form-errors")
            yield Button("Continue to dry run", variant="primary", id="continue")
        yield Footer()

    def on_mount(self) -> None:
        self._sync_target(self.initial_target)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "target":
            self._sync_target(str(event.value))

    def _sync_target(self, target: str) -> None:
        # Placement is claude-code-only: hide (not just disable) the group so a
        # target flip can't smuggle stale place options into the built command.
        self.query_one("#place-group").display = target == "claude-code"
        # Refresh the output default on target flips, but never clobber a path
        # the user has edited by hand.
        out = self.query_one("#output", Input)
        new_default = default_output_name(self.entry.path, target)
        if out.value == self._auto_output:
            out.value = new_default
        self._auto_output = new_default

    def _build_options(self) -> ConvertOptions:
        target = str(self.query_one("#target", Select).value)
        placing = (
            target == "claude-code" and self.query_one("#place", Switch).value
        )
        output = self.query_one("#output", Input).value.strip()
        handshake_out = self.query_one("#handshake-out", Input).value.strip()
        session_id = self.query_one("#session-id", Input).value.strip()
        return ConvertOptions(
            source=self.entry.harness,
            target=target,
            path=str(self.entry.path),
            output=output or None,
            no_handshake=not self.query_one("#handshake", Switch).value,
            stub_open_calls=self.query_one("#stub", Switch).value,
            handshake_out=handshake_out or None,
            place_claude_cwd=(
                self.query_one("#place-cwd", Input).value.strip() or None
            )
            if placing
            else None,
            session_id=(session_id or None) if placing else None,
            force=self.query_one("#force", Switch).value if placing else False,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter in any form field submits, like a regular form.
        self._continue()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue":
            self._continue()

    def _continue(self) -> None:
        opts = self._build_options()
        errors = validate_options(opts)
        # ConvertOptions can't represent "placement wanted but no cwd" (the CLI
        # drives placement purely off the --place-claude-cwd value), so catch
        # that state here where the switch is visible: silently dropping an
        # explicit placement request would violate the never-silent invariant.
        if (
            self.query_one("#place-group").display
            and self.query_one("#place", Switch).value
            and not opts.place_claude_cwd
        ):
            errors.append(
                "placement is enabled but no project cwd was given — fill in "
                "the cwd or turn the placement switch off"
            )
        if errors:
            self.query_one("#form-errors", Static).update(
                "[b red]" + "\n".join(errors) + "[/]"
            )
            return
        self.app.push_screen(DryRunScreen(opts))


class DryRunScreen(Screen):
    """Run the pure conversion and show everything BEFORE any file is written."""

    BINDINGS = [("escape", "back", "Back")]

    def __init__(self, opts: ConvertOptions) -> None:
        super().__init__()
        self.opts = opts
        self.result: ConversionResult | None = None
        self._writing = False

    def action_back(self) -> None:
        # Popping mid-write would discard the outcome (including any error);
        # the write worker pushes ResultScreen when it finishes.
        if not self._writing:
            self.app.pop_screen()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static("converting (nothing written yet)…", id="dryrun-body")
        with Horizontal(id="dryrun-buttons"):
            yield Button("Write files", variant="success", id="write", disabled=True)
            yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._convert()

    @work(thread=True, exclusive=True)
    def _convert(self) -> None:
        try:
            result = run_conversion(self.opts)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, exc)
            return
        self.app.call_from_thread(self._render_dryrun, result)

    def _show_error(self, exc: Exception) -> None:
        self.query_one("#dryrun-body", Static).update(
            f"[b red]conversion failed[/]\n\n{escape(str(exc))}\n\nescape to go back"
        )

    def _render_dryrun(self, result: ConversionResult) -> None:
        self.result = result
        opts = self.opts
        out = resolve_output(opts)
        lines = [
            f"[b]will write[/]        {len(result.records)} records -> {escape(out)}",
        ]
        if opts.handshake_out:
            lines.append(f"[b]handshake copy[/]    -> {escape(opts.handshake_out)}")
        if opts.place_claude_cwd:
            lines.append(
                f"[b]placement[/]         under ~/.claude/projects for cwd "
                f"{escape(opts.place_claude_cwd)}"
            )
        if result.report.warnings:
            lines.append(f"\n[b]{len(result.report.warnings)} conversion note(s):[/]")
            lines.extend(f"  [yellow]- {escape(w)}[/]" for w in result.report.warnings)
        else:
            lines.append("\n[green]lossless conversion (no warnings).[/]")
        lines.append("\n[b]equivalent CLI command:[/]")
        lines.append(f"  [dim]{escape(build_cli_command(opts))}[/]")
        self.query_one("#dryrun-body", Static).update("\n".join(lines))
        write = self.query_one("#write", Button)
        write.disabled = False
        # While Write was disabled, focus defaulted to Cancel — move it so
        # plain Enter confirms rather than silently cancelling.
        write.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_back()
        elif event.button.id == "write" and self.result is not None and not self._writing:
            self._writing = True
            self.query_one("#write", Button).disabled = True
            self.query_one("#cancel", Button).disabled = True
            self._write()

    @work(thread=True, exclusive=True)
    def _write(self) -> None:
        outcome = execute_writes(
            self.result,
            self.opts,
            claude_home=getattr(self.app, "claude_home", None),
        )
        self.app.call_from_thread(self.app.push_screen, ResultScreen(outcome))


class ResultScreen(Screen):
    """Outcome of the writes: paths, resume hint, or a rendered error."""

    BINDINGS = [
        ("n", "new_conversion", "Another conversion"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, outcome) -> None:
        super().__init__()
        self.outcome = outcome

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static(self._body(), id="result-body")
        yield Footer()

    def _body(self) -> str:
        o = self.outcome
        lines = []
        if o.output_path:
            lines.append(
                f"[green]wrote {o.record_count} records -> {escape(str(o.output_path))}[/]"
            )
        if o.handshake_path:
            lines.append(f"wrote resume handshake -> {escape(str(o.handshake_path))}")
        if o.placed_path:
            lines.append(f"placed resumable session -> {escape(str(o.placed_path))}")
        if o.resume_hint:
            lines.append(f"\n[b]resume with:[/]  {escape(o.resume_hint)}")
        if o.error:
            lines.append(f"\n[b red]error:[/] {escape(o.error)}")
        lines.append("\n[dim]n for another conversion, q to quit[/]")
        return "\n".join(lines)

    def action_new_conversion(self) -> None:
        while not isinstance(self.app.screen, PickerScreen):
            self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class RegisterFormScreen(Screen):
    """Registration options: write the session into a harness's SQLite store."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, entry: SessionEntry) -> None:
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        app_codex_home = getattr(self.app, "codex_home", None)
        yield Header()
        with VerticalScroll():
            yield Label("Target store")
            yield Select(
                [("Hermes (state.db)", "hermes"), ("Codex (state_5.sqlite)", "codex")],
                value="hermes",
                allow_blank=False,
                id="store",
            )
            yield Label("Title (optional)")
            yield Input(placeholder=f"resumed from {self.entry.harness}", id="reg-title")
            yield Label("Session id (blank: generated)")
            yield Input(id="reg-session-id")
            with Horizontal(classes="switch-row"):
                yield Switch(value=False, id="reg-stub")
                yield Label("stub open tool calls (synthetic interrupted results)")
            with Horizontal(classes="switch-row"):
                yield Switch(value=True, id="reg-backup")
                yield Label("back up the store before writing (recommended)")
            with Vertical(id="hermes-group"):
                yield Label("Hermes state.db path (blank: ~/.hermes/state.db)")
                yield Input(id="hermes-db")
                yield Label("Model to store (blank: keep source id — may not route)")
                yield Input(id="hermes-model")
            with Vertical(id="codex-group"):
                yield Label("Project cwd Codex resumes from (required)")
                yield Input(value=self.entry.cwd or "", id="codex-cwd")
                yield Label("Codex home (blank: ~/.codex)")
                yield Input(value=str(app_codex_home) if app_codex_home else "", id="codex-home")
                yield Label("Model (blank: infer most recently used)")
                yield Input(id="codex-model")
                yield Label("Model provider")
                yield Input(value="openai", id="codex-provider")
            yield Static("", id="reg-errors")
            yield Button("Continue to plan", variant="primary", id="reg-continue")
        yield Footer()

    def on_mount(self) -> None:
        self._sync_store("hermes")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "store":
            self._sync_store(str(event.value))

    def _sync_store(self, store: str) -> None:
        self.query_one("#hermes-group").display = store == "hermes"
        self.query_one("#codex-group").display = store == "codex"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter in any form field submits, mirroring OptionsScreen.
        self._continue()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reg-continue":
            self._continue()

    def _continue(self) -> None:
        from .register import CodexRegisterOptions, HermesRegisterOptions

        store = str(self.query_one("#store", Select).value)
        title = self.query_one("#reg-title", Input).value.strip() or None
        session_id = self.query_one("#reg-session-id", Input).value.strip() or None
        stub = self.query_one("#reg-stub", Switch).value
        no_backup = not self.query_one("#reg-backup", Switch).value
        if store == "hermes":
            opts = HermesRegisterOptions(
                source=self.entry.harness,
                path=str(self.entry.path),
                db=self.query_one("#hermes-db", Input).value.strip() or None,
                model=self.query_one("#hermes-model", Input).value.strip() or None,
                title=title,
                session_id=session_id,
                no_backup=no_backup,
                stub_open_calls=stub,
            )
        else:
            cwd = self.query_one("#codex-cwd", Input).value.strip()
            if not cwd:
                self.query_one("#reg-errors", Static).update(
                    "[b red]Codex registration needs the project cwd it will "
                    "resume from[/]"
                )
                return
            opts = CodexRegisterOptions(
                source=self.entry.harness,
                path=str(self.entry.path),
                cwd=cwd,
                codex_home=self.query_one("#codex-home", Input).value.strip() or None,
                title=title,
                model=self.query_one("#codex-model", Input).value.strip() or None,
                model_provider=self.query_one("#codex-provider", Input).value.strip()
                or "openai",
                session_id=session_id,
                no_backup=no_backup,
                stub_open_calls=stub,
            )
        self.app.push_screen(RegisterPlanScreen(store, opts))


class RegisterPlanScreen(Screen):
    """Everything the registration will do, shown BEFORE the SQLite mutation."""

    BINDINGS = [("escape", "back", "Back")]

    def __init__(self, store: str, opts) -> None:
        super().__init__()
        self.store = store
        self.opts = opts
        self.plan = None
        self._writing = False

    def action_back(self) -> None:
        if not self._writing:
            self.app.pop_screen()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static("planning registration (nothing written yet)…", id="plan-body")
        with Horizontal(id="plan-buttons"):
            yield Button("Register", variant="success", id="register", disabled=True)
            yield Button("Cancel", id="plan-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._prepare()

    @work(thread=True, exclusive=True)
    def _prepare(self) -> None:
        from .register import RegisterPlan, prepare_codex_register, prepare_hermes_register

        try:
            if self.store == "hermes":
                plan = prepare_hermes_register(
                    self.opts, hermes_home=getattr(self.app, "hermes_home", None)
                )
            else:
                plan = prepare_codex_register(
                    self.opts, codex_home=getattr(self.app, "codex_home", None)
                )
        except Exception as exc:
            # prepare_* promise never to raise; if that regresses, render the
            # failure rather than crash the terminal.
            plan = RegisterPlan(
                store=self.store, session=None, warnings=[], notes=[],
                session_id=None, db_path=None, model=None, cli_command="",
                opts=self.opts, error=str(exc),
            )
        self.app.call_from_thread(self._render_plan, plan)

    def _render_plan(self, plan) -> None:
        self.plan = plan
        body = self.query_one("#plan-body", Static)
        lines = []
        if plan.error:
            # Error plans still carry the computed loss disclosure — show it,
            # like the CLI prints its conversion notes before failing.
            lines.append(f"[b red]cannot register[/]\n\n{escape(plan.error)}\n")
        else:
            lines += [
                f"[b]store[/]        {self.store} -> {escape(str(plan.db_path))}",
                f"[b]session id[/]   {escape(str(plan.session_id))}",
                f"[b]model[/]        {escape(plan.model or '(source model id)')}",
                "[b]backup[/]       "
                + ("taken before writing" if not self.opts.no_backup else "[yellow]DISABLED[/]"),
            ]
        if plan.warnings:
            lines.append(f"\n[b]{len(plan.warnings)} conversion note(s):[/]")
            lines.extend(f"  [yellow]- {escape(w)}[/]" for w in plan.warnings)
        elif not plan.error:
            lines.append("\n[green]lossless registration (no warnings).[/]")
        for note in plan.notes:
            lines.append(f"[dim]note: {escape(note)}[/]")
        if plan.cli_command:
            lines.append("\n[b]equivalent CLI command:[/]")
            lines.append(f"  [dim]{escape(plan.cli_command)}[/]")
        if plan.error:
            lines.append("\n[dim]escape to go back[/]")
        body.update("\n".join(lines))
        if not plan.error:
            register = self.query_one("#register", Button)
            register.disabled = False
            # Same focus handoff as DryRunScreen: Enter should confirm, not
            # hit the Cancel button that had default focus while disabled.
            register.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plan-cancel":
            self.action_back()
        elif (
            event.button.id == "register"
            and self.plan is not None
            and self.plan.error is None
            and not self._writing
        ):
            self._writing = True
            self.query_one("#register", Button).disabled = True
            self.query_one("#plan-cancel", Button).disabled = True
            self._execute()

    @work(thread=True, exclusive=True)
    def _execute(self) -> None:
        from .register import execute_register

        outcome = execute_register(self.plan)
        self.app.call_from_thread(self.app.push_screen, RegisterResultScreen(outcome))


class RegisterResultScreen(Screen):
    """Outcome of the registration: rows written, backup path, resume hint."""

    BINDINGS = [
        ("n", "new_conversion", "Another session"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, outcome) -> None:
        super().__init__()
        self.outcome = outcome

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static(self._body(), id="reg-result-body")
        yield Footer()

    def _body(self) -> str:
        o = self.outcome
        lines = []
        if o.backup_path:
            lines.append(f"backed up store -> {escape(str(o.backup_path))}")
        if o.error:
            lines.append(f"\n[b red]registration failed:[/] {escape(o.error)}")
        else:
            lines.append(
                f"[green]registered session {escape(str(o.session_id))} "
                f"into {escape(str(o.db_path))}[/]"
            )
            if o.rollout_path:
                lines.append(f"wrote Codex rollout -> {escape(str(o.rollout_path))}")
            if o.resume_hint:
                lines.append(f"\n[b]resume with:[/]  {escape(o.resume_hint)}")
        lines.append("\n[dim]n for another session, q to quit[/]")
        return "\n".join(lines)

    def action_new_conversion(self) -> None:
        while not isinstance(self.app.screen, PickerScreen):
            self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
