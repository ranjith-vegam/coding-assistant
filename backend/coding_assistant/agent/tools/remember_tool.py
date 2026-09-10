"""A tool the agent calls to persist a short, durable note -- see agent/memory.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_assistant.agent.memory import append_memory_note
from coding_assistant.agent.tools.base import ToolError, ToolResult


class RememberTool:
    name = "remember"
    description = (
        "Save a short, durable note that should apply to every future turn and session in this "
        "workspace -- use this whenever the user corrects a mistake you made, or states a "
        "preference/rule you should keep following (e.g. 'use tabs not spaces here', 'never touch "
        "the migrations folder', 'always run the tests after an edit'). Do not use this for "
        "task-specific details that only matter for the current request."
    )
    parameters = {
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "One short, self-contained sentence to remember"}
        },
        "required": ["note"],
    }
    requires_approval = False

    async def run(self, arguments: dict[str, Any], workspace_root: Path) -> ToolResult:
        note = str(arguments.get("note", "")).strip()
        if not note:
            raise ToolError("note must not be empty")
        append_memory_note(workspace_root, note)
        return ToolResult(content=f"Remembered: {note}")
