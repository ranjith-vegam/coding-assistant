"""The actual tool-call loop: call the model -> execute any tool calls it made
-> feed results back -> repeat until a turn has no tool calls (or a bound is hit).

Replaces api/chat.py's earlier plain-passthrough relay. Emits events through
an `emit` callback so the transport layer (WebSocket today) stays a thin
adapter -- this class knows nothing about WebSockets.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from samixa_code.agent.checkpoints import Checkpoint, CheckpointStore, RestoreResult, restore_files
from samixa_code.agent.tools.base import Tool, ToolError, resolve_in_workspace
from samixa_code.llm.client import ContextLengthExceededError, ModelOrchClient, ModelOrchError
from samixa_code.llm.token_budget import estimate_message_tokens, estimate_tokens, fit_history_to_budget
from samixa_code.llm.types import ChatMessage, ParsedAssistantMessage, ParsedToolCall, ToolDefinition
from samixa_code.permissions.gate import ApprovalDenied, PermissionGate
from samixa_code.settings import get_settings

logger = logging.getLogger(__name__)

# Bounds a single user turn's tool-call chain. A confused local model
# re-calling the same tool forever is a real failure mode (see the
# discussion on tool-calling reliability being weaker than a frontier
# model). Hitting this must never mean "nothing" -- see the forced
# wrap-up call at the end of run_turn -- it's a safety net against
# runaway loops, not a hard stop that swallows whatever was found.
MAX_TOOL_TURNS = 20

# Sent as a final user-role nudge when the loop above is exhausted, with
# tools withheld from that one call so the model physically cannot emit
# another tool-call tag and is forced to answer in plain text.
FORCED_WRAP_UP_PROMPT = (
    "You've reached the tool-call limit for this request. Do not call any more tools. "
    "Based only on what you found above, give your best final answer now. If you "
    "genuinely didn't find enough to answer, say what you tried and what's still unknown."
)

# Confirmed live (2026-09-10): our char-based token estimate can be off by
# ~3x on tool-enabled calls -- the deployed model's chat template injects a
# tool-calling preamble that's invisible to us and much bigger than the raw
# tool-schema JSON we can see and estimate. Seeded pessimistic rather than at
# 1.0 so the very first call (before any real usage.prompt_tokens exists to
# calibrate against) doesn't repeat the exact overflow that motivated this.
# Refined at runtime from each response's real usage -- see _record_usage.
INITIAL_TOKEN_CALIBRATION = 3.0
CALIBRATION_EWMA_ALPHA = 0.3
CALIBRATION_MIN = 1.0
CALIBRATION_MAX = 6.0

# The actual guarantee, not just an optimization: confirmed live that
# pre-emptive estimation (even calibrated against real usage) is NOT reliable
# enough on its own -- the real/estimate gap behaves like a mostly-fixed
# overhead, not a proportional one, so a single multiplicative calibration
# constant can under-shoot for a request shape it hasn't seen recently (e.g.
# converges from small, cheap requests, then undershoots one big one). On the
# exact context-length error, shrink and retry until it fits or gives up.
MAX_CONTEXT_RETRIES = 4
CONTEXT_RETRY_SHRINK_FACTOR = 0.6

# A "possibly_truncated" parse (see toolcall_parser.py) most often means the
# model hit model_orch_reply_max_tokens mid tool-call, not that it's
# genuinely confused -- so the fix that actually addresses the cause is
# retrying with MORE reply budget, not just resending the same request and
# hoping. Env-configurable (truncation_retry_max_attempts/_growth_factor in
# settings.py) since the right values depend on the deployed model/orchestrator,
# not something to hardcode -- see AgentLoop.__init__.

# Tools whose changes are tracked for rewind -- see agent/checkpoints.py.
# Deliberately excludes run_command: matches Claude Code's own checkpointing
# limitation (arbitrary shell effects can't be reliably snapshotted/reversed).
CHECKPOINTED_TOOLS = {"write_file", "edit_file"}

Emit = Callable[[dict[str, Any]], Awaitable[None]]


class AgentLoop:
    def __init__(
        self,
        llm: ModelOrchClient,
        tools: dict[str, Tool],
        gate: PermissionGate,
        workspace_root: Path,
    ):
        self._llm = llm
        self._tools = tools
        self._gate = gate
        self._workspace_root = workspace_root
        self._tool_defs = [ToolDefinition(t.name, t.description, t.parameters) for t in tools.values()]
        settings = get_settings()
        self._context_window_tokens = settings.model_orch_context_window_tokens
        self._reply_max_tokens = settings.model_orch_reply_max_tokens
        self._truncation_retry_max_attempts = settings.truncation_retry_max_attempts
        self._truncation_retry_growth_factor = settings.truncation_retry_growth_factor
        # The tool schemas themselves (name/description/JSON-schema per tool)
        # ride along on every call that offers tools -- real prompt tokens the
        # history-only estimate below doesn't see. Computed once since the
        # tool set is fixed for the lifetime of one AgentLoop.
        self._tool_schema_tokens = estimate_tokens(json.dumps([t.to_wire() for t in self._tool_defs]))
        self._token_calibration = INITIAL_TOKEN_CALIBRATION
        self._checkpoints = CheckpointStore()
        self._active_checkpoint: Checkpoint | None = None

    def _budgeted(
        self, history: list[ChatMessage], *, with_tools: bool, shrink: float = 1.0, reply_max_tokens: int | None = None
    ) -> list[ChatMessage]:
        """A trimmed COPY for this one call -- see token_budget.py. `history`
        itself is never mutated; the full conversation is kept for replay/
        display, only what's sent to the model this call is reduced.

        `shrink` further reduces the usable window below 1.0 -- used by the
        context-retry loop below when the estimate turned out to be wrong.
        `reply_max_tokens` overrides the reserved reply budget for this one
        call -- used by the truncation-retry loop, which asks for MORE reply
        room on retry, so the reservation must grow to match or the extra
        room it just asked for would immediately get eaten back by history."""
        reserved = reply_max_tokens if reply_max_tokens is not None else self._reply_max_tokens
        if with_tools:
            reserved += int(self._tool_schema_tokens * self._token_calibration)
        effective_context = int(self._context_window_tokens * shrink)
        return fit_history_to_budget(history, effective_context, reserved, calibration=self._token_calibration)

    async def _chat_with_context_retry(
        self, history: list[ChatMessage], *, with_tools: bool, reply_max_tokens: int | None = None
    ) -> tuple[list[ChatMessage], ParsedAssistantMessage]:
        """The real guarantee against overflowing the context window -- see
        MAX_CONTEXT_RETRIES comment. Returns (sent, response) so the caller
        can still replay/append normally; raises the last ContextLengthExceededError
        if even the most aggressively shrunk attempt still doesn't fit.

        `reply_max_tokens` lets a caller ask for a bigger (or smaller) reply
        budget than the configured default for this one call -- see
        _chat_with_truncation_retry, which grows it across attempts."""
        reply_max_tokens = reply_max_tokens if reply_max_tokens is not None else self._reply_max_tokens
        shrink = 1.0
        last_exc: ContextLengthExceededError | None = None
        tool_defs = self._tool_defs if with_tools else None

        for attempt in range(MAX_CONTEXT_RETRIES):
            sent = self._budgeted(history, with_tools=with_tools, shrink=shrink, reply_max_tokens=reply_max_tokens)
            logger.debug(
                "_chat_with_context_retry attempt=%d shrink=%.4f calibration=%.2f reply_max_tokens=%d history_len=%d sent_len=%d sent_chars=%d",
                attempt,
                shrink,
                self._token_calibration,
                reply_max_tokens,
                len(history),
                len(sent),
                sum(len(m.content) for m in sent),
            )
            try:
                response = await self._llm.chat(sent, tools=tool_defs, max_tokens=reply_max_tokens)
            except ContextLengthExceededError as exc:
                last_exc = exc
                logger.warning(
                    "context length exceeded on attempt %d/%d (with_tools=%s) -- shrinking and retrying",
                    attempt + 1,
                    MAX_CONTEXT_RETRIES,
                    with_tools,
                )
                # A strong, immediate signal -- don't wait for the EWMA to
                # catch up over future turns; be more conservative right now too.
                self._token_calibration = min(CALIBRATION_MAX, self._token_calibration * 1.5)
                shrink *= CONTEXT_RETRY_SHRINK_FACTOR
                continue

            self._record_usage(sent, with_tools=with_tools, response=response)
            return sent, response

        assert last_exc is not None
        raise last_exc

    async def _chat_with_truncation_retry(
        self, history: list[ChatMessage], *, with_tools: bool
    ) -> tuple[list[ChatMessage], ParsedAssistantMessage]:
        """Retries a response that looks cut off mid tool-call (see
        toolcall_parser.py's possibly_truncated) by asking for MORE reply
        room each attempt -- the usual cause is hitting model_orch_reply_max_tokens
        before the closing tag arrived, so resending identically would just
        reproduce the same cutoff. Gives up after truncation_retry_max_attempts
        (settings.py) and returns the last (still truncated) attempt -- the
        caller decides what to do with a response that's still truncated
        after that; this method never raises for truncation itself, only
        ModelOrchError propagates."""
        reply_max_tokens = self._reply_max_tokens
        sent, parsed = await self._chat_with_context_retry(history, with_tools=with_tools, reply_max_tokens=reply_max_tokens)

        for attempt in range(1, self._truncation_retry_max_attempts):
            if not parsed.possibly_truncated:
                return sent, parsed
            reply_max_tokens = min(
                self._context_window_tokens // 2,
                int(reply_max_tokens * self._truncation_retry_growth_factor),
            )
            logger.warning(
                "response looked cut off mid tool-call (attempt %d/%d) -- retrying with reply_max_tokens=%d",
                attempt,
                self._truncation_retry_max_attempts,
                reply_max_tokens,
            )
            sent, parsed = await self._chat_with_context_retry(history, with_tools=with_tools, reply_max_tokens=reply_max_tokens)

        return sent, parsed

    def _record_usage(self, sent: list[ChatMessage], with_tools: bool, response: ParsedAssistantMessage) -> None:
        """Self-corrects _token_calibration from the REAL usage.prompt_tokens
        this exact request reported, so the estimate converges on reality
        instead of trusting a fixed guess indefinitely."""
        if response.prompt_tokens is None:
            return
        raw_estimate = sum(estimate_message_tokens(m) for m in sent)
        if with_tools:
            raw_estimate += self._tool_schema_tokens
        if raw_estimate <= 0:
            return

        observed_ratio = response.prompt_tokens / raw_estimate
        blended = CALIBRATION_EWMA_ALPHA * observed_ratio + (1 - CALIBRATION_EWMA_ALPHA) * self._token_calibration
        self._token_calibration = min(CALIBRATION_MAX, max(CALIBRATION_MIN, blended))
        logger.debug(
            "token calibration updated: observed_ratio=%.2f new_calibration=%.2f (real prompt_tokens=%d, raw_estimate=%d)",
            observed_ratio,
            self._token_calibration,
            response.prompt_tokens,
            raw_estimate,
        )

    async def run_turn(self, history: list[ChatMessage], emit: Emit) -> None:
        """Run one user turn to completion, mutating `history` in place with
        every assistant/tool message produced along the way."""
        # A checkpoint per turn, captured BEFORE any of its tool calls run --
        # `history[-1]` is the user message that started this turn (chat.py
        # appends it before calling run_turn). See agent/checkpoints.py.
        checkpoint = self._checkpoints.start_checkpoint(history_index=len(history) - 1)
        self._active_checkpoint = checkpoint
        await emit({"type": "checkpoint_created", "id": checkpoint.id})

        for turn_index in range(MAX_TOOL_TURNS):
            await emit({"type": "status", "status": "thinking"})

            try:
                _sent, parsed = await self._chat_with_truncation_retry(history, with_tools=True)
            except ModelOrchError as exc:
                logger.warning("model-orch call failed: %s", exc)
                await emit({"type": "error", "message": str(exc)})
                return

            # Replay the RAW content, not a reconstruction -- see
            # ParsedAssistantMessage.raw for why this matters for the model's
            # own chat-template expectations on the next turn.
            history.append(ChatMessage(role="assistant", content=parsed.raw))

            if parsed.possibly_truncated:
                # _chat_with_truncation_retry already retried with growing
                # reply budgets and it's STILL cut off -- surface it now
                # rather than retry forever.
                await emit(
                    {
                        "type": "error",
                        "message": f"The model's response looked cut off mid tool-call after "
                        f"{self._truncation_retry_max_attempts} attempts. Try again, or ask a more specific question.",
                    }
                )
                return

            if not parsed.tool_calls:
                await emit({"type": "message", "text": parsed.text, "thinking": parsed.thinking, "final": True})
                return

            if parsed.text:
                await emit({"type": "message", "text": parsed.text, "thinking": parsed.thinking, "final": False})

            for call in parsed.tool_calls:
                await self._execute_one(call, history, emit)

        await self._force_wrap_up(history, emit)

    async def _force_wrap_up(self, history: list[ChatMessage], emit: Emit) -> None:
        """Called when MAX_TOOL_TURNS is exhausted. Makes one more model call
        with tools withheld, so it cannot emit another tool-call tag and must
        answer in plain text from whatever was already gathered -- a best-effort
        answer, not silence, is the whole point of this loop existing."""
        await emit({"type": "status", "status": "thinking"})
        history.append(ChatMessage(role="user", content=FORCED_WRAP_UP_PROMPT))

        try:
            _sent, final = await self._chat_with_context_retry(history, with_tools=False)
        except ModelOrchError as exc:
            logger.warning("model-orch call failed during forced wrap-up: %s", exc)
            await emit(
                {
                    "type": "error",
                    "message": f"Stopped after {MAX_TOOL_TURNS} tool-call rounds, and the wrap-up call also failed: {exc}",
                }
            )
            return

        history.append(ChatMessage(role="assistant", content=final.raw))
        await emit(
            {
                "type": "message",
                "text": final.text or "I wasn't able to reach a final answer within the tool-call limit.",
                "thinking": final.thinking,
                "final": True,
            }
        )

    async def _execute_one(self, call: ParsedToolCall, history: list[ChatMessage], emit: Emit) -> None:
        await emit({"type": "tool_call", "id": call.id, "name": call.name, "arguments": call.arguments})

        tool = self._tools.get(call.name)
        try:
            if tool is None:
                result_text, is_error = f"Unknown tool: {call.name}", True
            else:
                if call.name in CHECKPOINTED_TOOLS and self._active_checkpoint is not None:
                    self._record_pre_edit_snapshot(call)
                await self._gate.check(call.id, tool, call.arguments)
                result = await tool.run(call.arguments, self._workspace_root)
                result_text, is_error = result.content, result.is_error
        except ApprovalDenied:
            result_text, is_error = "The user denied permission to run this tool call.", True
        except ToolError as exc:
            result_text, is_error = str(exc), True
        except asyncio.CancelledError:
            # The user hit Stop mid-tool-call. The assistant's tool-call
            # message is ALREADY in history (appended by run_turn before this
            # method was called) -- if we just re-raise without recording a
            # result, that message is left pointing at a tool call that never
            # got an answer, which is exactly the "orphaned tool call" shape
            # token_budget.py's group-dropping exists to never produce. Record
            # the cancellation as this call's result, then propagate.
            result_text, is_error = "Cancelled by user.", True
            await emit({"type": "tool_result", "id": call.id, "name": call.name, "content": result_text, "is_error": is_error})
            history.append(ChatMessage(role="tool", content=result_text, name=call.name, tool_call_id=call.id, is_error=is_error))
            raise
        except Exception as exc:  # noqa: BLE001 -- last-resort guard, a tool bug must not kill the turn
            logger.exception("tool '%s' raised unexpectedly", call.name)
            result_text, is_error = f"Internal error running '{call.name}': {exc}", True

        await emit({"type": "tool_result", "id": call.id, "name": call.name, "content": result_text, "is_error": is_error})
        history.append(ChatMessage(role="tool", content=result_text, name=call.name, tool_call_id=call.id))

    def _record_pre_edit_snapshot(self, call: ParsedToolCall) -> None:
        """Best-effort: if the path is malformed/escapes the workspace, skip
        silently here -- the tool call itself raises the real ToolError for
        that, this just must never be the thing that surfaces it twice."""
        raw_path = call.arguments.get("path")
        if not raw_path or self._active_checkpoint is None:
            return
        try:
            resolved = resolve_in_workspace(self._workspace_root, str(raw_path))
        except ToolError:
            return
        self._checkpoints.record_pre_edit_state(self._active_checkpoint, resolved, self._workspace_root)

    def rewind(
        self,
        checkpoint_id: str,
        history: list[ChatMessage],
        *,
        restore_code: bool,
        restore_conversation: bool,
    ) -> RestoreResult:
        """Restores files (if restore_code) and/or truncates `history` back
        to before the checkpointed turn (if restore_conversation) -- mutates
        `history` in place, same convention as run_turn. Raises ValueError
        for an unknown checkpoint id (stale/already-discarded)."""
        checkpoint = self._checkpoints.get(checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"unknown or already-discarded checkpoint: {checkpoint_id}")

        result = restore_files(checkpoint, self._workspace_root) if restore_code else RestoreResult(restored=[], skipped=[])

        if restore_conversation:
            del history[checkpoint.history_index :]

        self._checkpoints.discard_after(checkpoint_id)
        if self._active_checkpoint is not None and self._checkpoints.get(self._active_checkpoint.id) is None:
            self._active_checkpoint = None

        return result
