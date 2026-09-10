"""Unit tests for toolcall_parser.py, pinned to real captured model-orch responses.

Every "raw" string below is copy-pasted verbatim from an actual
/v1/chat/completions call against http://192.168.0.99:9900 (model
Qwen3.8-27B), captured 2026-09-09/10 -- not hand-constructed idealized
examples. If the orchestrator's output shape ever changes, these are the
fixtures to update, and this file is the first thing to re-run.
"""

from coding_assistant.llm.toolcall_parser import parse_assistant_content

# --- Real capture #1: plain answer, no tools offered ---
PLAIN_ANSWER_RAW = (
    'We need answer user: "Say hello in exactly 3 words." Need produce exactly 3 words. '
    'Need likely final only 3 words. Choose "Hello there friend" (3 words). Ensure no '
    "punctuation? Punctuation might not count? Better exactly three words separated spaces, "
    'maybe "Hello there friend". That\'s 3.\n</think>\n\nHello there friend'
)

# --- Real capture #2: single tool call ---
TOOL_CALL_RAW = (
    "The user wants to read the file located at /tmp/foo.txt. Let's do that.\n</think>\n\n"
    "<tool_call>\n<function=read_file>\n<parameter=path>\n/tmp/foo.txt\n</parameter>\n"
    "</function>\n</tool_call>"
)


def test_plain_answer_strips_thinking_and_has_no_tool_calls():
    parsed = parse_assistant_content(PLAIN_ANSWER_RAW)

    assert parsed.text == "Hello there friend"
    assert parsed.tool_calls == []
    assert parsed.possibly_truncated is False
    assert parsed.thinking is not None
    assert "Choose" in parsed.thinking
    # thinking must never leak into the visible text
    assert "</think>" not in parsed.text
    assert "Choose" not in parsed.text


def test_single_tool_call_is_recovered_with_typed_argument():
    parsed = parse_assistant_content(TOOL_CALL_RAW)

    assert parsed.text == ""  # nothing left once the tool_call block is removed
    assert len(parsed.tool_calls) == 1
    call = parsed.tool_calls[0]
    assert call.name == "read_file"
    assert call.arguments == {"path": "/tmp/foo.txt"}
    assert call.id.startswith("call_")
    assert parsed.possibly_truncated is False
    assert parsed.raw == TOOL_CALL_RAW  # exact byte-for-byte replay material


def test_multiple_tool_calls_in_one_response():
    raw = (
        "Let's check both files.\n</think>\n\n"
        "<tool_call>\n<function=read_file>\n<parameter=path>\n/a.py\n</parameter>\n"
        "</function>\n</tool_call>\n"
        "<tool_call>\n<function=read_file>\n<parameter=path>\n/b.py\n</parameter>\n"
        "</function>\n</tool_call>"
    )

    parsed = parse_assistant_content(raw)

    assert len(parsed.tool_calls) == 2
    assert [c.arguments["path"] for c in parsed.tool_calls] == ["/a.py", "/b.py"]
    # ids must be distinct so the agent loop can match results back to calls
    assert parsed.tool_calls[0].id != parsed.tool_calls[1].id


def test_json_shaped_parameter_value_is_coerced():
    raw = (
        "</think>\n\n<tool_call>\n<function=edit_file>\n"
        "<parameter=path>\n/x.py\n</parameter>\n"
        '<parameter=edits>\n[{"line": 3, "text": "pass"}]\n</parameter>\n'
        "</function>\n</tool_call>"
    )

    parsed = parse_assistant_content(raw)

    call = parsed.tool_calls[0]
    assert call.arguments["path"] == "/x.py"
    assert call.arguments["edits"] == [{"line": 3, "text": "pass"}]


def test_text_alongside_a_tool_call_is_preserved():
    raw = (
        "</think>\n\nSure, I'll check that file for you.\n\n"
        "<tool_call>\n<function=read_file>\n<parameter=path>\n/y.py\n</parameter>\n"
        "</function>\n</tool_call>"
    )

    parsed = parse_assistant_content(raw)

    assert parsed.text == "Sure, I'll check that file for you."
    assert len(parsed.tool_calls) == 1


def test_truncated_tool_call_is_flagged_not_silently_dropped():
    # Simulates hitting max_tokens mid tool-call: opening tag present, closing
    # tag never arrives. This must NOT be silently treated as "no tool call".
    raw = "</think>\n\n<tool_call>\n<function=read_file>\n<parameter=path>\n/z.py\n</parameter>\n"

    parsed = parse_assistant_content(raw)

    assert parsed.tool_calls == []  # no well-formed block to recover
    assert parsed.possibly_truncated is True


def test_no_thinking_marker_at_all_is_not_an_error():
    parsed = parse_assistant_content("Just a plain reply, no tags at all.")

    assert parsed.thinking is None
    assert parsed.text == "Just a plain reply, no tags at all."
    assert parsed.tool_calls == []


def test_empty_string_does_not_raise():
    parsed = parse_assistant_content("")

    assert parsed.text == ""
    assert parsed.tool_calls == []
    assert parsed.possibly_truncated is False
