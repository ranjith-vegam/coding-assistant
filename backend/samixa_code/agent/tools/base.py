"""Tool contract + the one safety primitive every filesystem tool depends on.

`resolve_in_workspace` is the path-traversal guard: every tool that takes a
path argument must run it through this before touching disk. A model asked
for "../../etc/passwd" or an absolute path outside the workspace gets a
ToolError, not a read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class ToolError(Exception):
    """Raised for an expected, tool-level failure (bad path, bad args, ...).

    Caught by the agent loop and turned into a role="tool" error result fed
    back to the model -- never propagates up and kills the turn.
    """


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]
    # Gates execution behind the permission gate (see permissions/gate.py).
    # True for anything that writes, executes, or could exfiltrate data.
    requires_approval: bool

    async def run(self, arguments: dict[str, Any], workspace_root: Path) -> ToolResult: ...


def resolve_in_workspace(workspace_root: Path, raw_path: str) -> Path:
    """Resolve `raw_path` (relative or absolute) against workspace_root and
    verify the result doesn't escape it.

    Mirrors the safeJoinUnderRoot pattern used elsewhere in this codebase's
    sibling projects for exactly this reason: `../../../etc/passwd` or an
    unrelated absolute path must fail here, not three lines later.
    """
    if not raw_path:
        raise ToolError("path must not be empty")

    candidate = Path(raw_path)
    resolved = (workspace_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()

    workspace_resolved = workspace_root.resolve()
    try:
        resolved.relative_to(workspace_resolved)
    except ValueError:
        raise ToolError(
            f"path '{raw_path}' resolves outside the workspace root ({workspace_resolved}); refusing"
        ) from None

    return resolved
