"""Approval gate for risky tools.

Deliberately owns no UI/transport concerns: it's handed an async callback
(`request_approval`) that does whatever it takes to ask a human, and it
awaits the answer. api/chat.py supplies the actual WebSocket round-trip.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol


class ApprovalDenied(Exception):
    """Raised when the user declines a risky tool call. Caught by the agent
    loop and turned into a role="tool" result -- never a hard failure."""


class RequiresApproval(Protocol):
    name: str
    requires_approval: bool


RequestApproval = Callable[[str, str, dict[str, Any]], Awaitable[bool]]
# (tool_call_id, tool_name, arguments) -> approved?


class PermissionGate:
    def __init__(self, request_approval: RequestApproval):
        self._request_approval = request_approval

    async def check(self, tool_call_id: str, tool: RequiresApproval, arguments: dict[str, Any]) -> None:
        if not tool.requires_approval:
            return
        approved = await self._request_approval(tool_call_id, tool.name, arguments)
        if not approved:
            raise ApprovalDenied(tool.name)
