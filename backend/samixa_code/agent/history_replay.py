"""Reconstructs frontend-displayable timeline items from a stored
ChatMessage history (pass history WITHOUT the leading system message).

Needed because a stored assistant message's `content` is the model's RAW
output (thinking + tool-call tags) -- exactly what the live turn already
parsed once and sent to the frontend as separate events, but that parsed
shape isn't itself persisted. So loading history re-parses each assistant
message the same way client.py does live, and pairs each recovered tool_call
with the "tool" messages that follow it POSITIONALLY, not by id:
toolcall_parser.py mints a fresh random id on every parse, so a re-parsed
call's id will never match the id that was live at the time. Order IS a
stable correspondence -- _execute_one appends tool results in the same order
the tool_calls were parsed, immediately after their assistant message, before
anything else can be appended.
"""

from __future__ import annotations

import uuid
from typing import Any

from samixa_code.llm.toolcall_parser import parse_assistant_content
from samixa_code.llm.types import ChatMessage


def history_to_display_items(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    i = 0
    while i < len(messages):
        message = messages[i]

        if message.role == "user":
            items.append({"kind": "user", "id": f"user-{uuid.uuid4().hex[:8]}", "text": message.content})
            i += 1
            continue

        if message.role == "assistant":
            parsed = parse_assistant_content(message.content)
            if parsed.text or parsed.thinking:
                items.append(
                    {
                        "kind": "assistant",
                        "id": f"assistant-{uuid.uuid4().hex[:8]}",
                        "text": parsed.text,
                        "thinking": parsed.thinking,
                    }
                )
            i += 1
            for call in parsed.tool_calls:
                if i < len(messages) and messages[i].role == "tool":
                    tool_message = messages[i]
                    items.append(
                        {
                            "kind": "tool",
                            "id": f"tool-{uuid.uuid4().hex[:8]}",
                            "name": tool_message.name or call.name,
                            "arguments": call.arguments,
                            "content": tool_message.content,
                            "is_error": tool_message.is_error,
                        }
                    )
                    i += 1
                else:
                    # Stored history is missing this call's result (shouldn't
                    # happen given the append ordering, but never crash a
                    # reload over it) -- show the call as still pending.
                    items.append(
                        {
                            "kind": "tool",
                            "id": f"tool-{uuid.uuid4().hex[:8]}",
                            "name": call.name,
                            "arguments": call.arguments,
                            "content": None,
                            "is_error": False,
                        }
                    )
            continue

        # Orphaned "tool" message with no preceding assistant tool_call
        # (shouldn't happen; skip rather than crash a reload over it).
        i += 1

    return items
