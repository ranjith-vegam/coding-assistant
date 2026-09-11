"""Shapes shared between the model-orchestrator client and the agent loop.

The orchestrator's /v1/chat/completions is OpenAI-shaped for messages/tools in
the *request*, but the *response* is not: tool calls and reasoning both arrive
as plain text inside `message.content` (see toolcall_parser.py for why and how
we recover structure from that). These types represent the *normalized* result
our own code works with, after parsing -- not the raw wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ChatMessage:
    """One turn we send to (or replay from) the orchestrator.

    `content` is always a plain string on the way in -- the orchestrator's
    ChatMessage schema accepts a list for multi-part content too, but we never
    send that; text in, text out keeps the tool-call/thinking parsing tractable.
    """

    role: Role
    content: str
    # Set only on role="tool" messages: which tool call this is a result for.
    # The orchestrator has no native concept of this (no tool_call_id in its
    # schema) so we fold it into the text we send -- see client.py.
    tool_call_id: str | None = None
    name: str | None = None
    # Set only on role="tool" messages. Not needed for the live turn (the
    # WebSocket event that carried this result already told the frontend),
    # but IS needed to durably reconstruct a tool card's status when a stored
    # chat is reloaded from Redis after a VS Code restart -- see chat_store.py
    # and agent/history_replay.py.
    is_error: bool = False


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        """OpenAI-style function-tool shape for the request body."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ParsedToolCall:
    """One <tool_call> block, recovered from raw assistant text."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw: str  # the original tag text -- kept for logging/replay/debugging


@dataclass
class ParsedAssistantMessage:
    """The result of parsing one raw orchestrator response.

    `thinking` and `tool_calls` are both best-effort recoveries from an
    unstructured text blob -- treat them as such, not as guaranteed-correct
    structure. `possibly_truncated` flags the one failure mode worth acting on:
    a response that was cut off (e.g. hit max_tokens) mid tool-call, which the
    agent loop should retry rather than silently misinterpret as "no tool call".
    """

    thinking: str | None
    text: str
    tool_calls: list[ParsedToolCall] = field(default_factory=list)
    possibly_truncated: bool = False
    # The untouched `message.content` string this was parsed from. When a
    # turn made tool calls, replay THIS (not a reconstruction from `text`/
    # `tool_calls`) as that assistant turn's content in the next request --
    # the model's chat template expects to see its own tags verbatim, and we
    # can't guarantee our parse round-trips byte-for-byte.
    raw: str = ""
    # From the response's own `usage` block -- REAL token counts, not our
    # char-based guess. Confirmed live (2026-09-10) that our estimate can be
    # off by ~3x on tool-enabled calls (the chat template's tool-calling
    # preamble is invisible to us and isn't reflected in a naive char count).
    # token_budget.py's calibration uses this ground truth to self-correct
    # rather than trusting a static fudge factor. None if the response had no
    # usage block.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class EmbeddingResult:
    dense: list[float]
    sparse: dict[str, float]
