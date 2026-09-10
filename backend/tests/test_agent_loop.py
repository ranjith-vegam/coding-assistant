"""Agent loop tests against a fake LLM (queued canned responses) -- these
exercise the loop's control flow, not the real orchestrator integration
(that's llm/toolcall_parser + client, covered separately and against real
captures). asyncio_mode = "auto" in pyproject.toml -- no @pytest.mark.asyncio needed.
"""

import asyncio

from coding_assistant.agent.loop import CALIBRATION_MAX, MAX_CONTEXT_RETRIES, MAX_TOOL_TURNS, AgentLoop
from coding_assistant.agent.tools.base import ToolResult
from coding_assistant.agent.tools.fs_tools import EditFileTool, WriteFileTool
from coding_assistant.llm.client import ContextLengthExceededError
from coding_assistant.llm.types import ChatMessage, ParsedAssistantMessage, ParsedToolCall
from coding_assistant.permissions.gate import PermissionGate


class FakeLLM:
    """Returns canned ParsedAssistantMessages in order; records call count."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, messages, tools=None, tool_choice="auto", temperature=0.2, max_tokens=4096):
        self.calls += 1
        return self._responses.pop(0)


class EchoTool:
    name = "echo"
    description = "echoes its input"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}
    requires_approval = False

    def __init__(self):
        self.received = []

    async def run(self, arguments, workspace_root):
        self.received.append(arguments)
        return ToolResult(content=f"echo: {arguments.get('text')}")


class RiskyTool:
    name = "risky"
    description = "does something risky"
    parameters = {"type": "object", "properties": {}}
    requires_approval = True

    async def run(self, arguments, workspace_root):
        return ToolResult(content="did the risky thing")


async def always_approve(call_id, name, arguments):
    return True


async def always_deny(call_id, name, arguments):
    return False


def make_tool_call(name, arguments=None, call_id=None):
    return ParsedToolCall(id=call_id or f"call_{name}", name=name, arguments=arguments or {}, raw="<tool_call>...</tool_call>")


async def collect_events(loop, history):
    events = []

    async def emit(event):
        events.append(event)

    await loop.run_turn(history, emit)
    return events


async def test_agent_loop_executes_tool_then_returns_final_answer(tmp_path):
    echo = EchoTool()
    responses = [
        ParsedAssistantMessage(thinking=None, text="", tool_calls=[make_tool_call("echo", {"text": "hi"})], raw="r1"),
        ParsedAssistantMessage(thinking=None, text="done", tool_calls=[], raw="r2"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"echo": echo}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="say hi")]
    events = await collect_events(loop, history)

    assert echo.received == [{"text": "hi"}]
    assert any(e["type"] == "message" and e.get("final") for e in events)
    assert llm.calls == 2
    assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]
    # the tool result must be replayed back with the right correspondence
    tool_message = next(m for m in history if m.role == "tool")
    assert tool_message.name == "echo"
    assert tool_message.content == "echo: hi"


async def test_denied_approval_feeds_back_as_tool_error_not_a_crash(tmp_path):
    risky = RiskyTool()
    responses = [
        ParsedAssistantMessage(thinking=None, text="", tool_calls=[make_tool_call("risky")], raw="r1"),
        ParsedAssistantMessage(thinking=None, text="ok, skipping", tool_calls=[], raw="r2"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"risky": risky}, PermissionGate(always_deny), tmp_path)

    history = [ChatMessage(role="user", content="do the risky thing")]
    events = await collect_events(loop, history)

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["is_error"] is True
    assert "denied" in tool_results[0]["content"].lower()
    # the loop must still reach a final answer, not hang or crash
    assert any(e["type"] == "message" and e.get("final") for e in events)


async def test_max_tool_turns_forces_a_final_answer_instead_of_silence(tmp_path):
    echo = EchoTool()
    # MAX_TOOL_TURNS rounds that all keep calling tools, plus one more canned
    # response for the forced wrap-up call (made with tools withheld).
    responses = [
        ParsedAssistantMessage(thinking=None, text="", tool_calls=[make_tool_call("echo", {"text": "x"}, call_id=f"c{i}")], raw=f"r{i}")
        for i in range(MAX_TOOL_TURNS)
    ]
    responses.append(ParsedAssistantMessage(thinking=None, text="Best-effort summary of what I found.", tool_calls=[], raw="wrap-up"))
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"echo": echo}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="loop forever")]
    events = await collect_events(loop, history)

    assert llm.calls == MAX_TOOL_TURNS + 1
    final_messages = [e for e in events if e["type"] == "message" and e.get("final")]
    assert len(final_messages) == 1
    assert final_messages[0]["text"] == "Best-effort summary of what I found."
    assert not any(e["type"] == "error" for e in events)


async def test_wrap_up_call_failing_still_surfaces_an_error(tmp_path):
    from coding_assistant.llm.client import ModelOrchError

    class FailingWrapUpLLM(FakeLLM):
        async def chat(self, messages, tools=None, tool_choice="auto", temperature=0.2, max_tokens=4096):
            self.calls += 1
            if tools is None:
                raise ModelOrchError("orchestrator down")
            return self._responses.pop(0)

    echo = EchoTool()
    responses = [
        ParsedAssistantMessage(thinking=None, text="", tool_calls=[make_tool_call("echo", {"text": "x"}, call_id=f"c{i}")], raw=f"r{i}")
        for i in range(MAX_TOOL_TURNS)
    ]
    llm = FailingWrapUpLLM(responses)
    loop = AgentLoop(llm, {"echo": echo}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="loop forever")]
    events = await collect_events(loop, history)

    assert any(e["type"] == "error" and "wrap-up call also failed" in e["message"] for e in events)


async def test_unknown_tool_name_is_reported_not_crashed(tmp_path):
    responses = [
        ParsedAssistantMessage(thinking=None, text="", tool_calls=[make_tool_call("does_not_exist")], raw="r1"),
        ParsedAssistantMessage(thinking=None, text="oops", tool_calls=[], raw="r2"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="call a fake tool")]
    events = await collect_events(loop, history)

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results[0]["is_error"] is True
    assert "Unknown tool" in tool_results[0]["content"]


async def test_possibly_truncated_response_aborts_the_turn_cleanly(tmp_path):
    responses = [ParsedAssistantMessage(thinking=None, text="", tool_calls=[], possibly_truncated=True, raw="r1")]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="hi")]
    events = await collect_events(loop, history)

    assert any(e["type"] == "error" and "cut off" in e["message"] for e in events)
    assert llm.calls == 1  # must not retry on its own -- surfaced to the user instead


async def test_record_usage_increases_calibration_when_real_tokens_exceed_estimate(tmp_path):
    """Reproduces why the fix was needed: real prompt_tokens (from the API's
    own usage block) can be far larger than our char-based estimate for the
    exact same request -- confirmed live, tool-enabled calls in particular.
    _record_usage must push the calibration up in response, not ignore it."""
    loop = AgentLoop(FakeLLM([]), {}, PermissionGate(always_approve), tmp_path)
    initial = loop._token_calibration

    sent = [ChatMessage(role="system", content="short"), ChatMessage(role="user", content="hi")]
    response = ParsedAssistantMessage(thinking=None, text="ok", tool_calls=[], raw="ok", prompt_tokens=50_000)

    loop._record_usage(sent, with_tools=True, response=response)

    assert loop._token_calibration > initial


async def test_record_usage_is_a_noop_without_real_usage_data(tmp_path):
    loop = AgentLoop(FakeLLM([]), {}, PermissionGate(always_approve), tmp_path)
    initial = loop._token_calibration

    sent = [ChatMessage(role="user", content="hi")]
    response = ParsedAssistantMessage(thinking=None, text="ok", tool_calls=[], raw="ok", prompt_tokens=None)
    loop._record_usage(sent, with_tools=True, response=response)

    assert loop._token_calibration == initial


async def test_calibration_never_exceeds_its_clamp():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        loop = AgentLoop(FakeLLM([]), {}, PermissionGate(always_approve), Path(tmp))
        sent = [ChatMessage(role="user", content="x")]
        response = ParsedAssistantMessage(thinking=None, text="ok", tool_calls=[], raw="ok", prompt_tokens=10_000_000)

        for _ in range(50):
            loop._record_usage(sent, with_tools=True, response=response)

        assert loop._token_calibration == CALIBRATION_MAX


async def test_higher_calibration_trims_more_aggressively(tmp_path):
    """The whole point: once calibration goes up, _budgeted() must actually
    trim history harder for the NEXT call, not just record a number nobody uses."""
    loop = AgentLoop(FakeLLM([]), {}, PermissionGate(always_approve), tmp_path)

    history = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="x" * 8000),
        ChatMessage(role="assistant", content="ok"),
        ChatMessage(role="tool", content="y" * 8000, name="read_file", tool_call_id="c1"),
        ChatMessage(role="user", content="latest question"),
    ]

    at_default = loop._budgeted(history, with_tools=True)
    loop._token_calibration = CALIBRATION_MAX
    at_max_calibration = loop._budgeted(history, with_tools=True)

    assert len(at_max_calibration) <= len(at_default)
    assert at_max_calibration[-1].content == "latest question"


async def test_context_retry_recovers_after_shrinking(tmp_path):
    """Reproduces the exact live failure mode: pre-emptive estimation says a
    request fits, model-orch says it doesn't (400, context length exceeded).
    The loop must shrink and retry rather than treat this as a hard failure."""

    class FlakyThenOkLLM:
        def __init__(self, fail_times):
            self.fail_times = fail_times
            self.calls = 0
            self.seen_messages: list[list[ChatMessage]] = []

        async def chat(self, messages, tools=None, tool_choice="auto", temperature=0.2, max_tokens=4096):
            self.calls += 1
            self.seen_messages.append(messages)
            if self.calls <= self.fail_times:
                raise ContextLengthExceededError("model-orch chat completion failed: 400 maximum context length ...")
            return ParsedAssistantMessage(thinking=None, text="done", tool_calls=[], raw="done", prompt_tokens=100)

    llm = FlakyThenOkLLM(fail_times=2)
    loop = AgentLoop(llm, {}, PermissionGate(always_approve), tmp_path)

    history = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="x" * 5000),
    ]
    sent, response = await loop._chat_with_context_retry(history, with_tools=True)

    assert llm.calls == 3  # 2 failures + 1 success
    assert response.text == "done"
    # each retry must have actually shrunk what was sent, not repeated the identical request
    lengths = [sum(len(m.content) for m in msgs) for msgs in llm.seen_messages]
    assert lengths[1] <= lengths[0]
    assert lengths[2] <= lengths[1]


async def test_context_retry_gives_up_after_max_attempts_and_raises(tmp_path):
    class AlwaysFailsLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=None, tool_choice="auto", temperature=0.2, max_tokens=4096):
            self.calls += 1
            raise ContextLengthExceededError("model-orch chat completion failed: 400 maximum context length ...")

    llm = AlwaysFailsLLM()
    loop = AgentLoop(llm, {}, PermissionGate(always_approve), tmp_path)
    history = [ChatMessage(role="user", content="hi")]

    try:
        await loop._chat_with_context_retry(history, with_tools=True)
        assert False, "expected ContextLengthExceededError to propagate"
    except ContextLengthExceededError:
        pass

    assert llm.calls == MAX_CONTEXT_RETRIES


async def test_run_turn_surfaces_a_clean_error_when_context_retries_are_exhausted(tmp_path):
    """End-to-end through run_turn (not just the retry helper): the turn must
    end with a normal error event, not an unhandled exception killing the
    connection -- ContextLengthExceededError IS-A ModelOrchError so the
    existing except clause in run_turn already covers it."""

    class AlwaysFailsLLM:
        async def chat(self, messages, tools=None, tool_choice="auto", temperature=0.2, max_tokens=4096):
            raise ContextLengthExceededError("model-orch chat completion failed: 400 maximum context length ...")

    loop = AgentLoop(AlwaysFailsLLM(), {}, PermissionGate(always_approve), tmp_path)
    history = [ChatMessage(role="user", content="hi")]
    events = await collect_events(loop, history)

    assert any(e["type"] == "error" for e in events)


async def test_cancelling_mid_tool_call_records_a_result_not_an_orphaned_call(tmp_path):
    """Simulates hitting Stop while a slow tool is running: the assistant's
    tool-call message is already in history by the time execution starts, so
    cancellation must still produce a matching tool result -- an orphaned
    tool-call message would confuse the next call's chat template AND could
    get split from its (nonexistent) result by token_budget's group-dropping."""

    class SlowTool:
        name = "slow"
        description = "never finishes on its own"
        parameters = {"type": "object", "properties": {}}
        requires_approval = False

        def __init__(self):
            self.started = asyncio.Event()

        async def run(self, arguments, workspace_root):
            self.started.set()
            await asyncio.sleep(10)  # cancelled long before this would return
            return ToolResult(content="should never get here")

    slow = SlowTool()
    responses = [
        ParsedAssistantMessage(thinking=None, text="", tool_calls=[make_tool_call("slow")], raw="r1"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"slow": slow}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="do the slow thing")]
    events = []

    async def emit(event):
        events.append(event)

    task = asyncio.create_task(loop.run_turn(history, emit))
    await slow.started.wait()
    task.cancel()

    raised = None
    try:
        await task
    except asyncio.CancelledError as exc:
        raised = exc
    assert raised is not None  # cancellation must propagate, not be swallowed

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["is_error"] is True
    assert "cancel" in tool_results[0]["content"].lower()

    tool_message = next(m for m in history if m.role == "tool")
    assert "cancel" in tool_message.content.lower()
    # the assistant's tool-call turn and its (cancellation) result must both
    # be present -- never just one half of the pair
    assert [m.role for m in history] == ["user", "assistant", "tool"]


async def test_a_buggy_tool_raising_does_not_kill_the_turn(tmp_path):
    class BrokenTool:
        name = "broken"
        description = "raises unexpectedly"
        parameters = {"type": "object", "properties": {}}
        requires_approval = False

        async def run(self, arguments, workspace_root):
            raise RuntimeError("boom")

    responses = [
        ParsedAssistantMessage(thinking=None, text="", tool_calls=[make_tool_call("broken")], raw="r1"),
        ParsedAssistantMessage(thinking=None, text="recovered", tool_calls=[], raw="r2"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"broken": BrokenTool()}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="trigger the bug")]
    events = await collect_events(loop, history)

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results[0]["is_error"] is True
    assert "boom" in tool_results[0]["content"]
    assert any(e["type"] == "message" and e.get("final") for e in events)


async def test_run_turn_emits_a_checkpoint_before_any_tool_runs(tmp_path):
    responses = [ParsedAssistantMessage(thinking=None, text="hi", tool_calls=[], raw="r1")]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="hello")]
    events = await collect_events(loop, history)

    checkpoint_events = [e for e in events if e["type"] == "checkpoint_created"]
    assert len(checkpoint_events) == 1
    assert checkpoint_events[0]["id"]


async def test_rewind_restores_code_and_conversation_after_a_write(tmp_path):
    (tmp_path / "greeter.py").write_text("original content\n")

    write_tool = WriteFileTool()
    responses = [
        ParsedAssistantMessage(
            thinking=None,
            text="",
            tool_calls=[make_tool_call("write_file", {"path": "greeter.py", "content": "modified by agent\n"})],
            raw="r1",
        ),
        ParsedAssistantMessage(thinking=None, text="done", tool_calls=[], raw="r2"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"write_file": write_tool}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="please rewrite greeter.py")]
    events = await collect_events(loop, history)

    assert (tmp_path / "greeter.py").read_text() == "modified by agent\n"
    checkpoint_id = next(e["id"] for e in events if e["type"] == "checkpoint_created")

    result = loop.rewind(checkpoint_id, history, restore_code=True, restore_conversation=True)

    assert (tmp_path / "greeter.py").read_text() == "original content\n"
    assert result.restored == ["greeter.py"]
    assert result.skipped == []
    assert history == []  # truncated back to before the user message that started this turn


async def test_rewind_deletes_a_file_that_was_created_by_the_turn(tmp_path):
    write_tool = WriteFileTool()
    responses = [
        ParsedAssistantMessage(
            thinking=None,
            text="",
            tool_calls=[make_tool_call("write_file", {"path": "brand_new.py", "content": "hello\n"})],
            raw="r1",
        ),
        ParsedAssistantMessage(thinking=None, text="done", tool_calls=[], raw="r2"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"write_file": write_tool}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="create a new file")]
    events = await collect_events(loop, history)
    assert (tmp_path / "brand_new.py").exists()

    checkpoint_id = next(e["id"] for e in events if e["type"] == "checkpoint_created")
    loop.rewind(checkpoint_id, history, restore_code=True, restore_conversation=False)

    assert not (tmp_path / "brand_new.py").exists()


async def test_rewind_undoes_the_whole_turns_edits_not_just_the_last_one(tmp_path):
    """Two writes to the SAME file within one turn -- restoring must go back
    to the state before the FIRST write, not just undo the second."""
    (tmp_path / "a.py").write_text("v0\n")
    write_tool = WriteFileTool()
    responses = [
        ParsedAssistantMessage(
            thinking=None, text="", tool_calls=[make_tool_call("write_file", {"path": "a.py", "content": "v1\n"}, call_id="c1")], raw="r1"
        ),
        ParsedAssistantMessage(
            thinking=None, text="", tool_calls=[make_tool_call("write_file", {"path": "a.py", "content": "v2\n"}, call_id="c2")], raw="r2"
        ),
        ParsedAssistantMessage(thinking=None, text="done", tool_calls=[], raw="r3"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"write_file": write_tool}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="edit it twice")]
    events = await collect_events(loop, history)
    assert (tmp_path / "a.py").read_text() == "v2\n"

    checkpoint_id = next(e["id"] for e in events if e["type"] == "checkpoint_created")
    result = loop.rewind(checkpoint_id, history, restore_code=True, restore_conversation=False)

    assert (tmp_path / "a.py").read_text() == "v0\n"
    assert result.restored == ["a.py"]


async def test_run_command_changes_are_not_tracked_for_rewind(tmp_path):
    """Matches Claude Code's own documented limitation: bash/run_command
    effects can't be reliably captured or reversed, so they're not tracked."""

    class FakeRunCommand:
        name = "run_command"
        description = "runs a command"
        parameters = {"type": "object", "properties": {}}
        requires_approval = True

        async def run(self, arguments, workspace_root):
            (workspace_root / "side_effect.txt").write_text("created by a shell command\n")
            return ToolResult(content="ran it")

    responses = [
        ParsedAssistantMessage(thinking=None, text="", tool_calls=[make_tool_call("run_command", {"command": "touch side_effect.txt"})], raw="r1"),
        ParsedAssistantMessage(thinking=None, text="done", tool_calls=[], raw="r2"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"run_command": FakeRunCommand()}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="run a command")]
    events = await collect_events(loop, history)
    assert (tmp_path / "side_effect.txt").exists()

    checkpoint_id = next(e["id"] for e in events if e["type"] == "checkpoint_created")
    result = loop.rewind(checkpoint_id, history, restore_code=True, restore_conversation=False)

    assert (tmp_path / "side_effect.txt").exists()  # NOT reverted -- untracked by design
    assert result.restored == []


async def test_rewind_with_unknown_checkpoint_id_raises(tmp_path):
    loop = AgentLoop(FakeLLM([]), {}, PermissionGate(always_approve), tmp_path)
    try:
        loop.rewind("does_not_exist", [], restore_code=True, restore_conversation=True)
        assert False, "expected ValueError"
    except ValueError:
        pass


async def test_edit_file_change_is_also_tracked_for_rewind(tmp_path):
    (tmp_path / "a.py").write_text("hello world\n")
    edit_tool = EditFileTool()
    responses = [
        ParsedAssistantMessage(
            thinking=None,
            text="",
            tool_calls=[make_tool_call("edit_file", {"path": "a.py", "old_string": "hello", "new_string": "goodbye"})],
            raw="r1",
        ),
        ParsedAssistantMessage(thinking=None, text="done", tool_calls=[], raw="r2"),
    ]
    llm = FakeLLM(responses)
    loop = AgentLoop(llm, {"edit_file": edit_tool}, PermissionGate(always_approve), tmp_path)

    history = [ChatMessage(role="user", content="rename the greeting")]
    events = await collect_events(loop, history)
    assert (tmp_path / "a.py").read_text() == "goodbye world\n"

    checkpoint_id = next(e["id"] for e in events if e["type"] == "checkpoint_created")
    loop.rewind(checkpoint_id, history, restore_code=True, restore_conversation=False)

    assert (tmp_path / "a.py").read_text() == "hello world\n"
