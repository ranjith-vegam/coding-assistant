"""Rough token budgeting for a hard-capped context window (confirmed live:
model-orch returned a 400 for "This model's maximum context length is 16384
tokens" -- a single read_file call had already put ~12k input tokens on the
wire before this guard existed).

model-orch's /tokenize endpoint errors (confirmed 500 on a real call), so
there's no exact tokenizer available to us here. This uses a conservative
chars-per-token estimate instead -- the goal is "never send a request that's
going to get a 400 back", not precise token accounting, so overestimating is
the safe direction to be wrong in.

Three-phase trimming (v3 -- v1 had only phase 1, v2 added phase 2, both still
overflowed on a real case):
  Phase 1 drops whole OLDER TURNS (a full past exchange: a user message and
  everything up to the next user message) oldest-first -- this is what gives
  cross-message memory within a session, bounded by budget.
  Phase 2 additionally trims OLDER ROUNDS WITHIN the current, still-open turn
  (each tool-call round: an assistant message + the tool results it produced)
  if that turn has, by itself, grown past the budget -- confirmed live: a
  single turn making many tool-call rounds (read/search/edit before a final
  answer) can accumulate past 16k entirely on its own, and v1's "never touch
  the last group" rule had nothing left to trim in that case.
  Phase 3 (content-level, not message-level): confirmed live that a model can
  bundle SEVERAL tool calls into ONE assistant turn (six read_file calls in a
  single response, observed directly) -- that whole bundle is then ONE
  round, indivisible by phase 2 (dropping any one tool result would leave the
  assistant's own tool_call tag for it with no matching result, exactly the
  orphaning phases 1/2 exist to prevent). When even the protected floor
  (leading user message + this one indivisible round) is still over budget,
  the only thing left to shrink is the CONTENT of the biggest tool-result
  messages themselves -- safe to truncate (it's our own tool output, format
  we control) unlike an assistant message's raw tool-call tags.
"""

from __future__ import annotations

from samixa_code.llm.types import ChatMessage

CHARS_PER_TOKEN_ESTIMATE = 3.2  # conservative -- overestimates tokens, not under
PER_MESSAGE_OVERHEAD_TOKENS = 8  # role/formatting overhead, rough
# Never shrink a tool result below this many characters -- keep at least
# something informative rather than truncate it to nothing.
MIN_TOOL_CONTENT_CHARS = 300


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN_ESTIMATE))


def estimate_message_tokens(message: ChatMessage) -> int:
    return estimate_tokens(message.content) + PER_MESSAGE_OVERHEAD_TOKENS


def _tokens_of(messages: list[ChatMessage], calibration: float = 1.0) -> int:
    """calibration scales the raw char-based estimate toward reality once
    real usage.prompt_tokens data is available (see AgentLoop) -- confirmed
    live that the raw estimate alone can be off by ~3x on tool-enabled calls."""
    return int(sum(estimate_message_tokens(m) for m in messages) * calibration)


def _split_into_turns(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """Whole past exchanges: each starts at a 'user' message and includes
    everything up to (not including) the next 'user' message. The unit for
    cross-message memory -- an entire past exchange is kept or dropped as one."""
    turns: list[list[ChatMessage]] = []
    for message in messages:
        if message.role == "user" or not turns:
            turns.append([message])
        else:
            turns[-1].append(message)
    return turns


def _split_into_rounds(turn_body: list[ChatMessage]) -> list[list[ChatMessage]]:
    """Within one turn's body (everything after its leading user message):
    each round starts at an 'assistant' message and includes the 'tool'
    messages it produced -- never split an assistant tool-call from its
    result, same reasoning as _split_into_turns but one level finer."""
    rounds: list[list[ChatMessage]] = []
    for message in turn_body:
        if message.role == "assistant" or not rounds:
            rounds.append([message])
        else:
            rounds[-1].append(message)
    return rounds


def _shrink_oversized_tool_messages(
    messages: list[ChatMessage],
    budget: int,
    calibration: float,
) -> list[ChatMessage]:
    """Last resort (phase 3): truncate the CONTENT of the largest tool-result
    messages, largest first, until the total fits or every tool message is
    down to MIN_TOOL_CONTENT_CHARS. Only ever touches role="tool" messages --
    never system/user/assistant content (an assistant message's tool_call
    tags must survive byte-for-byte, see ParsedAssistantMessage.raw). Returns
    a new list; never mutates the input."""
    result = list(messages)
    tool_indices = sorted(
        (i for i, m in enumerate(result) if m.role == "tool"),
        key=lambda i: len(result[i].content),
        reverse=True,
    )

    for i in tool_indices:
        current_total = _tokens_of(result, calibration)
        if current_total <= budget:
            break

        message = result[i]
        current_len = len(message.content)
        if current_len <= MIN_TOOL_CONTENT_CHARS:
            continue

        excess_tokens = current_total - budget
        # Chars to remove to close (approximately) the whole remaining gap in
        # one step for THIS message, capped at what's actually there to cut.
        chars_to_remove = min(
            current_len - MIN_TOOL_CONTENT_CHARS,
            int((excess_tokens * CHARS_PER_TOKEN_ESTIMATE) / max(calibration, 0.01)) + 100,
        )
        if chars_to_remove <= 0:
            continue

        new_content = message.content[: current_len - chars_to_remove] + "\n... (further truncated to fit the model's context window)"
        result[i] = ChatMessage(role=message.role, content=new_content, tool_call_id=message.tool_call_id, name=message.name)

    return result


def fit_history_to_budget(
    history: list[ChatMessage],
    max_context_tokens: int,
    reserved_for_reply: int,
    calibration: float = 1.0,
) -> list[ChatMessage]:
    """Return a (possibly trimmed) copy of `history` that plausibly fits
    within max_context_tokens once `reserved_for_reply` output tokens are
    accounted for. Never mutates `history` -- callers keep the full,
    untrimmed conversation for replay/display; only the copy sent to the
    model on this one call is reduced.

    `calibration` scales every char-based estimate here -- pass the caller's
    currently-observed (real-usage-calibrated) multiplier, not just 1.0,
    once any real usage.prompt_tokens data is available (see AgentLoop);
    the raw estimate alone is not reliable enough on its own (confirmed live).

    Always keeps: a leading system message, the current turn's leading user
    message (what it's actually being asked), and the current turn's most
    recent round (needed for the call in progress). If even that minimum
    doesn't fit, returns it as-is and lets the real error surface rather than
    silently dropping the request just made.
    """
    has_system = bool(history) and history[0].role == "system"
    head = history[:1] if has_system else []
    rest = history[1:] if has_system else list(history)

    if not rest:
        return history

    budget = max_context_tokens - reserved_for_reply
    head_tokens = _tokens_of(head, calibration)

    turns = _split_into_turns(rest)
    last_turn = turns[-1]
    older_turns = turns[:-1]

    def total(older: list[list[ChatMessage]], current: list[ChatMessage]) -> int:
        return head_tokens + sum(_tokens_of(t, calibration) for t in older) + _tokens_of(current, calibration)

    # Phase 1: drop whole older turns, oldest first.
    while older_turns and total(older_turns, last_turn) > budget:
        older_turns.pop(0)

    # Phase 2: the current turn alone may still be over budget (many
    # tool-call rounds before a final answer). Trim ITS oldest rounds too,
    # always keeping its leading user message and its most recent round.
    if total(older_turns, last_turn) > budget and len(last_turn) > 1:
        leading_user = last_turn[:1]
        rounds = _split_into_rounds(last_turn[1:])
        if rounds:
            last_round = rounds[-1]
            droppable_rounds = rounds[:-1]
            while droppable_rounds:
                candidate = leading_user + [m for r in droppable_rounds for m in r] + last_round
                if total(older_turns, candidate) <= budget:
                    break
                droppable_rounds.pop(0)
            last_turn = leading_user + [m for r in droppable_rounds for m in r] + last_round

    kept = [*older_turns, last_turn]
    result = head + [message for turn in kept for message in turn]

    # Phase 3: message-level trimming may still not be enough -- e.g. one
    # assistant turn bundled several tool calls, making that whole round a
    # single indivisible unit. Shrink oversized tool-result CONTENT instead.
    if _tokens_of(result, calibration) > budget:
        result = _shrink_oversized_tool_messages(result, budget, calibration)

    return result
