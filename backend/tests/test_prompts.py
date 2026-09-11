from samixa_code.agent.prompts import build_system_prompt


def test_no_project_doc_tells_model_none_exists_and_offers_to_create_one():
    prompt = build_system_prompt("/workspace")
    assert "There is no SAMIXA.md" in prompt
    assert "write_file" in prompt


def test_project_doc_present_is_included_verbatim_and_no_missing_note():
    prompt = build_system_prompt("/workspace", project_doc="# My Project\n\nUses tabs.")
    assert "Uses tabs." in prompt
    assert "There is no SAMIXA.md" not in prompt


def test_memory_and_project_doc_are_independent_sections():
    prompt = build_system_prompt("/workspace", memory="- always use tabs", project_doc="# Notes\n\narchitecture stuff")
    assert "always use tabs" in prompt
    assert "architecture stuff" in prompt
