"""Client for the model-orchestrator (chat completions + embeddings).

We do not own or configure the model server -- this just talks to whatever is
running behind MODEL_ORCH_BASE_URL over its OpenAI-compatible-ish REST API.
See toolcall_parser.py for the two ways the response deviates from a real
OpenAI-compatible server (unsplit thinking, unstructured tool calls) and why
that's permanent rather than a bug to wait out.
"""

from __future__ import annotations

import logging

import httpx

from coding_assistant.llm.toolcall_parser import parse_assistant_content
from coding_assistant.llm.types import ChatMessage, EmbeddingResult, ParsedAssistantMessage, ToolDefinition
from coding_assistant.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class ModelOrchError(RuntimeError):
    """Raised on a non-2xx response or a malformed body from model-orch."""


class ContextLengthExceededError(ModelOrchError):
    """The specific 400 that says the prompt+reply exceeds the deployed
    model's context window. Split out from ModelOrchError so callers (the
    agent loop) can react by trimming and retrying instead of giving up --
    confirmed live that pre-emptive estimation alone isn't reliable enough to
    prevent this (see agent/loop.py's calibration + retry logic), so this is
    the actual guarantee, not just an optimization."""


class ModelOrchClient:
    def __init__(self, settings: Settings | None = None, http_client: httpx.AsyncClient | None = None):
        self._settings = settings or get_settings()
        self._client = http_client or httpx.AsyncClient(
            base_url=self._settings.model_orch_base_url,
            headers={"Authorization": f"Bearer {self._settings.model_orch_api_key}"},
            timeout=self._settings.model_orch_timeout_seconds,
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> ParsedAssistantMessage:
        """One (non-streaming -- see settings.py) turn against /v1/chat/completions."""
        body: dict = {
            "model": self._settings.model_orch_chat_model,
            "messages": [_message_to_wire(m) for m in messages],
            "stream": False,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = [t.to_wire() for t in tools]
            body["tool_choice"] = tool_choice

        response = await self._client.post("/v1/chat/completions", json=body)
        if response.status_code >= 400:
            body_text = response.text[:500]
            message = f"model-orch chat completion failed: {response.status_code} {body_text}"
            if response.status_code == 400 and "maximum context length" in body_text:
                raise ContextLengthExceededError(message)
            raise ModelOrchError(message)

        data = response.json()
        try:
            raw_content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelOrchError(f"unexpected chat completion shape: {data!r}") from exc

        parsed = parse_assistant_content(raw_content)
        if parsed.possibly_truncated:
            logger.warning(
                "model-orch response looks truncated mid tool-call (leftover tag markers in visible text); "
                "the agent loop should treat this turn as incomplete rather than 'no tool call'"
            )

        usage = data.get("usage") or {}
        parsed.prompt_tokens = usage.get("prompt_tokens")
        parsed.completion_tokens = usage.get("completion_tokens")
        return parsed

    async def embed(self, texts: list[str], return_sparse: bool = True) -> list[EmbeddingResult]:
        """Dense (+ optional sparse) embeddings for a batch of texts, in input order."""
        if not texts:
            return []
        body = {
            "model": self._settings.model_orch_embed_model,
            "input": texts,
            "return_sparse": return_sparse,
        }
        response = await self._client.post("/v1/embeddings", json=body)
        if response.status_code >= 400:
            raise ModelOrchError(f"model-orch embeddings failed: {response.status_code} {response.text[:500]}")

        data = response.json()
        try:
            items = sorted(data["data"], key=lambda item: item["index"])
        except (KeyError, TypeError) as exc:
            raise ModelOrchError(f"unexpected embeddings response shape: {data!r}") from exc

        return [
            EmbeddingResult(dense=item["embedding"], sparse=item.get("sparse_embedding") or {})
            for item in items
        ]


def _message_to_wire(message: ChatMessage) -> dict:
    # The orchestrator's ChatMessage schema is role/content only -- no
    # tool_call_id field to carry correspondence structurally. We fold the
    # tool name into the text itself for role="tool" replies; the model's
    # chat template resolves which call a result belongs to positionally.
    if message.role == "tool":
        prefix = f"[tool result: {message.name}]\n" if message.name else ""
        return {"role": "tool", "content": f"{prefix}{message.content}"}
    return {"role": message.role, "content": message.content}
