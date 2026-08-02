#!/usr/bin/env python3
"""Live acceptance: prove session-bridge works against the REAL harnesses.

The unit suite can only test the session shapes we imagined; every
consequential bug so far (picker invisibility, assistant amnesia, db-only
Hermes sessions, duplicate row keys) lived in the gap between fixtures and
reality. This runner automates the harness-recertification skill:

1. Discovery smoke over the real stores, plus a TUI picker sweep (mounts the
   real app read-only and cursors through rows — the crash class unit
   fixtures miss).
2. For each requested source->target pair: seed a real session in the source
   harness carrying BOTH sentinels (a user magic word and a forced assistant
   ACK), bridge it, live-resume in the target, and require the model to
   quote both. User-turn and assistant-turn recall fail independently.
3. Structural picker checks for codex targets (event_msg user_message in the
   rollout, populated index row).
4. Guaranteed cleanup of every artifact it created, even on failure.

Run it before releases and after any harness updates:

    uv run --extra dev --extra tui python scripts/live_acceptance.py
    uv run ... scripts/live_acceptance.py --pairs codex:claude,hermes:codex
    uv run ... scripts/live_acceptance.py --structure-only   # no LLM calls

Requires the harness CLIs for the pairs you request (claude / codex /
hermes), and vhs for hermes-target recall (hermes -z ignores --resume, so
the interactive TUI is driven headlessly). Missing tools skip their pairs
with a clear reason rather than failing.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESSES = ("claude", "codex", "hermes")
PAIRS_ALL = [(s, t) for s in HARNESSES for t in HARNESSES if s != t]


def log(msg: str) -> None:
    print(f"[live-acceptance] {msg}", flush=True)


def run(cmd: list[str], *, timeout: int = 300, cwd: str | None = None) -> str:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{' '.join(cmd[:3])}... failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()[:400] or proc.stdout.strip()[:400]}"
        )
    return proc.stdout


@dataclass
class Cleanup:
    """Undo ledger: every mutation registers its reversal immediately."""

    actions: list[tuple[str, callable]] = field(default_factory=list)

    def add(self, label: str, fn) -> None:
        self.actions.append((label, fn))

    def run_all(self) -> None:
        for label, fn in reversed(self.actions):
            try:
                fn()
                log(f"cleaned: {label}")
            except Exception as exc:  # cleanup must never mask the real result
                log(f"CLEANUP FAILED ({label}): {exc}")


@dataclass
class Sentinels:
    magic: str  # stated by the user turn
    ack: str  # forced into the assistant turn

    @classmethod
    def fresh(cls) -> "Sentinels":
        tag = f"{random.randrange(16**6):06x}"
        return cls(magic=f"XYZZY-{tag}", ack=f"ACK-{tag}")

    def prompt(self) -> str:
        return (
            f"Reply with exactly this and nothing else: {self.ack}. "
            f"Also, for the record, the magic word is {self.magic}."
        )

    def query(self) -> str:
        return (
            "From this conversation only, in one line: what is the magic "
            "word, and what exact code did YOU reply with earlier?"
        )

    def check(self, reply: str) -> tuple[bool, str]:
        missing = [s for s in (self.magic, self.ack) if s not in reply]
        if not missing:
            return True, "both sentinels recalled"
        return False, f"missing {missing} in reply: {reply.strip()[:200]!r}"


@dataclass
class Seed:
    harness: str
    transcript: Path  # a JSONL file session-bridge can read (--from <harness>)
    sentinels: Sentinels


class Env:
    def __init__(self, bridge: str, hermes_model: str | None):
        self.bridge = bridge
        self.hermes_model = hermes_model
        self.have = {h: shutil.which(h) is not None for h in HARNESSES}
        self.have_vhs = shutil.which("vhs") is not None
        self.claude_home = Path.home() / ".claude"
        self.codex_home = Path.home() / ".codex"
        self.hermes_home = Path.home() / ".hermes"
        self.hermes_db = self.hermes_home / "state.db"
        self.scratch = Path(tempfile.mkdtemp(prefix="sb-live-acceptance-"))

    def bridge_cmd(self, *args: str) -> list[str]:
        return [self.bridge, *args]


# ---------------------------------------------------------------- discovery


def discovery_smoke(env: Env) -> tuple[bool, str]:
    """Real-store discovery + a cursor sweep through the real picker."""
    sys.path.insert(0, str(REPO / "src"))
    from session_bridge.tui.discovery import discover_sessions

    t0 = time.time()
    entries = discover_sessions()
    took = time.time() - t0
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.harness] = counts.get(e.harness, 0) + 1
    detail = f"{len(entries)} sessions {counts} in {took:.2f}s"
    if not entries:
        return False, f"no sessions discovered at all ({detail})"
    if took > 5:
        return False, f"discovery too slow: {detail}"

    try:
        import asyncio

        from session_bridge.tui.app import SessionBridgeApp
        from textual.widgets import DataTable
    except ImportError:
        return True, detail + " (textual not installed; picker sweep skipped)"

    async def sweep() -> str:
        app = SessionBridgeApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause(1.5)
            table = app.screen.query_one(DataTable)
            if table.row_count != len(entries):
                return f"picker shows {table.row_count} rows, discovery found {len(entries)}"
            table.focus()
            # Cursor through a real slice of rows: exercises row keying and
            # the detail pane against real data shapes.
            for _ in range(min(30, table.row_count - 1)):
                await pilot.press("down")
            await pilot.pause(0.3)
            return ""

    problem = asyncio.run(sweep())
    if problem:
        return False, problem
    return True, detail + " + picker sweep (30 rows)"


# ------------------------------------------------------------------ seeding


def seed_claude(env: Env, cleanup: Cleanup) -> Seed:
    s = Sentinels.fresh()
    cwd = env.scratch / "seed-claude"
    cwd.mkdir(parents=True)
    run(["claude", "-p", s.prompt()], cwd=str(cwd), timeout=300)
    encoded = str(cwd.resolve()).replace("/", "-")
    project = env.claude_home / "projects" / encoded
    transcripts = sorted(project.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not transcripts:
        raise RuntimeError(f"claude -p left no transcript under {project}")
    cleanup.add(f"claude seed project {project.name}", lambda: shutil.rmtree(project))
    return Seed("claude", transcripts[-1], s)


def seed_codex(env: Env, cleanup: Cleanup) -> Seed:
    s = Sentinels.fresh()
    before = {
        p for p in env.codex_home.glob("sessions/*/*/*/rollout-*.jsonl")
    }
    # Run from the repo (a trusted dir) so codex exec doesn't stall on the
    # directory-trust prompt.
    run(["codex", "exec", s.prompt()], cwd=str(REPO), timeout=300)
    new = [
        p
        for p in env.codex_home.glob("sessions/*/*/*/rollout-*.jsonl")
        if p not in before
    ]
    if not new:
        raise RuntimeError("codex exec left no new rollout")
    rollout = max(new, key=lambda p: p.stat().st_mtime)
    sid = rollout.stem.split("-", 7)[-1] if "-" in rollout.stem else None
    match = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27,})$", rollout.stem)
    sid = match.group(1) if match else sid

    def _cleanup() -> None:
        rollout.unlink(missing_ok=True)
        if sid:
            conn = sqlite3.connect(env.codex_home / "state_5.sqlite")
            conn.execute("DELETE FROM threads WHERE id = ?", (sid,))
            conn.commit()
            conn.close()

    cleanup.add(f"codex seed {rollout.name}", _cleanup)
    return Seed("codex", rollout, s)


def seed_hermes(env: Env, cleanup: Cleanup) -> Seed:
    s = Sentinels.fresh()
    before_ids = _hermes_session_ids(env)
    run(["hermes", "-z", s.prompt()], timeout=300)
    new_ids = _hermes_session_ids(env) - before_ids
    if not new_ids:
        raise RuntimeError("hermes -z left no new session in state.db")
    sid = sorted(new_ids)[-1]

    def _cleanup() -> None:
        conn = sqlite3.connect(env.hermes_db)
        conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        conn.commit()
        conn.close()

    cleanup.add(f"hermes seed {sid}", _cleanup)
    export = env.scratch / f"hermes-seed-{sid}.jsonl"
    run(env.bridge_cmd("export-hermes", sid, "--db", str(env.hermes_db), "-o", str(export)))
    return Seed("hermes", export, s)


def _hermes_session_ids(env: Env) -> set[str]:
    conn = sqlite3.connect(f"file:{env.hermes_db}?mode=ro", uri=True)
    try:
        return {row[0] for row in conn.execute("SELECT id FROM sessions")}
    finally:
        conn.close()


SEEDERS = {"claude": seed_claude, "codex": seed_codex, "hermes": seed_hermes}
FROM_NAME = {"claude": "claude-code", "codex": "codex", "hermes": "hermes"}


# -------------------------------------------------------------------- pairs


def bridge_to_claude(env: Env, seed: Seed, cleanup: Cleanup, llm: bool) -> str:
    cwd = env.scratch / f"target-claude-{seed.harness}"
    cwd.mkdir(parents=True, exist_ok=True)
    run(
        env.bridge_cmd(
            "convert", "--from", FROM_NAME[seed.harness], str(seed.transcript),
            "--to", "claude-code", "-o", str(env.scratch / "discard.jsonl"),
            "--stub-open-calls", "--place-claude-cwd", str(cwd),
        )
    )
    # The resume hint goes to stderr; derive the placed id from the project
    # dir instead (exactly one fresh transcript).
    encoded = str(cwd.resolve()).replace("/", "-")
    project = env.claude_home / "projects" / encoded
    cleanup.add(f"claude placement {project.name}", lambda: shutil.rmtree(project, ignore_errors=True))
    transcripts = list(project.glob("*.jsonl"))
    if len(transcripts) != 1:
        return f"FAIL: expected 1 placed transcript, found {len(transcripts)}"
    session_id = transcripts[0].stem
    if not llm:
        return "PASS (structure only: placed transcript exists)"
    # One retry: claude's project index can lag a placement by a beat.
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            reply = run(
                ["claude", "-p", "--resume", session_id, seed.sentinels.query()],
                cwd=str(cwd), timeout=300,
            )
            break
        except RuntimeError as exc:
            last_exc = exc
            time.sleep(3)
    else:
        return f"FAIL: {last_exc}"
    ok, why = seed.sentinels.check(reply)
    return f"PASS ({why})" if ok else f"FAIL: {why}"


def bridge_to_codex(env: Env, seed: Seed, cleanup: Cleanup, llm: bool) -> str:
    out = run(
        env.bridge_cmd(
            "register-codex", "--from", FROM_NAME[seed.harness], str(seed.transcript),
            "--cwd", str(REPO), "--title", "live-acceptance-disposable",
            "--stub-open-calls", "--no-backup",
        )
    )
    match = re.search(r"registered session ([0-9a-f-]{36})", out)
    if not match:
        return f"FAIL: no session id in register-codex output: {out[:200]!r}"
    sid = match.group(1)

    def _cleanup() -> None:
        conn = sqlite3.connect(env.codex_home / "state_5.sqlite")
        row = conn.execute(
            "SELECT rollout_path FROM threads WHERE id = ?", (sid,)
        ).fetchone()
        if row and os.path.exists(row[0]):
            os.unlink(row[0])
        conn.execute("DELETE FROM threads WHERE id = ?", (sid,))
        conn.commit()
        conn.close()

    cleanup.add(f"codex registration {sid}", _cleanup)

    # Structural picker requirements (the class of bug live testing caught):
    conn = sqlite3.connect(f"file:{env.codex_home / 'state_5.sqlite'}?mode=ro", uri=True)
    row = conn.execute(
        "SELECT rollout_path, preview, first_user_message FROM threads WHERE id = ?",
        (sid,),
    ).fetchone()
    conn.close()
    if not row:
        return f"FAIL: no threads row for {sid} (register output: {out[:150]!r})"
    if not (row[1] or "").strip():
        return f"FAIL: preview column empty for {sid} (picker requirement)"
    rollout_records = [json.loads(l) for l in open(row[0])]
    if not any(
        r.get("type") == "event_msg" and r.get("payload", {}).get("type") == "user_message"
        for r in rollout_records
    ):
        return "FAIL: rollout lacks event_msg user_message (picker requirement)"
    if not llm:
        return "PASS (structure only: row + picker requirements)"
    reply = run(
        ["codex", "exec", "resume", sid, seed.sentinels.query()],
        cwd=str(REPO), timeout=300,
    )
    ok, why = seed.sentinels.check(reply)
    return f"PASS ({why})" if ok else f"FAIL: {why}"


def bridge_to_hermes(env: Env, seed: Seed, cleanup: Cleanup, llm: bool) -> str:
    model = env.hermes_model or _newest_hermes_model(env)
    if not model:
        return "SKIP: no routable hermes model found (pass --hermes-model)"
    out = run(
        env.bridge_cmd(
            "register", "--from", FROM_NAME[seed.harness], str(seed.transcript),
            "--model", model, "--title", f"live-acceptance-{seed.sentinels.ack}",
            "--stub-open-calls", "--no-backup",
        )
    )
    match = re.search(r"registered session (sb_[0-9a-f_]+)", out)
    if not match:
        return f"FAIL: no session id in register output: {out[:200]!r}"
    sid = match.group(1)

    def _cleanup() -> None:
        conn = sqlite3.connect(env.hermes_db)
        conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        conn.commit()
        conn.close()

    cleanup.add(f"hermes registration {sid}", _cleanup)
    if not llm:
        return "PASS (structure only: rows registered)"
    if not env.have_vhs:
        return "SKIP: vhs required for hermes recall (hermes -z ignores --resume)"

    # hermes -z silently ignores --resume, so drive the real TUI headlessly
    # and read the terminal text back.
    txt = env.scratch / f"hermes-reply-{sid}.txt"
    tape = env.scratch / f"hermes-{sid}.tape"
    tape.write_text(
        "\n".join(
            [
                f'Output "{txt}"',
                "Set Width 1400",
                "Set Height 2000",  # tall: keep the whole reply on the final frame
                f'Type "hermes --resume {sid}"',
                "Enter",
                "Sleep 20s",  # skills + TUI startup take a while
                f'Type "{seed.sentinels.query()}"',
                "Sleep 1s",
                "Enter",
                "Sleep 75s",  # model reply
                "Ctrl+C",  # leave no lingering hermes process
                "Sleep 1s",
                "Ctrl+C",
                "Sleep 1s",
            ]
        )
        + "\n"
    )
    run(["vhs", str(tape)], timeout=300)
    reply = txt.read_text(encoding="utf-8", errors="replace") if txt.exists() else ""
    ok, why = seed.sentinels.check(reply)
    verdict = f"PASS (model {model}; {why})" if ok else f"FAIL (model {model}): {why}"
    return verdict


BRIDGERS = {"claude": bridge_to_claude, "codex": bridge_to_codex, "hermes": bridge_to_hermes}


def _newest_hermes_model(env: Env) -> str | None:
    if not env.hermes_db.is_file():
        return None
    conn = sqlite3.connect(f"file:{env.hermes_db}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT model FROM sessions WHERE model IS NOT NULL AND model != '' "
            "AND id NOT LIKE 'sb_%' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# --------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs",
        help="comma-separated source:target pairs (harnesses: claude, codex, "
        "hermes); default: every pair whose tools are installed",
    )
    parser.add_argument(
        "--structure-only",
        action="store_true",
        help="skip LLM resume calls; verify placement/registration structure only",
    )
    parser.add_argument("--binary", default="session-bridge", help="session-bridge to test")
    parser.add_argument("--hermes-model", help="routable model for hermes registrations")
    parser.add_argument("--keep", action="store_true", help="skip cleanup (debugging)")
    args = parser.parse_args()

    env = Env(args.binary, args.hermes_model)
    version = run(env.bridge_cmd("--version")).strip()
    log(f"testing {version} ({shutil.which(args.binary)})")
    log(f"harness CLIs: " + ", ".join(f"{h}={'yes' if v else 'NO'}" for h, v in env.have.items()))

    if args.pairs:
        pairs = []
        for item in args.pairs.split(","):
            s, t = item.strip().split(":")
            if s not in HARNESSES or t not in HARNESSES or s == t:
                parser.error(f"bad pair: {item}")
            pairs.append((s, t))
    else:
        pairs = [(s, t) for s, t in PAIRS_ALL if env.have[s] and env.have[t]]

    results: dict[str, str] = {}
    ok, detail = discovery_smoke(env)
    results["discovery+picker"] = ("PASS: " if ok else "FAIL: ") + detail
    log(results["discovery+picker"])

    cleanup = Cleanup()
    seeds: dict[str, Seed] = {}
    try:
        for source in {s for s, _ in pairs}:
            if not env.have[source]:
                continue
            log(f"seeding {source} session with dual sentinels...")
            try:
                seeds[source] = SEEDERS[source](env, cleanup)
            except Exception as exc:
                results[f"seed {source}"] = f"FAIL: {exc}"
                log(results[f"seed {source}"])

        for source, target in pairs:
            name = f"{source} -> {target}"
            if source not in seeds:
                results[name] = f"SKIP: no {source} seed"
                continue
            log(f"pair {name} ...")
            try:
                results[name] = BRIDGERS[target](
                    env, seeds[source], cleanup, llm=not args.structure_only
                )
            except Exception as exc:
                results[name] = f"FAIL: {exc}"
            log(f"{name}: {results[name]}")
    finally:
        if args.keep:
            log(f"--keep: artifacts left in place; scratch at {env.scratch}")
        else:
            cleanup.run_all()
            shutil.rmtree(env.scratch, ignore_errors=True)

    print("\n=== live acceptance report ===")
    width = max(len(k) for k in results)
    failed = False
    for name, result in results.items():
        print(f"  {name:<{width}}  {result}")
        failed = failed or result.startswith("FAIL")
    print("==============================")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
