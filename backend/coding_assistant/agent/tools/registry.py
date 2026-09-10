from coding_assistant.agent.tools.bash_tool import RunCommandTool
from coding_assistant.agent.tools.base import Tool
from coding_assistant.agent.tools.fs_tools import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from coding_assistant.agent.tools.remember_tool import RememberTool
from coding_assistant.agent.tools.search_tool import SearchCodeTool


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
