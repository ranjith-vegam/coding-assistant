from coding_assistant.agent.project_doc import MAX_PROJECT_DOC_CHARS, load_project_doc, project_doc_path


def test_load_project_doc_returns_none_when_file_does_not_exist(tmp_path):
    assert load_project_doc(tmp_path) is None


def test_load_project_doc_reads_root_level_samixa_md(tmp_path):
    path = project_doc_path(tmp_path)
    path.write_text("# My Project\n\nUses tabs, not spaces.\n")

    doc = load_project_doc(tmp_path)
    assert doc is not None
    assert "Uses tabs, not spaces." in doc


def test_empty_file_on_disk_loads_as_none_not_empty_string(tmp_path):
    path = project_doc_path(tmp_path)
    path.write_text("   \n  ")
    assert load_project_doc(tmp_path) is None


def test_oversized_doc_is_truncated_not_dropped_entirely(tmp_path):
    path = project_doc_path(tmp_path)
    path.write_text("x" * (MAX_PROJECT_DOC_CHARS * 2))

    doc = load_project_doc(tmp_path)
    assert doc is not None
    assert len(doc) <= MAX_PROJECT_DOC_CHARS + 100  # truncation note slack
    assert "truncated" in doc
