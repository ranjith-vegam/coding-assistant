"""Manual smoke test against the real model-orchestrator -- not part of pytest.

Run with: uv run python scripts/smoke_test_client.py
"""

from __future__ import annotations

import asyncio

from coding_assistant.llm.client import ModelOrchClient
from coding_assistant.llm.types import ChatMessage, ToolDefinition


async def main() -> None:
    client = ModelOrchClient()
    try:
        print("=== plain chat ===")
        result = await client.chat([ChatMessage(role="user", content="Say hello in exactly 3 words.")])
        print("thinking:", (result.thinking or "")[:80], "...")
        print("text:", result.text)
        print("tool_calls:", result.tool_calls)
        print()

        print("=== tool-calling chat ===")
        tools = [
            ToolDefinition(
                name="read_file",
                description="Read a file from the local filesystem and return its contents.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Absolute path to the file"}},
                    "required": ["path"],
                },
            )
        ]
        result = await client.chat(
            [ChatMessage(role="user", content="Read the file located at /tmp/foo.txt and tell me its contents.")],
            tools=tools,
        )
        print("text:", repr(result.text))
        print("tool_calls:", result.tool_calls)
        print("possibly_truncated:", result.possibly_truncated)
        print()

        print("=== embeddings ===")
        embeddings = await client.embed(["def add(a, b):\n    return a + b"])
        print("dense len:", len(embeddings[0].dense))
        print("sparse terms:", len(embeddings[0].sparse))
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
