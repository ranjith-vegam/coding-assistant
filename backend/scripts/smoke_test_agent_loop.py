"""Manual smoke test: the real agent loop, real orchestrator, real tools,
against a throwaway workspace. Not part of pytest.

Run with: uv run python scripts/smoke_test_agent_loop.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from coding_assistant.agent.loop import AgentLoop
from coding_assistant.agent.prompts import build_system_prompt
from coding_assistant.agent.tools.registry import build_default_tools
from coding_assistant.llm.client import ModelOrchClient
from coding_assistant.llm.types import ChatMessage
from coding_assistant.permissions.gate import PermissionGate


async def auto_approve(call_id: str, name: str, arguments: dict) -> bool:
    print(f"  [auto-approving {name}({arguments})]")
    return True


async def main() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        workspace_root = Path(workspace)
        (workspace_root / "greeter.py").write_text(
            "def greet(name):\n"
            "    '''Return a friendly greeting for `name`.'''\n"
            "    return f'Hello, {name}!'\n"
        )

        client = ModelOrchClient()
        tools = build_default_tools()
        gate = PermissionGate(auto_approve)
        loop = AgentLoop(client, tools, gate, workspace_root)

        history = [
            ChatMessage(role="system", content=build_system_prompt(str(workspace_root))),
            ChatMessage(role="user", content="What does the greet function in greeter.py do? Read the file first."),
        ]

        async def emit(event: dict) -> None:
            print(event)

        try:
            await loop.run_turn(history, emit)
        finally:
            await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
