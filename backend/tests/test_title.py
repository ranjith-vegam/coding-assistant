from coding_assistant.agent.title import MAX_TITLE_CHARS, generate_chat_title
from coding_assistant.llm.client import ModelOrchError
from coding_assistant.llm.types import ParsedAssistantMessage


class FakeLLM:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    async def chat(self, messages, tools=None, tool_choice="auto", temperature=0.2, max_tokens=4096):
        self.calls.append({"messages": messages, "tools": tools, "max_tokens": max_tokens})
        if self._error is not None:
            raise self._error
        return self._response


async def test_generate_chat_title_returns_the_models_text():
    llm = FakeLLM(response=ParsedAssistantMessage(thinking=None, text="Fix login timeout bug", tool_calls=[], raw="raw"))

    title = await generate_chat_title(llm, "why does login keep timing out after 30 seconds")

    assert title == "Fix login timeout bug"
    assert llm.calls[0]["tools"] is None  # never needs tools for this


async def test_generate_chat_title_strips_surrounding_quotes():
    llm = FakeLLM(response=ParsedAssistantMessage(thinking=None, text='"Refactor auth module"', tool_calls=[], raw="raw"))

    title = await generate_chat_title(llm, "please refactor the auth module")

    assert title == "Refactor auth module"


async def test_generate_chat_title_returns_none_on_model_orch_error():
    llm = FakeLLM(error=ModelOrchError("orchestrator down"))

    title = await generate_chat_title(llm, "hello")

    assert title is None


async def test_generate_chat_title_returns_none_for_empty_response():
    llm = FakeLLM(response=ParsedAssistantMessage(thinking=None, text="   ", tool_calls=[], raw="raw"))

    title = await generate_chat_title(llm, "hello")

    assert title is None


async def test_generate_chat_title_truncates_an_overlong_response():
    llm = FakeLLM(response=ParsedAssistantMessage(thinking=None, text="x" * 200, tool_calls=[], raw="raw"))

    title = await generate_chat_title(llm, "hello")

    assert title is not None
    assert len(title) <= MAX_TITLE_CHARS + 1  # +1 for the trailing ellipsis char
    assert title.endswith("…")
