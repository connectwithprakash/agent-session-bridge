"""The install-skill bootstrap: link/copy the packaged skill into harness homes."""

from pathlib import Path

from session_bridge.cli import main
from session_bridge.skill_install import (
    SKILL_NAME,
    install_skill,
    packaged_skill_dir,
)


def _homes(tmp_path, *existing):
    homes = {
        "claude-code": tmp_path / ".claude",
        "codex": tmp_path / ".codex",
        "hermes": tmp_path / ".hermes",
    }
    for name in existing:
        homes[name].mkdir()
    return homes


def test_packaged_skill_ships_with_the_package():
    src = packaged_skill_dir()
    assert (src / "SKILL.md").is_file()
    text = (src / "SKILL.md").read_text(encoding="utf-8")
    assert "session-handoff" in text and "register-codex" in text


def test_links_into_existing_homes_and_skips_missing(tmp_path):
    homes = _homes(tmp_path, "claude-code", "hermes")  # no .codex
    results = {r.harness: r for r in install_skill(homes)}
    assert results["claude-code"].action == "linked"
    assert results["hermes"].action == "linked"
    assert results["codex"].action == "skipped"
    link = homes["claude-code"] / "skills" / SKILL_NAME
    assert link.is_symlink()
    assert (link / "SKILL.md").is_file()  # resolves through the link


def test_idempotent_second_run_is_up_to_date(tmp_path):
    homes = _homes(tmp_path, "claude-code")
    install_skill(homes)
    results = {r.harness: r for r in install_skill(homes)}
    assert results["claude-code"].action == "up-to-date"


def test_refuses_to_replace_foreign_skill_without_force(tmp_path):
    homes = _homes(tmp_path, "claude-code")
    foreign = homes["claude-code"] / "skills" / SKILL_NAME
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("someone else's skill", encoding="utf-8")
    results = {r.harness: r for r in install_skill(homes)}
    assert results["claude-code"].action == "error"
    assert "--force" in results["claude-code"].detail
    # untouched
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "someone else's skill"

    forced = {r.harness: r for r in install_skill(homes, force=True)}
    assert forced["claude-code"].action == "linked"


def test_copy_mode_copies_content_and_is_idempotent(tmp_path):
    homes = _homes(tmp_path, "codex")
    results = {r.harness: r for r in install_skill(homes, copy=True)}
    assert results["codex"].action == "copied"
    target = homes["codex"] / "skills" / SKILL_NAME
    assert not target.is_symlink()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == (
        packaged_skill_dir() / "SKILL.md"
    ).read_text(encoding="utf-8")
    again = {r.harness: r for r in install_skill(homes, copy=True)}
    assert again["codex"].action == "up-to-date"


def test_missing_source_reports_error_not_raise(tmp_path):
    homes = _homes(tmp_path, "claude-code")
    results = install_skill(homes, source=tmp_path / "nope")
    assert results[0].action == "error"


def test_cli_install_skill_subcommand_registered():
    from session_bridge.cli import build_parser

    args = build_parser().parse_args(["install-skill", "--copy", "--force"])
    assert args.func.__name__ == "cmd_install_skill"
    assert args.copy and args.force
