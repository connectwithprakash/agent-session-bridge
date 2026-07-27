"""Session summary rows for the TUI detail pane.

Produces the same fields as ``cli.cmd_inspect``, but as (label, value) string
pairs a two-column table widget can render directly. Values are formatted
identically to the CLI output (e.g. the model line embeds the provider) so the
TUI and ``session-bridge inspect`` never disagree about a session; tests pin
this parity by checking every value here against the CLI's stdout.

This module must stay importable without textual: it is pure data shaping, so
the CLI-only install can reuse it and the tests need no TUI dependency.
"""

from __future__ import annotations

from ..ir import BlockType, Session


def _count_blocks(session: Session, block_type: BlockType) -> int:
    return sum(1 for m in session.messages for b in m.content if b.type is block_type)


def summarize_session(session: Session) -> list[tuple[str, str]]:
    """Return label/value rows mirroring ``session-bridge inspect`` output."""
    m = session.meta
    p = session.pending
    return [
        ("source harness", str(m.source_harness)),
        ("session id", str(m.session_id)),
        ("model", f"{m.model}  (provider: {m.model_provider})"),
        ("cwd", str(m.cwd)),
        ("permission", str(m.permission_mode)),
        ("messages", str(len(session.messages))),
        ("text blocks", str(_count_blocks(session, BlockType.TEXT))),
        ("reasoning", str(_count_blocks(session, BlockType.REASONING))),
        ("tool calls", str(_count_blocks(session, BlockType.TOOL_CALL))),
        ("tool results", str(_count_blocks(session, BlockType.TOOL_RESULT))),
        ("tool schemas", str(len(session.tools))),
        ("open tool calls", str(list(p.open_tool_calls))),
        ("queued user input", str(len(p.queued_user_messages))),
        ("active goal", str(p.active_goal or "-")),
    ]
