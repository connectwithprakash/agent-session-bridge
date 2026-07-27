"""Bootstrap the packaged agent skill into every harness on this machine.

Harnesses that support the SKILL.md convention read from a per-user skills
directory (``~/.claude/skills``, ``~/.codex/skills``, ``~/.hermes/skills``).
``install_skill`` links (or copies) the packaged ``session-handoff`` skill
into each harness home that actually exists, so one install command makes the
handoff instructions available everywhere — the agent-skills bootstrap
pattern.

Symlink is the default (the skill tracks the installed package; re-installing
session-bridge updates every harness at once); ``copy`` decouples the skill
from the package at the cost of going stale. Existing foreign files are never
silently replaced — that requires ``force``, matching the no-silent-overwrite
rule everywhere else in this codebase.
"""

from __future__ import annotations

import filecmp
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

SKILL_NAME = "session-handoff"

#: Default per-user home of each supported harness. A harness is "available"
#: when this directory exists; its skills dir is created on demand.
HARNESS_HOMES: dict[str, str] = {
    "claude-code": "~/.claude",
    "codex": "~/.codex",
    "hermes": "~/.hermes",
}


def packaged_skill_dir() -> Path:
    """Filesystem path of the skill shipped inside this package."""
    from importlib.resources import files

    return Path(str(files("session_bridge") / "skills" / SKILL_NAME))


@dataclass(frozen=True)
class InstallResult:
    harness: str
    target: Path | None
    action: str  # "linked" | "copied" | "up-to-date" | "skipped" | "error"
    detail: str


def _is_current(target: Path, source: Path) -> bool:
    """Already installed and pointing at (or identical to) this source?"""
    if target.is_symlink():
        try:
            return target.resolve() == source.resolve()
        except OSError:
            return False
    manifest = target / "SKILL.md"
    if manifest.is_file():
        try:
            return filecmp.cmp(manifest, source / "SKILL.md", shallow=False)
        except OSError:
            return False
    return False


def install_skill(
    harness_homes: dict[str, Path],
    *,
    source: Path | None = None,
    copy: bool = False,
    force: bool = False,
) -> list[InstallResult]:
    """Install the packaged skill into each existing harness home.

    Never raises for a single harness: each one reports its own outcome so
    one broken home cannot abort the others.
    """
    src = source if source is not None else packaged_skill_dir()
    results: list[InstallResult] = []
    if not (src / "SKILL.md").is_file():
        return [
            InstallResult(
                harness="*",
                target=None,
                action="error",
                detail=f"packaged skill not found at {src}",
            )
        ]

    for harness, home in harness_homes.items():
        home = Path(home).expanduser()
        if not home.is_dir():
            results.append(
                InstallResult(harness, None, "skipped", f"{home} does not exist")
            )
            continue
        target = home / "skills" / SKILL_NAME
        try:
            if target.is_symlink() or target.exists():
                if _is_current(target, src):
                    results.append(
                        InstallResult(harness, target, "up-to-date", str(target))
                    )
                    continue
                if not force:
                    results.append(
                        InstallResult(
                            harness,
                            target,
                            "error",
                            f"{target} already exists and differs; "
                            "re-run with --force to replace it",
                        )
                    )
                    continue
                if target.is_symlink() or target.is_file():
                    target.unlink()
                else:
                    shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if copy:
                shutil.copytree(src, target)
                results.append(InstallResult(harness, target, "copied", str(target)))
            else:
                os.symlink(src.resolve(), target, target_is_directory=True)
                results.append(
                    InstallResult(
                        harness, target, "linked", f"{target} -> {src.resolve()}"
                    )
                )
        except OSError as exc:
            results.append(InstallResult(harness, target, "error", str(exc)))
    return results
