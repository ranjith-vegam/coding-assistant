from coding_assistant.agent.history_replay import history_to_display_items
from coding_assistant.llm.types import ChatMessage


def test_plain_user_and_assistant_turn():
    messages = [
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="assistant", content="</think>\n\nHi there"),
    ]

    items = history_to_display_items(messages)

    assert [i["kind"] for i in items] == ["user", "assistant"]
    assert items[0]["text"] == "hello"
    assert items[1]["text"] == "Hi there"


def test_single_tool_call_pairs_with_its_result():
    messages = [
        ChatMessage(role="user", content="read the file"),
        ChatMessage(
            role="assistant",
            content="</think>\n\n<tool_call>\n<function=read_file>\n<parameter=path>\na.py\n</parameter>\n</function>\n</tool_call>",
        ),
        ChatMessage(role="tool", content="file contents here", name="read_file", tool_call_id="whatever", is_error=False),
        ChatMessage(role="assistant", content="</think>\n\nHere's what's in it."),
    ]

    items = history_to_display_items(messages)

    kinds = [i["kind"] for i in items]
    assert kinds == ["user", "tool", "assistant"]
    tool_item = items[1]
    assert tool_item["name"] == "read_file"
    assert tool_item["arguments"] == {"path": "a.py"}
    assert tool_item["content"] == "file contents here"
    assert tool_item["is_error"] is False
    assert items[2]["text"] == "Here's what's in it."


def test_multiple_bundled_tool_calls_pair_positionally_not_by_id():
    """Reproduces the exact reason this must be positional: parse_assistant_content
    mints a FRESH random id every call, so re-parsing never reproduces the id
    that was live when the tool actually ran -- only append order is stable."""
    messages = [
        ChatMessage(role="user", content="read both files"),
        ChatMessage(
            role="assistant",
            content=(
                "</think>\n\n"
                "<tool_call>\n<function=read_file>\n<parameter=path>\na.py\n</parameter>\n</function>\n</tool_call>\n"
                "<tool_call>\n<function=read_file>\n<parameter=path>\nb.py\n</parameter>\n</function>\n</tool_call>"
            ),
        ),
        ChatMessage(role="tool", content="contents of a", name="read_file", tool_call_id="original_id_1"),
        ChatMessage(role="tool", content="contents of b", name="read_file", tool_call_id="original_id_2"),
    ]

    items = history_to_display_items(messages)

    tool_items = [i for i in items if i["kind"] == "tool"]
    assert len(tool_items) == 2
    assert tool_items[0]["arguments"] == {"path": "a.py"}
    assert tool_items[0]["content"] == "contents of a"
    assert tool_items[1]["arguments"] == {"path": "b.py"}
    assert tool_items[1]["content"] == "contents of b"


def test_error_tool_result_is_preserved():
    messages = [
        ChatMessage(role="user", content="edit it"),
        ChatMessage(
            role="assistant",
            content="</think>\n\n<tool_call>\n<function=edit_file>\n<parameter=path>\na.py\n</parameter>\n</function>\n</tool_call>",
        ),
        ChatMessage(role="tool", content="old_string not found", name="edit_file", tool_call_id="c1", is_error=True),
    ]

    items = history_to_display_items(messages)
    tool_item = next(i for i in items if i["kind"] == "tool")
    assert tool_item["is_error"] is True


def test_missing_tool_result_does_not_crash_shows_pending():
    messages = [
        ChatMessage(role="user", content="do something"),
        ChatMessage(
            role="assistant",
            content="</think>\n\n<tool_call>\n<function=read_file>\n<parameter=path>\na.py\n</parameter>\n</function>\n</tool_call>",
        ),
        # no matching tool message follows -- must not raise
    ]

    items = history_to_display_items(messages)
    tool_item = next(i for i in items if i["kind"] == "tool")
    assert tool_item["content"] is None


def test_assistant_message_with_only_a_tool_call_has_no_text_item():
    messages = [
        ChatMessage(role="user", content="go"),
        ChatMessage(
            role="assistant",
            content="<tool_call>\n<function=read_file>\n<parameter=path>\na.py\n</parameter>\n</function>\n</tool_call>",
        ),
        ChatMessage(role="tool", content="result", name="read_file", tool_call_id="c1"),
    ]

    items = history_to_display_items(messages)
    assert [i["kind"] for i in items] == ["user", "tool"]  # no empty assistant bubble


def test_empty_history_returns_empty_list():
    assert history_to_display_items([]) == []
