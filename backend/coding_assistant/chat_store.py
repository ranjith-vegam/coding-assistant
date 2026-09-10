"""Redis-backed chat persistence -- so a chat survives a VS Code window
reload, and a user can see/resume past chats after reconnecting.

Key schema (plain string + JSON, not RedisJSON -- works against any Redis,
not just redis-stack, even though that's what's actually running here):

  coding-assistant:{user_id}:chat_ids   ZSET   member=chat_id, score=updated_at
  coding-assistant:chat:{chat_id}       STRING JSON blob (see ChatRecord)

The ZSET gives recency ordering for free (ZREVRANGE) and cheap membership
checks, without needing a second index.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from functools import lru_cache

import redis.asyncio as redis

from coding_assistant.llm.types import ChatMessage
from coding_assistant.settings import get_settings

DEFAULT_TITLE = "New Chat"
# A title generated from the first user message, capped so the chat-list
# dropdown stays a one-liner per entry.
TITLE_MAX_CHARS = 60


def _user_chats_key(user_id: str) -> str:
    return f"coding-assistant:{user_id}:chat_ids"


def _chat_key(chat_id: str) -> str:
    return f"coding-assistant:chat:{chat_id}"


@dataclass
class ChatSummary:
    chat_id: str
    title: str
    workspace_root: str
    updated_at: float


@dataclass
class ChatRecord:
    chat_id: str
    user_id: str
    workspace_root: str
    title: str
    created_at: float
    updated_at: float
    messages: list[ChatMessage] = field(default_factory=list)


def _message_to_dict(message: ChatMessage) -> dict:
    return asdict(message)


def _message_from_dict(data: dict) -> ChatMessage:
    return ChatMessage(
        role=data["role"],
        content=data["content"],
        tool_call_id=data.get("tool_call_id"),
        name=data.get("name"),
        is_error=data.get("is_error", False),
    )


class ChatStore:
    def __init__(self, client: redis.Redis):
        self._client = client

    async def create_chat(self, user_id: str, workspace_root: str) -> ChatRecord:
        now = time.time()
        record = ChatRecord(
            chat_id=f"chat_{uuid.uuid4().hex[:16]}",
            user_id=user_id,
            workspace_root=workspace_root,
            title=DEFAULT_TITLE,
            created_at=now,
            updated_at=now,
            messages=[],
        )
        await self._write(record)
        await self._client.zadd(_user_chats_key(user_id), {record.chat_id: now})
        return record

    async def load_chat(self, chat_id: str) -> ChatRecord | None:
        raw = await self._client.get(_chat_key(chat_id))
        if raw is None:
            return None
        data = json.loads(raw)
        return ChatRecord(
            chat_id=data["chat_id"],
            user_id=data["user_id"],
            workspace_root=data["workspace_root"],
            title=data["title"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            messages=[_message_from_dict(m) for m in data["messages"]],
        )

    async def save_messages(self, chat_id: str, user_id: str, workspace_root: str, messages: list[ChatMessage]) -> None:
        """Overwrites a chat's message list wholesale -- simpler and safer
        than trying to append incrementally against a JSON blob, and chats
        are small enough (a handful of turns) that this is cheap."""
        existing = await self.load_chat(chat_id)
        now = time.time()
        created_at = existing.created_at if existing else now
        title = existing.title if existing else DEFAULT_TITLE
        if title == DEFAULT_TITLE:
            title = _derive_title(messages) or title

        record = ChatRecord(
            chat_id=chat_id,
            user_id=user_id,
            workspace_root=workspace_root,
            title=title,
            created_at=created_at,
            updated_at=now,
            messages=messages,
        )
        await self._write(record)
        await self._client.zadd(_user_chats_key(user_id), {chat_id: now})

    async def list_chats(self, user_id: str, limit: int = 50) -> list[ChatSummary]:
        chat_ids = await self._client.zrevrange(_user_chats_key(user_id), 0, limit - 1)
        if not chat_ids:
            return []
        raw_records = await self._client.mget([_chat_key(cid) for cid in chat_ids])
        summaries: list[ChatSummary] = []
        for cid, raw in zip(chat_ids, raw_records):
            if raw is None:
                continue  # chat_id was in the index but the blob expired/was deleted -- skip, don't crash
            data = json.loads(raw)
            summaries.append(
                ChatSummary(
                    chat_id=data["chat_id"],
                    title=data["title"],
                    workspace_root=data["workspace_root"],
                    updated_at=data["updated_at"],
                )
            )
        return summaries

    async def _write(self, record: ChatRecord) -> None:
        data = {
            "chat_id": record.chat_id,
            "user_id": record.user_id,
            "workspace_root": record.workspace_root,
            "title": record.title,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "messages": [_message_to_dict(m) for m in record.messages],
        }
        await self._client.set(_chat_key(record.chat_id), json.dumps(data))


def _derive_title(messages: list[ChatMessage]) -> str | None:
    first_user = next((m for m in messages if m.role == "user"), None)
    if first_user is None:
        return None
    text = " ".join(first_user.content.split())
    if len(text) > TITLE_MAX_CHARS:
        text = text[:TITLE_MAX_CHARS].rstrip() + "…"
    return text or None


@lru_cache
def get_redis_client() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


def get_chat_store() -> ChatStore:
    return ChatStore(get_redis_client())
