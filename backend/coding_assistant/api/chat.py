"""Chat WebSocket -- backed by the real agent loop (tools + approval gate)
and Redis-backed chat persistence (see chat_store.py).

Wire protocol (JSON over one WebSocket connection):

  client -> server:
    {"type": "init", "workspace_root": "<path>", "user_id": "<email>", "chat_id": "<optional, resume>"}
    {"type": "send", "content": "<user text>"}
    {"type": "approval_response", "id": "<tool_call id>", "approved": true|false}
    {"type": "cancel"}
    {"type": "rewind", "checkpoint_id": "...", "restore_code": bool, "restore_conversation": bool}
    {"type": "new_chat"}
    {"type": "switch_chat", "chat_id": "..."}
    {"type": "list_chats"}

  server -> client:
    {"type": "status", "status": "thinking"}
    {"type": "message", "text": ..., "thinking": ..., "final": bool}
    {"type": "tool_call", "id": ..., "name": ..., "arguments": {...}}
    {"type": "tool_result", "id": ..., "name": ..., "content": ..., "is_error": bool}
    {"type": "approval_request", "id": ..., "name": ..., "arguments": {...}}
    {"type": "checkpoint_created", "id": ...}
    {"type": "rewound", "checkpoint_id": ..., "restored_code": bool, "restored_conversation": bool,
                         "restored_files": [...], "skipped_files": [...]}
    {"type": "chat_ready", "chat_id": ..., "title": ..., "items": [...]}   -- full reconstructed
                                                                              timeline for this chat
                                                                              (see agent/history_replay.py),
                                                                              sent on init/new_chat/switch_chat
    {"type": "chat_list", "chats": [{chat_id, title, workspace_root, updated_at}, ...]}
    {"type": "cancelled"}
    {"type": "error", "message": ...}

One connection can move between chats (new_chat/switch_chat) without
reconnecting -- `session` (a plain dict, same one-item-holder trick as
current_run_task below) holds whichever chat is currently active so the
reader/turn_processor tasks always operate on the current one, not one
captured at connection time.

No real token streaming yet -- see settings.py on why. "thinking" status is
the only interim signal before a "message" event lands.

Concurrency note: a single `while True: receive_json()` loop that also calls
`run_turn()` inline would deadlock -- run_turn blocks awaiting an approval
future, but the only thing that can resolve that future is the very message
read that's blocked behind run_turn returning. So reading and turn-processing
run as two concurrent tasks: `_reader` only ever reads and dispatches
(resolving approval futures immediately, queuing "send" messages, cancelling
the in-flight turn on "cancel"), and the main task drains the queue and runs
turns one at a time. Each turn runs as its OWN task (not just an awaited
coroutine) specifically so `cancel` has something to call .cancel() on
without also killing the processor's own "wait for the next message" loop.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from coding_assistant.agent.history_replay import history_to_display_items
from coding_assistant.agent.loop import AgentLoop
from coding_assistant.agent.memory import load_memory
from coding_assistant.agent.prompts import build_system_prompt
from coding_assistant.agent.tools.registry import build_default_tools
from coding_assistant.chat_store import ChatRecord, get_chat_store
from coding_assistant.llm.client import ModelOrchClient
from coding_assistant.llm.types import ChatMessage
from coding_assistant.permissions.gate import PermissionGate

logger = logging.getLogger(__name__)

router = APIRouter()

# How long to wait for the user to approve/deny a risky tool call before
# treating it as denied. A stuck approval must not hang the loop forever.
APPROVAL_TIMEOUT_SECONDS = 300

DEFAULT_USER_ID = "anonymous"  # used if the extension hasn't set up an identity yet


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    # --- Handshake: the first message must set the workspace root. The
    # backend has no other way to know what folder VS Code has open. ---
    try:
        init = await websocket.receive_json()
    except WebSocketDisconnect:
        return

    workspace_root_raw = init.get("workspace_root") if init.get("type") == "init" else None
    if not workspace_root_raw:
        await websocket.send_json({"type": "error", "message": "First message must be {type: 'init', workspace_root: <path>}"})
        await websocket.close()
        return

    workspace_root = Path(workspace_root_raw).resolve()
    if not workspace_root.is_dir():
        await websocket.send_json({"type": "error", "message": f"workspace_root does not exist: {workspace_root}"})
        await websocket.close()
        return

    user_id = init.get("user_id") or DEFAULT_USER_ID

    client = ModelOrchClient()
    tools = build_default_tools()
    store = get_chat_store()
    pending_approvals: dict[str, asyncio.Future] = {}
    send_queue: asyncio.Queue[str] = asyncio.Queue()
    # One-item holders so reader()/turn_processor() closures see live state
    # without needing `nonlocal` into each other's scope (same trick for both).
    current_run_task: dict[str, asyncio.Task | None] = {"task": None}
    session: dict[str, object] = {}  # "chat_id" / "history" / "loop" -- see enter_chat()

    async def emit(event: dict) -> None:
        await websocket.send_json(event)

    async def request_approval(tool_call_id: str, tool_name: str, arguments: dict) -> bool:
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        pending_approvals[tool_call_id] = future
        await websocket.send_json({"type": "approval_request", "id": tool_call_id, "name": tool_name, "arguments": arguments})
        try:
            return await asyncio.wait_for(future, timeout=APPROVAL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return False
        finally:
            pending_approvals.pop(tool_call_id, None)

    gate = PermissionGate(request_approval)

    async def enter_chat(record: ChatRecord) -> None:
        """Makes `record` the active chat for this connection -- (re)builds
        the in-memory history/AgentLoop and tells the frontend the full
        reconstructed timeline. Only call while no turn is in flight."""
        system_prompt = build_system_prompt(str(workspace_root), memory=load_memory(workspace_root))
        session["chat_id"] = record.chat_id
        session["history"] = [ChatMessage(role="system", content=system_prompt), *record.messages]
        session["loop"] = AgentLoop(client, tools, gate, workspace_root)
        await emit(
            {
                "type": "chat_ready",
                "chat_id": record.chat_id,
                "title": record.title,
                "items": history_to_display_items(record.messages),
            }
        )

    async def persist_active_chat() -> None:
        history: list[ChatMessage] = session["history"]  # type: ignore[assignment]
        await store.save_messages(session["chat_id"], user_id, str(workspace_root), history[1:])  # skip the system message

    def turn_in_progress() -> bool:
        task = current_run_task["task"]
        return bool(task and not task.done())

    # --- Initial chat: resume the requested chat_id if it's real and owned
    # by this user, otherwise start a fresh one. ---
    requested_chat_id = init.get("chat_id")
    initial_record = await store.load_chat(requested_chat_id) if requested_chat_id else None
    if initial_record is not None and initial_record.user_id != user_id:
        initial_record = None  # never load another user's chat just because its id was guessed/stale
    if initial_record is None:
        initial_record = await store.create_chat(user_id, str(workspace_root))
    await enter_chat(initial_record)

    async def reader() -> None:
        # Runs for the life of the connection, independent of whether a turn
        # is currently in flight -- this is what lets an approval_response
        # (or a cancel) arrive and take effect while run_turn() is mid-await.
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type", "send")

            if message_type == "approval_response":
                future = pending_approvals.get(data.get("id"))
                if future and not future.done():
                    future.set_result(bool(data.get("approved", False)))
                continue

            if message_type == "cancel":
                task = current_run_task["task"]
                if task and not task.done():
                    task.cancel()
                continue

            if message_type == "rewind":
                if turn_in_progress():
                    await emit({"type": "error", "message": "Cannot rewind while a turn is in progress -- stop it first."})
                    continue
                checkpoint_id = data.get("checkpoint_id")
                restore_code = bool(data.get("restore_code", True))
                restore_conversation = bool(data.get("restore_conversation", True))
                loop: AgentLoop = session["loop"]  # type: ignore[assignment]
                history: list[ChatMessage] = session["history"]  # type: ignore[assignment]
                try:
                    result = loop.rewind(
                        checkpoint_id, history, restore_code=restore_code, restore_conversation=restore_conversation
                    )
                except ValueError as exc:
                    await emit({"type": "error", "message": str(exc)})
                    continue
                await persist_active_chat()
                await emit(
                    {
                        "type": "rewound",
                        "checkpoint_id": checkpoint_id,
                        "restored_code": restore_code,
                        "restored_conversation": restore_conversation,
                        "restored_files": result.restored,
                        "skipped_files": result.skipped,
                    }
                )
                continue

            if message_type == "new_chat":
                if turn_in_progress():
                    await emit({"type": "error", "message": "Cannot start a new chat while a turn is in progress -- stop it first."})
                    continue
                record = await store.create_chat(user_id, str(workspace_root))
                await enter_chat(record)
                continue

            if message_type == "switch_chat":
                if turn_in_progress():
                    await emit({"type": "error", "message": "Cannot switch chats while a turn is in progress -- stop it first."})
                    continue
                target_id = data.get("chat_id")
                record = await store.load_chat(target_id) if target_id else None
                if record is None or record.user_id != user_id:
                    await emit({"type": "error", "message": "Chat not found."})
                    continue
                await enter_chat(record)
                continue

            if message_type == "list_chats":
                chats = await store.list_chats(user_id)
                await emit({"type": "chat_list", "chats": [dataclasses.asdict(c) for c in chats]})
                continue

            if message_type == "send" and data.get("content"):
                await send_queue.put(data["content"])

    async def turn_processor() -> None:
        while True:
            user_text = await send_queue.get()
            history: list[ChatMessage] = session["history"]  # type: ignore[assignment]
            loop: AgentLoop = session["loop"]  # type: ignore[assignment]
            history.append(ChatMessage(role="user", content=user_text))

            task = asyncio.create_task(loop.run_turn(history, emit))
            current_run_task["task"] = task
            try:
                await task
            except asyncio.CancelledError:
                await emit({"type": "cancelled"})
            finally:
                current_run_task["task"] = None
                await persist_active_chat()

    reader_task = asyncio.create_task(reader())
    processor_task = asyncio.create_task(turn_processor())
    try:
        # Either task ending (client disconnect surfaces in reader_task;
        # turn_processor never returns on its own) means the connection is
        # done -- cancel whichever is still running and surface any real error.
        done, pending = await asyncio.wait({reader_task, processor_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                raise exc
    finally:
        for future in pending_approvals.values():
            if not future.done():
                future.cancel()
        await client.aclose()
