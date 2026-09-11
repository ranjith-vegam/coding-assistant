from samixa_code.agent.tools.bash_tool import RunCommandTool
from samixa_code.agent.tools.base import Tool
from samixa_code.agent.tools.fs_tools import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from samixa_code.agent.tools.remember_tool import RememberTool
from samixa_code.agent.tools.search_tool import SearchCodeTool


def build_default_tools() -> dict[str, Tool]:
    tools: list[Tool] = [
        ReadFileTool(),
        ListDirTool(),
        SearchCodeTool(),
        WriteFileTool(),
        EditFileTool(),
        RunCommandTool(),
        RememberTool(),
    ]
    return {tool.name: tool for tool in tools}
