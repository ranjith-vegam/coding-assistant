from samixa_code.llm.token_budget import MIN_TOOL_CONTENT_CHARS, estimate_tokens, fit_history_to_budget
from samixa_code.llm.types import ChatMessage


def test_estimate_tokens_is_positive_and_roughly_proportional():
    assert estimate_tokens("a") >= 1
    assert estimate_tokens("a" * 1000) > estimate_tokens("a" * 10)


def test_small_history_fits_unchanged():
    history = [
        ChatMessage(role="system", content="you are an assistant"),
        ChatMessage(role="user", content="hello"),
    ]
    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)
    assert result == history


def test_drops_oldest_turn_groups_first_keeps_system_and_last():
    system = ChatMessage(role="system", content="sys")
    # ~31k estimated tokens on its own -- must exceed the ~15k budget alone
    # (16384 context - 1024 reply) to force a drop, unlike a merely large message.
    old_user = ChatMessage(role="user", content="x" * 100000)
    old_assistant = ChatMessage(role="assistant", content="ok")
    recent_user = ChatMessage(role="user", content="recent question")

    history = [system, old_user, old_assistant, recent_user]
    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)

    assert result[0] == system
    assert result[-1] == recent_user
    assert old_user not in result  # the huge old turn had to go
    assert old_assistant not in result  # dropped as part of the same group


def test_tool_call_group_is_dropped_as_one_unit_never_orphaned():
    system = ChatMessage(role="system", content="sys")
    huge_group = [
        ChatMessage(role="user", content="do a big thing"),
        ChatMessage(role="assistant", content="x" * 30000),  # tool-call turn, huge
        ChatMessage(role="tool", content="y" * 30000, name="read_file", tool_call_id="c1"),
        ChatMessage(role="assistant", content="done"),
    ]
    recent_user = ChatMessage(role="user", content="another question")
    history = [system, *huge_group, recent_user]

    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)

    # Either the whole huge group survives or none of it does -- never a
    # partial group (e.g. the tool result with no matching assistant call).
    group_messages_present = [m for m in huge_group if m in result]
    assert len(group_messages_present) in (0, len(huge_group))
    assert result[-1] == recent_user


def test_last_group_is_never_dropped_even_if_it_alone_exceeds_budget():
    system = ChatMessage(role="system", content="sys")
    huge_last = ChatMessage(role="user", content="z" * 100000)
    history = [system, huge_last]

    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)

    assert result[-1] == huge_last


def test_current_turn_with_many_huge_rounds_gets_its_own_oldest_rounds_trimmed():
    """Reproduces the exact live failure: one still-open turn accumulates many
    tool-call rounds and blows the budget entirely on its own -- v1 had
    nothing to trim here since the whole current turn was one protected group."""
    system = ChatMessage(role="system", content="sys")
    leading_user = ChatMessage(role="user", content="do a multi-step task")

    def make_round(tag: str, size: int) -> list[ChatMessage]:
        return [
            ChatMessage(role="assistant", content=f"calling tool {tag}"),
            ChatMessage(role="tool", content=tag * size, name="read_file", tool_call_id=f"c-{tag}"),
        ]

    # Sized so round2 ALONE still exceeds the ~15k budget -- forces both
    # older rounds to be dropped, not just enough to stop after the first.
    round1 = make_round("a", 60000)  # huge, oldest -- must be droppable
    round2 = make_round("b", 60000)  # huge, middle -- must be droppable
    round3 = make_round("c", 100)  # small, most recent -- must survive

    history = [system, leading_user, *round1, *round2, *round3]
    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)

    assert result[0] == system
    assert result[1] == leading_user  # the original request must never be lost
    for m in round1 + round2:
        assert m not in result
    for m in round3:
        assert m in result
    assert estimate_tokens("".join(m.content for m in result)) <= 16384 - 1024 + 50  # fits, with estimator slack


def test_within_turn_trim_never_drops_the_leading_user_message_even_if_huge():
    system = ChatMessage(role="system", content="sys")
    huge_leading_user = ChatMessage(role="user", content="x" * 200000)
    small_round = [
        ChatMessage(role="assistant", content="ok"),
        ChatMessage(role="tool", content="result", name="read_file", tool_call_id="c1"),
    ]

    history = [system, huge_leading_user, *small_round]
    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)

    assert huge_leading_user in result
    assert result[-1] == small_round[-1]


def test_bundled_multi_tool_call_round_gets_content_shrunk_not_dropped():
    """Reproduces the exact live failure: a model bundling several tool calls
    into ONE response makes that whole round indivisible by phase 2 (dropping
    any single tool result would orphan its tool_call tag in the assistant
    message) -- phase 3 must shrink the oversized tool CONTENT instead."""
    system = ChatMessage(role="system", content="sys")
    user = ChatMessage(role="user", content="read six files")
    # One assistant message bundling 6 tool calls -- an indivisible round.
    assistant = ChatMessage(role="assistant", content="calling 6 tools")
    tool_results = [
        ChatMessage(role="tool", content=f"file{i} " + ("x" * 6000), name="read_file", tool_call_id=f"c{i}")
        for i in range(6)
    ]

    history = [system, user, assistant, *tool_results]
    # calibration=3.0 mirrors the real observed gap live -- at calibration=1.0
    # this exact content (36k chars) doesn't even exceed budget, so nothing
    # would need shrinking and this test would pass vacuously.
    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024, calibration=3.0)

    assert estimate_tokens("".join(m.content for m in result)) * 3.0 <= 16384 - 1024 + 500
    # every tool result must still be present (not dropped -- that would
    # orphan the assistant's tool_call tag for it), just shrunk
    assert len([m for m in result if m.role == "tool"]) == 6
    # at least the largest ones should have been cut down, with a visible marker
    shrunk = [m for m in result if m.role == "tool" and len(m.content) < 6006]
    assert shrunk, "expected at least one oversized tool result to be shrunk"
    for m in shrunk:
        assert "truncated" in m.content


def test_content_shrink_never_touches_system_user_or_assistant_messages():
    system = ChatMessage(role="system", content="sys")
    user = ChatMessage(role="user", content="u" * 5000)
    assistant = ChatMessage(role="assistant", content="a" * 5000)
    tool_result = ChatMessage(role="tool", content="t" * 60000, name="read_file", tool_call_id="c1")

    history = [system, user, assistant, tool_result]
    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)

    system_msg = next(m for m in result if m.role == "system")
    user_msg = next(m for m in result if m.role == "user")
    assistant_msg = next(m for m in result if m.role == "assistant")
    assert system_msg.content == "sys"
    assert user_msg.content == "u" * 5000
    assert assistant_msg.content == "a" * 5000
    tool_msg = next(m for m in result if m.role == "tool")
    assert len(tool_msg.content) < 60000  # only the tool message shrank


def test_content_shrink_never_goes_below_minimum_floor():
    system = ChatMessage(role="system", content="sys")
    user = ChatMessage(role="user", content="q")
    assistant = ChatMessage(role="assistant", content="a")
    tool_result = ChatMessage(role="tool", content="t" * 500000, name="read_file", tool_call_id="c1")

    history = [system, user, assistant, tool_result]
    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)

    tool_msg = next(m for m in result if m.role == "tool")
    assert len(tool_msg.content) >= MIN_TOOL_CONTENT_CHARS


def test_no_system_message_still_works():
    history = [ChatMessage(role="user", content="hi")]
    result = fit_history_to_budget(history, max_context_tokens=16384, reserved_for_reply=1024)
    assert result == history


def test_empty_history_returns_empty():
    assert fit_history_to_budget([], max_context_tokens=16384, reserved_for_reply=1024) == []
