from coding_assistant.agent.memory import MAX_MEMORY_CHARS, append_memory_note, load_memory, memory_path


def test_load_memory_returns_none_when_file_does_not_exist(tmp_path):
    assert load_memory(tmp_path) is None


def test_append_then_load_round_trips(tmp_path):
    append_memory_note(tmp_path, "use tabs not spaces here")

    memory = load_memory(tmp_path)
    assert memory is not None
    assert "use tabs not spaces here" in memory


def test_append_multiple_notes_keeps_all_of_them(tmp_path):
    append_memory_note(tmp_path, "first note")
    append_memory_note(tmp_path, "second note")

    memory = load_memory(tmp_path)
    assert "first note" in memory
    assert "second note" in memory


def test_memory_file_lives_under_dot_samixa(tmp_path):
    append_memory_note(tmp_path, "note")
    path = memory_path(tmp_path)
    assert path.parent.name == ".samixa"
    assert path.name == "MEMORY.md"
    assert path.is_file()


def test_empty_file_on_disk_loads_as_none_not_empty_string(tmp_path):
    path = memory_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("   \n  ")
    assert load_memory(tmp_path) is None


def test_growing_past_max_chars_drops_oldest_notes_not_the_whole_file():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # ~90 chars/note * 150 =~ 13.5k chars, well over MAX_MEMORY_CHARS (4000)
        # -- 50 short notes in an earlier version of this test never actually
        # exceeded the cap, so truncation never ran and the assertion below
        # was vacuously true. Confirmed exceeding the cap this time (asserted
        # via the total-length check).
        for i in range(150):
            append_memory_note(root, f"note number {i:04d} with some padding text to grow the file over time")

        memory = load_memory(root)
        assert memory is not None
        assert len(memory) <= MAX_MEMORY_CHARS + 200  # header/formatting slack
        # the most recent note must have survived; an early one should not have
        assert "note number 0149" in memory
        assert "note number 0000 " not in memory


def test_new_note_after_truncation_still_appends_correctly(tmp_path):
    for i in range(50):
        append_memory_note(tmp_path, f"note {i} " + "x" * 100)

    append_memory_note(tmp_path, "final note")
    memory = load_memory(tmp_path)
    assert "final note" in memory
