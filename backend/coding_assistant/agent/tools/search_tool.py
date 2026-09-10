"""Literal/regex code search over the workspace, via ripgrep.

Zero indexing, always current -- the tool the agent should reach for whenever
it knows a symbol/string to look for. Complements (does not replace) the
retrieval layer being built in retrieval/ for natural-language queries.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from coding_assistant.agent.tools.base import ToolError, ToolResult, resolve_in_workspace

# See fs_tools.py MAX_RETURNED_CHARS comment -- same 16384-token deployed
# context window, same reasoning: a big match set must not overflow it alone.
MAX_MATCHES = 50
MAX_RETURNED_CHARS = 6000
SEARCH_TIMEOUT_SECONDS = 30


class SearchCodeTool:
    name = "search_code"
    description = (
        "Search the workspace for a literal string or regex pattern (via ripgrep). Returns "
        "matching file:line:text, capped to the first 200 matches. Use this for known symbols, "
        "strings, or patterns -- not for vague natural-language questions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {
                "type": "string",
                "description": "Subdirectory to restrict the search to (default: whole workspace)",
            },
            "regex": {"type": "boolean", "description": "Treat query as a regex instead of a literal string"},
        },
        "required": ["query"],
    }
    requires_approval = False

    async def run(self, arguments: dict[str, Any], workspace_root: Path) -> ToolResult:
        query = arguments.get("query")
        if not query:
            raise ToolError("query must not be empty")

        search_root = workspace_root
        if arguments.get("path"):
            search_root = resolve_in_workspace(workspace_root, str(arguments["path"]))

        command = ["rg", "--line-number", "--no-heading", "--max-count", "50", "--color", "never"]
        if not arguments.get("regex", False):
            command.append("--fixed-strings")
        command += [str(query), str(search_root)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workspace_root),
            )
        except FileNotFoundError:
            raise ToolError("ripgrep ('rg') is not installed on this backend host") from None

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SEARCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            raise ToolError(f"search timed out after {SEARCH_TIMEOUT_SECONDS}s") from None

        # rg exit code 1 means "ran fine, no matches" -- not an error.
        if proc.returncode not in (0, 1):
            raise ToolError(f"search failed: {stderr.decode(errors='replace')[:500]}")

        lines = stdout.decode(errors="replace").splitlines()
        truncated = len(lines) > MAX_MATCHES
        lines = lines[:MAX_MATCHES]
        # rg reports absolute paths (we passed an absolute search root); show
        # workspace-relative paths since that's what the model should cite back.
        prefix = str(workspace_root.resolve()) + "/"
        rel_lines = [line.replace(prefix, "") for line in lines]

        content = "\n".join(rel_lines) or "(no matches)"
        if truncated:
            content += f"\n... (truncated to {MAX_MATCHES} matches; narrow the query or path)"
        if len(content) > MAX_RETURNED_CHARS:
            content = content[:MAX_RETURNED_CHARS] + "\n... (truncated to fit the model's context window; narrow the query or path)"
        return ToolResult(content=content)
