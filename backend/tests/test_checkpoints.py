from coding_assistant.agent.checkpoints import CheckpointStore, restore_files


def test_record_pre_edit_state_captures_existing_content_once(tmp_path):
    (tmp_path / "a.py").write_text("original")
    store = CheckpointStore()
    checkpoint = store.start_checkpoint(history_index=1)

    store.record_pre_edit_state(checkpoint, tmp_path / "a.py", tmp_path)
    (tmp_path / "a.py").write_text("changed once")
    store.record_pre_edit_state(checkpoint, tmp_path / "a.py", tmp_path)  # second edit, same turn

    assert checkpoint.file_snapshots["a.py"] == "original"  # first-write baseline, not the intermediate edit


def test_record_pre_edit_state_records_none_for_a_file_that_did_not_exist(tmp_path):
    store = CheckpointStore()
    checkpoint = store.start_checkpoint(history_index=0)

    store.record_pre_edit_state(checkpoint, tmp_path / "new.py", tmp_path)

    assert checkpoint.file_snapshots["new.py"] is None


def test_restore_files_writes_back_original_content(tmp_path):
    (tmp_path / "a.py").write_text("original")
    store = CheckpointStore()
    checkpoint = store.start_checkpoint(history_index=0)
    store.record_pre_edit_state(checkpoint, tmp_path / "a.py", tmp_path)
    (tmp_path / "a.py").write_text("modified by the agent")

    result = restore_files(checkpoint, tmp_path)

    assert (tmp_path / "a.py").read_text() == "original"
    assert result.restored == ["a.py"]
    assert result.skipped == []


def test_restore_files_deletes_a_file_that_did_not_exist_at_checkpoint_time(tmp_path):
    store = CheckpointStore()
    checkpoint = store.start_checkpoint(history_index=0)
    store.record_pre_edit_state(checkpoint, tmp_path / "new.py", tmp_path)
    (tmp_path / "new.py").write_text("created by the agent")

    result = restore_files(checkpoint, tmp_path)

    assert not (tmp_path / "new.py").exists()
    assert result.restored == ["new.py"]


def test_discard_after_removes_later_checkpoints_but_keeps_earlier_ones():
    store = CheckpointStore()
    first = store.start_checkpoint(history_index=0)
    second = store.start_checkpoint(history_index=2)
    third = store.start_checkpoint(history_index=4)

    store.discard_after(second.id)

    assert store.get(first.id) is not None
    assert store.get(second.id) is not None
    assert store.get(third.id) is None


def test_get_unknown_checkpoint_returns_none():
    store = CheckpointStore()
    assert store.get("nonexistent") is None
