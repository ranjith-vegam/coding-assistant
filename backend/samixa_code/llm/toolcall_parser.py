"""Recover structure from the orchestrator's raw completion text.

Confirmed by hand against the real model-orchestrator (2026-09-09/10, model
Qwen3.8-27B, http://192.168.0.99:9900):

  1. Thinking mode is on by default and NOT split into its own field. A
     response looks like:
         "We need answer user...\n</think>\n\nHello there friend"
     i.e. reasoning text, then a bare `</think>` marker (no matching opening
     tag observed in practice), then the real answer.

  2. Tool calls are NOT returned as `message.tool_calls` / `finish_reason:
     "tool_calls"` the way a real OpenAI-compatible server would -- the
     orchestrator passes the model's native Hermes-style tags straight through
     as plain text inside `content`, and finish_reason stays "stop" even when
     a tool call is present:
         "...\n</think>\n\n<tool_call>\n<function=read_file>\n"
         "<parameter=path>\n/tmp/foo.txt\n</parameter>\n</function>\n</tool_call>"

  This is permanent, by design (model-orch is a shared multi-client service
  and won't parse tool calls for us -- confirmed with the user 2026-09-10),
  not a temporary gap -- so this module is load-bearing for the whole agent
  loop, not a stopgap. Treat changes to it with the same care as a wire
  protocol, and keep its test fixtures pinned to real captured responses.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

from samixa_code.llm.types import ParsedAssistantMessage, ParsedToolCall

_THINK_CLOSE = "</think>"
_THINK_OPEN = "<think>"

_TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FUNCTION_RE = re.compile(r"<function\s*=\s*([^>]+?)\s*>(.*?)</function>", re.DOTALL)
_PARAMETER_RE = re.compile(r"<parameter\s*=\s*([^>]+?)\s*>(.*?)</parameter>", re.DOTALL)

# Any of these appearing in the leftover text (after removing well-formed
# <tool_call>...</tool_call> blocks) means the generation was probably cut off
# mid tool-call -- e.g. hit max_tokens before the closing tag arrived.
_TRUNCATION_MARKERS = ("<tool_call>", "<function=", "<parameter=")


def _split_thinking(raw: str) -> tuple[str | None, str]:
    """Split off a leading reasoning block, if one is present.

    Only `</think>` is guaranteed to appear in practice (see module docstring)
    so that's what we key off of; an opening `<think>` is stripped too when
    present, but its absence is not treated as "no thinking happened".
    """
    idx = raw.find(_THINK_CLOSE)
    if idx == -1:
        return None, raw
    thinking = raw[:idx]
    if thinking.startswith(_THINK_OPEN):
        thinking = thinking[len(_THINK_OPEN) :]
    thinking = thinking.strip()
    remainder = raw[idx + len(_THINK_CLOSE) :]
    return (thinking or None), remainder


def _coerce_param_value(raw_value: str) -> object:
    """A <parameter> body is always raw text; recover richer types where we can.

    Qwen's tool-call tags carry every argument as text regardless of the
    declared JSON-schema type, so a boolean/number/object parameter arrives as
    a *string* containing "true" / "3" / "{...}". We try JSON first (covers
    numbers, bools, null, objects, arrays) and fall back to the trimmed string
    -- which is also the correct behavior for genuinely string-typed args like
    a file path.
    """
    value = raw_value.strip()
    if not value:
        return ""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def _parse_one_tool_call(block_text: str) -> ParsedToolCall | None:
    match = _FUNCTION_RE.search(block_text)
    if not match:
        return None
    name = match.group(1).strip()
    body = match.group(2)
    arguments = {
        param_name.strip(): _coerce_param_value(param_value)
        for param_name, param_value in _PARAMETER_RE.findall(body)
    }
    return ParsedToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=name, arguments=arguments, raw=block_text)


def parse_assistant_content(raw: str) -> ParsedAssistantMessage:
    """Normalize one raw `message.content` string from the orchestrator.

    Always succeeds -- a response with no thinking and no tool calls (the
    common case for a plain text answer) just comes back with `text=raw` and
    an empty tool_calls list.
    """
    thinking, remainder = _split_thinking(raw)

    tool_calls: list[ParsedToolCall] = []
    for block in _TOOL_CALL_RE.findall(remainder):
        parsed = _parse_one_tool_call(block)
        if parsed is not None:
            tool_calls.append(parsed)

    visible_text = _TOOL_CALL_RE.sub("", remainder).strip()

    possibly_truncated = any(marker in visible_text for marker in _TRUNCATION_MARKERS)

    return ParsedAssistantMessage(
        thinking=thinking,
        text=visible_text,
        tool_calls=tool_calls,
        possibly_truncated=possibly_truncated,
        raw=raw,
    )
