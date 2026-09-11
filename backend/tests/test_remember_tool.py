from samixa_code.agent.memory import load_memory
from samixa_code.agent.tools.base import ToolError
from samixa_code.agent.tools.remember_tool import RememberTool


async def test_remember_tool_persists_a_note(tmp_path):
    tool = RememberTool()
    result = await tool.run({"note": "always run tests after an edit"}, tmp_path)

    assert "Remembered" in result.content
    memory = load_memory(tmp_path)
    assert memory is not None
    assert "always run tests after an edit" in memory


async def test_remember_tool_rejects_empty_note(tmp_path):
    tool = RememberTool()
    try:
        await tool.run({"note": "   "}, tmp_path)
        assert False, "expected ToolError"
    except ToolError:
        pass


def test_remember_tool_does_not_require_approval():
    assert RememberTool().requires_approval is False
