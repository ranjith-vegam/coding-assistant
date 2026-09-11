from fakeredis import aioredis as fakeredis

from samixa_code.chat_store import ChatStore, DEFAULT_TITLE
from samixa_code.llm.types import ChatMessage


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

    chats = await store.list_chats("alice@example.com", "/workspace")

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


async def test_save_messages_uses_generated_title_over_the_heuristic():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")
    messages = [ChatMessage(role="user", content="please refactor the auth module")]

    await store.save_messages(
        record.chat_id, "alice@example.com", "/workspace", messages, generated_title="Refactor auth module"
    )
    loaded = await store.load_chat(record.chat_id)

    assert loaded.title == "Refactor auth module"


async def test_save_messages_falls_back_to_heuristic_when_no_generated_title():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")
    messages = [ChatMessage(role="user", content="please refactor the auth module")]

    await store.save_messages(record.chat_id, "alice@example.com", "/workspace", messages, generated_title=None)
    loaded = await store.load_chat(record.chat_id)

    assert loaded.title == "please refactor the auth module"


async def test_save_messages_never_overwrites_an_existing_real_title_with_a_generated_one():
    store = make_store()
    record = await store.create_chat("alice@example.com", "/workspace")
    await store.save_messages(
        record.chat_id, "alice@example.com", "/workspace", [ChatMessage(role="user", content="q1")], generated_title="First title"
    )

    await store.save_messages(
        record.chat_id,
        "alice@example.com",
        "/workspace",
        [ChatMessage(role="user", content="q1"), ChatMessage(role="user", content="q2")],
        generated_title="Should never apply",
    )

    loaded = await store.load_chat(record.chat_id)
    assert loaded.title == "First title"


async def test_list_chats_orders_most_recently_updated_first():
    store = make_store()
    first = await store.create_chat("alice@example.com", "/workspace")
    second = await store.create_chat("alice@example.com", "/workspace")

    # bump `first`'s recency after `second` was created
    await store.save_messages(first.chat_id, "alice@example.com", "/workspace", [ChatMessage(role="user", content="hi")])

    chats = await store.list_chats("alice@example.com", "/workspace")
    assert chats[0].chat_id == first.chat_id
    assert chats[1].chat_id == second.chat_id


async def test_load_unknown_chat_returns_none():
    store = make_store()
    assert await store.load_chat("does_not_exist") is None


async def test_chats_are_isolated_per_user():
    store = make_store()
    await store.create_chat("alice@example.com", "/workspace")
    await store.create_chat("bob@example.com", "/workspace")

    alice_chats = await store.list_chats("alice@example.com", "/workspace")
    bob_chats = await store.list_chats("bob@example.com", "/workspace")

    assert len(alice_chats) == 1
    assert len(bob_chats) == 1
    assert alice_chats[0].chat_id != bob_chats[0].chat_id


async def test_chats_are_isolated_per_workspace_for_the_same_user():
    """The actual feature: opening a different project must not show chats
    from another one, even for the same signed-in user."""
    store = make_store()
    project_a = await store.create_chat("alice@example.com", "/home/alice/project-a")
    project_b = await store.create_chat("alice@example.com", "/home/alice/project-b")

    a_chats = await store.list_chats("alice@example.com", "/home/alice/project-a")
    b_chats = await store.list_chats("alice@example.com", "/home/alice/project-b")

    assert [c.chat_id for c in a_chats] == [project_a.chat_id]
    assert [c.chat_id for c in b_chats] == [project_b.chat_id]


async def test_a_third_unrelated_workspace_sees_no_chats():
    store = make_store()
    await store.create_chat("alice@example.com", "/home/alice/project-a")

    chats = await store.list_chats("alice@example.com", "/home/alice/never-opened-before")

    assert chats == []


async def test_legacy_global_chats_are_migrated_into_the_correct_workspace_on_first_list():
    """Chats created before per-workspace scoping existed only live in the
    old global {user_id}:chat_ids index. The first list_chats call for the
    workspace they actually belong to must find them (not silently orphan
    them), and only them -- not chats belonging to some other workspace
    that also predates the scoping change."""
    store = make_store()

    # Simulate pre-existing data written the OLD way: directly against the
    # legacy global key, bypassing the new workspace-scoped create_chat.
    from samixa_code.chat_store import _legacy_user_chats_key

    project_a_record = await store.create_chat("alice@example.com", "/home/alice/project-a")
    project_b_record = await store.create_chat("alice@example.com", "/home/alice/project-b")
    # Undo the (new-style) workspace-scoped indexing those create_chat calls
    # just did, and re-index them the OLD way instead, to faithfully
    # reproduce "data from before this change existed".
    from samixa_code.chat_store import _user_workspace_chats_key

    await store._client.delete(_user_workspace_chats_key("alice@example.com", "/home/alice/project-a"))
    await store._client.delete(_user_workspace_chats_key("alice@example.com", "/home/alice/project-b"))
    await store._client.zadd(_legacy_user_chats_key("alice@example.com"), {project_a_record.chat_id: 1, project_b_record.chat_id: 2})

    a_chats = await store.list_chats("alice@example.com", "/home/alice/project-a")

    assert [c.chat_id for c in a_chats] == [project_a_record.chat_id]

    # And now that it's migrated, a second call must not need the legacy
    # index at all -- confirm it actually landed in the new scoped key.
    from samixa_code.chat_store import _user_workspace_chats_key as scoped_key

    migrated = await store._client.zrange(scoped_key("alice@example.com", "/home/alice/project-a"), 0, -1)
    assert migrated == [project_a_record.chat_id]
