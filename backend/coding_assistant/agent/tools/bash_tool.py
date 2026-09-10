"""Shell command execution -- the highest-risk tool, always approval-gated.

No command allow/deny filtering in v1: the permission gate (every call
requires explicit user approval, surfaced with the exact command text) is the
safety control here, same posture as Claude Code's own Bash approval model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from coding_assistant.agent.tools.base import ToolError, ToolResult

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
# See fs_tools.py MAX_RETURNED_CHARS comment -- deployed context window is
# 16384 tokens TOTAL; 20_000 chars of command output alone could exceed it.
MAX_OUTPUT_CHARS = 4_000


class RunCommandTool:
    name = "run_command"
    description = (
        "Run a shell command in the workspace root (e.g. tests, builds, git). Requires explicit "
        "user approval every time. Do not use this to read or write files -- use the dedicated tools."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer", "description": "Max seconds to wait (default 30, max 120)"},
        },
        "required": ["command"],
    }
    requires_approval = True

    async def run(self, arguments: dict[str, Any], workspace_root: Path) -> ToolResult:
        command = arguments.get("command")
        if not command:
            raise ToolError("command must not be empty")
        timeout = min(int(arguments.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS)

        try:
            proc = await asyncio.create_subprocess_shell(
                str(command),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(workspace_root),
            )
        except OSError as exc:
            raise ToolError(f"failed to start command: {exc}") from None

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise ToolError(f"command timed out after {timeout}s") from None
        except asyncio.CancelledError:
            # The user hit Stop while this was running. asyncio.wait_for
            # being cancelled does NOT kill the underlying OS process on its
            # own -- without this, a cancelled run_command leaves an orphaned
            # child process running after the tool call "stopped".
            proc.kill()
            raise

        output = stdout.decode(errors="replace")
        truncated = len(output) > MAX_OUTPUT_CHARS
        if truncated:
            output = output[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"

        return ToolResult(content=f"{output}\n[exit code: {proc.returncode}]", is_error=(proc.returncode != 0))
