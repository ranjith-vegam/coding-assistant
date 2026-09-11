"""Manual smoke test: the real agent loop, real orchestrator, real tools,
against a throwaway workspace. Not part of pytest.

Run with: uv run python scripts/smoke_test_agent_loop.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from samixa_code.agent.loop import AgentLoop
from samixa_code.agent.prompts import build_system_prompt
from samixa_code.agent.tools.registry import build_default_tools
from samixa_code.llm.client import ModelOrchClient
from samixa_code.llm.types import ChatMessage
from samixa_code.permissions.gate import PermissionGate


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
