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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "continue":
            return
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
        self.query_one("#write", Button).disabled = False

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
