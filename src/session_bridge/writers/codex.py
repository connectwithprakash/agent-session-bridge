"""Writer: IR -> Codex rollout JSONL.

Emits ``{timestamp, type, payload}`` records: a ``session_meta`` (with
base_instructions), a ``turn_context`` (model + approval policy), then
``response_item`` records in the OpenAI Responses shape (message / reasoning /
function_call / function_call_output).
"""

from __future__ import annotations

import json
from typing import Any

from ..ir import BlockType, ConversionReport, Role, Session
from ._common import ERROR_MARKER, report_losses, tool_result_text


_ROLE_TO_CODEX = {Role.USER: "user", Role.ASSISTANT: "assistant", Role.SYSTEM: "system"}


def _codex_role(role: Role) -> str:
    return _ROLE_TO_CODEX.get(role, "user")


def _msg_payload(role: str, text: str) -> dict[str, Any]:
    if role == "assistant":
        # Codex's history reconstruction keeps assistant messages by channel
        # phase; without this the resumed model sees only the user turns.
        block_type = "output_text"
        return {
            "type": "message",
            "role": role,
            "content": [{"type": block_type, "text": text}],
            "phase": "final_answer",
        }
    # Assistant emits output_text; user/system emit input_text.
    block_type = "output_text" if role == "assistant" else "input_text"
    return {"type": "message", "role": role, "content": [{"type": block_type, "text": text}]}


def workspace_write_policies(cwd: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return matching Codex transcript and thread-store sandbox policies."""
    entries = [
        {"path": {"type": "special", "value": {"kind": "root"}}, "access": "read"},
        {"path": {"type": "path", "path": cwd}, "access": "write"},
        {"path": {"type": "special", "value": {"kind": "slash_tmp"}}, "access": "write"},
        {"path": {"type": "special", "value": {"kind": "tmpdir"}}, "access": "write"},
        {"path": {"type": "path", "path": f"{cwd}/.git"}, "access": "read"},
        {"path": {"type": "path", "path": f"{cwd}/.agents"}, "access": "read"},
        {"path": {"type": "path", "path": f"{cwd}/.codex"}, "access": "read"},
    ]
    return (
        {
            "type": "workspace-write",
            "network_access": False,
            "exclude_tmpdir_env_var": False,
            "exclude_slash_tmp": False,
        },
        {"type": "managed", "file_system": {"type": "restricted", "entries": entries}, "network": "restricted"},
    )


def write_codex(
    session: Session,
    *,
    timestamp: str = "2000-01-01T00:00:00.000Z",
    approval_policy: str | None = None,
    sandbox_policy: dict[str, Any] | None = None,
    file_system_sandbox_policy: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], ConversionReport]:
    """Render the IR into a Codex rollout.

    ``timestamp`` is the ISO time stamped on session_meta. Codex treats a rollout
    whose session_meta lacks a valid top-level timestamp as empty and refuses to
    resume it, so a non-null value is required; the caller should pass the real
    current time (scripts cannot call the clock directly).
    """
    report = report_losses(session, "codex")
    records: list[dict[str, Any]] = [
        {
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {
                # Real Codex session_meta carries both session_id and id (same
                # value); resume/discovery keys on these, so emit both.
                "session_id": session.meta.session_id,
                "id": session.meta.session_id,
                "timestamp": timestamp,
                "cwd": session.meta.cwd,
                "originator": "codex-cli",
                "cli_version": session.meta.version or "0.145.0",
                "source": "cli",
                "thread_source": "user",
                "model_provider": session.meta.model_provider or "openai",
                "base_instructions": {"text": session.meta.system_instructions or ""},
            },
        },
        {
            "timestamp": None,
            "type": "turn_context",
            "payload": {
                "turn_id": "t1",
                "model": session.meta.model or "unknown",
                "cwd": session.meta.cwd,
                "approval_policy": approval_policy or session.meta.permission_mode or "on-request",
                "sandbox_policy": sandbox_policy,
                "file_system_sandbox_policy": file_system_sandbox_policy,
            },
        },
    ]

    def add(payload: dict[str, Any], ts: Any) -> None:
        records.append({"timestamp": ts, "type": "response_item", "payload": payload})

    for msg in session.messages:
        ts = msg.timestamp
        role = _codex_role(msg.role)
        emitted = False
        # Single ordered pass. Coalesce only ADJACENT TEXT/RAW blocks into one
        # message record (so consecutive text doesn't inflate the turn count) and
        # flush that buffer when a non-text block interrupts — this preserves the
        # original block order (e.g. reasoning -> text -> tool_call) instead of
        # hoisting all text to the front.
        text_buf: list[str] = []

        def flush_text() -> None:
            nonlocal emitted
            if text_buf:
                add(_msg_payload(role, "\n".join(text_buf)), ts)
                text_buf.clear()
                emitted = True

        for b in msg.content:
            if b.type is BlockType.TEXT or b.type is BlockType.RAW:
                text_buf.append(b.text or "")
            elif b.type is BlockType.REASONING:
                flush_text()
                add({"type": "reasoning", "summary": [{"type": "summary_text", "text": b.text or ""}]}, ts)
                emitted = True
            elif b.type is BlockType.TOOL_CALL:
                flush_text()
                add(
                    {
                        "type": "function_call",
                        "name": b.tool_name,
                        "arguments": json.dumps(b.tool_input or {}),
                        "call_id": b.call_id,
                    },
                    ts,
                )
                emitted = True
            elif b.type is BlockType.TOOL_RESULT:
                flush_text()
                output = tool_result_text(b)  # placeholder for parts-only results
                if b.is_error:
                    output = ERROR_MARKER + output
                add({"type": "function_call_output", "call_id": b.call_id, "output": output}, ts)
                emitted = True
        flush_text()
        # Preserve an otherwise-empty message so message count survives the round trip.
        if not emitted and msg.role in (Role.USER, Role.ASSISTANT, Role.SYSTEM):
            add(_msg_payload(role, ""), ts)
        # Codex writes an event_msg twin for every user turn, and its resume
        # picker only lists sessions whose rollout contains at least one
        # user_message event — without this the imported session resumes by
        # id but never appears in the picker. The reader ignores event_msg
        # as a response_item duplicate, so round-trips are unaffected.
        if msg.role is Role.USER:
            user_text = msg.text()
            if user_text.strip():
                records.append(
                    {
                        "timestamp": ts,
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": user_text,
                            "images": [],
                            "local_images": [],
                            "audio": [],
                            "local_audio": [],
                            "text_elements": [],
                        },
                    }
                )
        elif msg.role is Role.ASSISTANT:
            # Same twin discipline for assistant turns: the transcript view
            # renders from event_msg records, so without agent_message events
            # a resumed session displays as user-messages-only.
            assistant_text = msg.text()
            if assistant_text.strip():
                records.append(
                    {
                        "timestamp": ts,
                        "type": "event_msg",
                        "payload": {
                            "type": "agent_message",
                            "message": assistant_text,
                            "phase": "final_answer",
                            "memory_citation": None,
                        },
                    }
                )

    return records, report
