"""Filesystem tools: read, list, write, exact-match edit.

All path arguments go through resolve_in_workspace -- see base.py. Read/list
are safe (requires_approval=False); write/edit mutate the workspace and are
gated behind approval.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from samixa_code.agent.tools.base import ToolError, ToolResult, resolve_in_workspace

# Confirmed live against the real model-orch deployment: its context window
# is 16384 tokens TOTAL. These are sized so one read_file call can't blow
# that by itself (~3.2 chars/token estimate -- see llm/token_budget.py),
# leaving room for the system prompt, tool schemas, and prior turns.
MAX_READ_LINES = 300
MAX_READ_BYTES = 128 * 1024
MAX_RETURNED_CHARS = 6000

# Directories never worth walking into for a coding agent -- noise at best,
# hundreds of thousands of irrelevant files at worst on a real repo.
_SKIP_DIR_NAMES = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".turbo", "target", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
}


class ReadFileTool:
    name = "read_file"
    description = (
        "Read a file from the workspace. Returns up to 300 lines; use `offset`/`limit` "
        "to page through a larger file -- prefer several narrow reads over one huge one, "
        "the model's context window is limited. Always read a file before editing it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root (or absolute, inside it)"},
            "offset": {"type": "integer", "description": "1-indexed line to start from (default 1)"},
            "limit": {"type": "integer", "description": "Max lines to return (default 300)"},
        },
        "required": ["path"],
    }
    requires_approval = False

    async def run(self, arguments: dict[str, Any], workspace_root: Path) -> ToolResult:
        path = resolve_in_workspace(workspace_root, str(arguments.get("path", "")))
        if not path.exists():
            raise ToolError(f"no such file: {arguments.get('path')}")
        if path.is_dir():
            raise ToolError(f"'{arguments.get('path')}' is a directory, not a file -- use list_dir")
        if path.stat().st_size > MAX_READ_BYTES:
            raise ToolError(
                f"'{arguments.get('path')}' is larger than {MAX_READ_BYTES // 1024}KB; "
                "use offset/limit to read it in windows"
            )

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ToolError(f"could not read '{arguments.get('path')}': {exc}") from None

        lines = text.splitlines()
        offset = max(1, int(arguments.get("offset") or 1))
        # Clamped, not just defaulted -- a requested limit larger than
        # MAX_READ_LINES must not bypass the budget this cap exists for.
        limit = min(int(arguments.get("limit") or MAX_READ_LINES), MAX_READ_LINES)
        window = lines[offset - 1 : offset - 1 + limit]

        numbered = "\n".join(f"{offset + i:6d}\t{line}" for i, line in enumerate(window))
        truncated_note = ""
        if offset - 1 + limit < len(lines):
            truncated_note = f"\n... ({len(lines) - (offset - 1 + limit)} more lines, use offset={offset + limit})"

        # Belt-and-suspenders: a 300-line window of very long lines (minified
        # JS, generated code) can still be huge in characters even under the
        # line cap. This is the hard backstop against overflowing the model's
        # context window regardless of line count.
        content = numbered + truncated_note
        if len(content) > MAX_RETURNED_CHARS:
            content = content[:MAX_RETURNED_CHARS] + "\n... (truncated to fit the model's context window; use a narrower offset/limit)"
        return ToolResult(content=content)


class ListDirTool:
    name = "list_dir"
    description = "List files and subdirectories directly inside a workspace directory (non-recursive)."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory path, relative to the workspace root"}},
        "required": ["path"],
    }
    requires_approval = False

    async def run(self, arguments: dict[str, Any], workspace_root: Path) -> ToolResult:
        path = resolve_in_workspace(workspace_root, str(arguments.get("path", ".")))
        if not path.is_dir():
            raise ToolError(f"'{arguments.get('path')}' is not a directory")

        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        lines = []
        for entry in entries:
            if entry.name in _SKIP_DIR_NAMES:
                continue
            lines.append(f"{'d' if entry.is_dir() else 'f'}  {entry.name}")
        return ToolResult(content="\n".join(lines) or "(empty directory)")


class WriteFileTool:
    name = "write_file"
    description = "Create a file or overwrite it entirely with new content. Prefer edit_file for small changes."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace root"},
            "content": {"type": "string", "description": "Full file content to write"},
        },
        "required": ["path", "content"],
    }
    requires_approval = True

    async def run(self, arguments: dict[str, Any], workspace_root: Path) -> ToolResult:
        path = resolve_in_workspace(workspace_root, str(arguments.get("path", "")))
        content = arguments.get("content")
        if content is None:
            raise ToolError("write_file requires 'content'")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        # Line count, not byte size -- more useful to the model (and to a
        # human reading the tool-call log) for judging whether a write did
        # roughly what was intended than an opaque byte count.
        line_count = len(content.splitlines())
        return ToolResult(content=f"wrote {line_count} line{'s' if line_count != 1 else ''} to {arguments.get('path')}")


class EditFileTool:
    name = "edit_file"
    description = (
        "Replace an exact, unique text match in a file with new text. Fails if old_string "
        "isn't found or matches more than once (unless replace_all is true) -- read the file "
        "first so old_string matches exactly, including whitespace."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to find; must be unique unless replace_all"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence instead of requiring one"},
        },
        "required": ["path", "old_string", "new_string"],
    }
    requires_approval = True

    async def run(self, arguments: dict[str, Any], workspace_root: Path) -> ToolResult:
        path = resolve_in_workspace(workspace_root, str(arguments.get("path", "")))
        if not path.is_file():
            raise ToolError(f"no such file: {arguments.get('path')}")

        old_string = arguments.get("old_string", "")
        new_string = arguments.get("new_string", "")
        replace_all = bool(arguments.get("replace_all", False))
        if not old_string:
            raise ToolError("old_string must not be empty")

        text = path.read_text(encoding="utf-8", errors="replace")
        count = text.count(old_string)
        if count == 0:
            raise ToolError("old_string not found in file -- read the file again, it may have changed")
        if count > 1 and not replace_all:
            raise ToolError(f"old_string is not unique ({count} occurrences) -- add context or pass replace_all")

        new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        path.write_text(new_text, encoding="utf-8")
        return ToolResult(content=f"edited {arguments.get('path')} ({count if replace_all else 1} replacement(s))")
