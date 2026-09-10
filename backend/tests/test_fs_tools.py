from coding_assistant.agent.tools.base import ToolError, resolve_in_workspace
from coding_assistant.agent.tools.fs_tools import EditFileTool, ReadFileTool, WriteFileTool


def test_resolve_in_workspace_allows_relative_path_inside(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")

    resolved = resolve_in_workspace(tmp_path, "src/a.py")

    assert resolved == (tmp_path / "src" / "a.py").resolve()


def test_resolve_in_workspace_rejects_path_traversal(tmp_path):
    try:
        resolve_in_workspace(tmp_path, "../../etc/passwd")
        assert False, "expected ToolError"
    except ToolError as exc:
        assert "outside the workspace root" in str(exc)


def test_resolve_in_workspace_rejects_unrelated_absolute_path(tmp_path):
    try:
        resolve_in_workspace(tmp_path, "/etc/passwd")
        assert False, "expected ToolError"
    except ToolError:
        pass


def test_resolve_in_workspace_rejects_empty_path(tmp_path):
    try:
        resolve_in_workspace(tmp_path, "")
        assert False, "expected ToolError"
    except ToolError as exc:
        assert "empty" in str(exc)


async def test_read_file_returns_line_numbered_content(tmp_path):
    (tmp_path / "a.py").write_text("line one\nline two\n")

    result = await ReadFileTool().run({"path": "a.py"}, tmp_path)

    assert "line one" in result.content
    assert "line two" in result.content
    assert result.is_error is False


async def test_read_file_missing_raises_tool_error(tmp_path):
    try:
        await ReadFileTool().run({"path": "nope.py"}, tmp_path)
        assert False, "expected ToolError"
    except ToolError:
        pass


async def test_write_file_creates_parent_dirs(tmp_path):
    result = await WriteFileTool().run({"path": "nested/dir/out.txt", "content": "hello"}, tmp_path)

    assert (tmp_path / "nested" / "dir" / "out.txt").read_text() == "hello"
    assert "wrote" in result.content


async def test_edit_file_requires_unique_match(tmp_path):
    (tmp_path / "a.py").write_text("foo\nfoo\n")

    try:
        await EditFileTool().run({"path": "a.py", "old_string": "foo", "new_string": "bar"}, tmp_path)
        assert False, "expected ToolError for non-unique match"
    except ToolError as exc:
        assert "not unique" in str(exc)


async def test_edit_file_replace_all_handles_non_unique_match(tmp_path):
    (tmp_path / "a.py").write_text("foo\nfoo\n")

    await EditFileTool().run({"path": "a.py", "old_string": "foo", "new_string": "bar", "replace_all": True}, tmp_path)

    assert (tmp_path / "a.py").read_text() == "bar\nbar\n"


async def test_edit_file_missing_old_string_raises(tmp_path):
    (tmp_path / "a.py").write_text("hello\n")

    try:
        await EditFileTool().run({"path": "a.py", "old_string": "not there", "new_string": "x"}, tmp_path)
        assert False, "expected ToolError"
    except ToolError as exc:
        assert "not found" in str(exc)
