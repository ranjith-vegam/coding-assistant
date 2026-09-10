from fakeredis import aioredis as fakeredis

from coding_assistant.chat_store import ChatStore, DEFAULT_TITLE
from coding_assistant.llm.types import ChatMessage


def make_store() -> ChatStore:
    return ChatStore(fakeredis.FakeRedis(decode_responses=True))


async def test_create_chat_starts_empty_with_default_title():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")

    assert record.title == DEFAULT_TITLE
    assert record.messages == []
    assert record.chat_id.startswith("chat_")


async def test_created_chat_appears_in_list_chats():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")

    chats = await store.list_chats("alice@example.com")

    assert [c.chat_id for c in chats] == [record.chat_id]


async def test_load_chat_round_trips_messages():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")
    messages = [
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="assistant", content="hi there"),
        ChatMessage(role="tool", content="result text", name="read_file", tool_call_id="c1", is_error=True),
    ]

    await store.save_messages(record.chat_id, "alice@example.com", "/workspace", messages)
    loaded = await store.load_chat(record.chat_id)

    assert loaded is not None
    assert [m.role for m in loaded.messages] == ["user", "assistant", "tool"]
    assert loaded.messages[2].is_error is True
    assert loaded.messages[2].name == "read_file"
    assert loaded.messages[2].tool_call_id == "c1"


async def test_save_messages_derives_title_from_first_user_message():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")
    messages = [ChatMessage(role="user", content="please refactor the auth module")]

    await store.save_messages(record.chat_id, "alice@example.com", "/workspace", messages)
    loaded = await store.load_chat(record.chat_id)

    assert loaded.title == "please refactor the auth module"


async def test_save_messages_does_not_override_an_already_derived_title():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")
    await store.save_messages(record.chat_id, "alice@example.com", "/workspace", [ChatMessage(role="user", content="first question")])
    await store.save_messages(
        record.chat_id,
        "alice@example.com",
        "/workspace",
        [ChatMessage(role="user", content="first question"), ChatMessage(role="user", content="second question")],
    )

    loaded = await store.load_chat(record.chat_id)
    assert loaded.title == "first question"


async def test_long_title_is_truncated():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")
    long_text = "x" * 200

    await store.save_messages(record.chat_id, "alice@example.com", "/workspace", [ChatMessage(role="user", content=long_text)])
    loaded = await store.load_chat(record.chat_id)

    assert len(loaded.title) <= 61  # TITLE_MAX_CHARS + ellipsis
    assert loaded.title.endswith("…")


async def test_list_chats_orders_most_recently_updated_first():
    store = make_store()
    first = await store.create_chat("alice@example.com", "/workspace")
    second = await store.create_chat("alice@example.com", "/workspace")

    # bump `first`'s recency after `second` was created
    await store.save_messages(first.chat_id, "alice@example.com", "/workspace", [ChatMessage(role="user", content="hi")])

    chats = await store.list_chats("alice@example.com")
    assert chats[0].chat_id == first.chat_id
    assert chats[1].chat_id == second.chat_id


async def test_load_unknown_chat_returns_none():
    store = make_store()
    assert await store.load_chat("does_not_exist") is None


async def test_chats_are_isolated_per_user():
    store = make_store()
    await store.create_chat("alice@example.com", "/workspace")
    await store.create_chat("bob@example.com", "/workspace")

    alice_chats = await store.list_chats("alice@example.com")
    bob_chats = await store.list_chats("bob@example.com")

    assert len(alice_chats) == 1
    assert len(bob_chats) == 1
    assert alice_chats[0].chat_id != bob_chats[0].chat_id
