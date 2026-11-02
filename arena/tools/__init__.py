"""
Tool registry and XML tool parser for Arena CLI.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from arena.tools.base import BaseTool
from arena.tools.file_tools import ReadFileTool, WriteFileTool, EditFileTool, SearchTool, LsTool
from arena.tools.shell_tools import RunCmdTool
from arena.tools.mcp import McpStdioClient, McpToolWrapper
from arena.tools.browser_mcp import (
    BrowserDetectTool, BrowserOpenUrlTool, BrowserListTabsTool, BrowserExecJsTool
)

SYSTEM_PROMPT_TEMPLATE = """You are Arena CLI, an expert AI coding assistant modeled after Claude Code running directly in the user's terminal.
Current working directory: {cwd}

You have access to the following local developer tools.
To execute a tool, output its exact XML representation:

READ A FILE:
<tool name="read_file"><path>path/to/file</path></tool>

WRITE OR CREATE A FILE:
<tool name="write_file"><path>path/to/file</path><content>
file contents here
</content></tool>

EDIT FILE (TARGETED REPLACEMENT):
<tool name="edit_file"><path>path/to/file</path><old_text>exact existing snippet</old_text><new_text>replacement snippet</new_text></tool>

SEARCH FILES (REGEX GREP):
<tool name="search"><pattern>regex</pattern><path>.</path></tool>

LIST DIRECTORY:
<tool name="ls"><path>.</path></tool>

RUN SHELL COMMAND:
<tool name="run_cmd"><cmd>command</cmd></tool>
{mcp_docs}

Guidelines:
1. Always inspect files with `read_file` before editing them.
2. Prefer `edit_file` for targeted changes, and `write_file` for new files or full rewrites.
3. Be direct, accurate, and concise. Explain what was changed.
4. You may execute multiple tools in sequence. After seeing results, continue or provide the final solution."""


class ToolRegistry:
    """Manages active tools and executes tool calls."""

    def __init__(self, cwd: str):
        self.cwd = cwd
        self.tools: Dict[str, BaseTool] = {}
        self.mcp_clients: List[McpStdioClient] = []
        self._register_default_tools()
        self._load_local_mcp_servers()

    def _register_default_tools(self) -> None:
        """Register built-in coding and multi-browser tools."""
        defaults = [
            ReadFileTool(self.cwd),
            WriteFileTool(self.cwd),
            EditFileTool(self.cwd),
            SearchTool(self.cwd),
            LsTool(self.cwd),
            RunCmdTool(self.cwd),
            BrowserDetectTool(self.cwd),
            BrowserOpenUrlTool(self.cwd),
            BrowserListTabsTool(self.cwd),
            BrowserExecJsTool(self.cwd),
        ]
        for t in defaults:
            self.tools[t.name] = t

    def _load_local_mcp_servers(self) -> None:
        """Check for brave-search-mcp-server or configured MCP servers."""
        candidate_dirs = [
            Path(self.cwd) / "servers" / "brave-search-mcp-server-2.1.4",
            Path(self.cwd) / "servers" / "brave-search-mcp-server",
            Path(self.cwd) / "brave-search-mcp-server-2.1.4",
            Path(self.cwd) / "brave-search-mcp-server",
        ]
        brave_dir = None
        for d in candidate_dirs:
            if (d / "dist" / "index.js").exists():
                brave_dir = d
                break

        if brave_dir:
            index_js = brave_dir / "dist" / "index.js"
            brave_api_key = os.environ.get("BRAVE_API_KEY", "")
            cmd = ["node", str(index_js)]
            if brave_api_key:
                cmd.extend(["--brave-api-key", brave_api_key])
            client = McpStdioClient(
                command=cmd,
                cwd=str(brave_dir)
            )
            if client.start():
                self.mcp_clients.append(client)
                for t_info in client.tools:
                    wrapped = McpToolWrapper(self.cwd, client, t_info)
                    self.tools[wrapped.name] = wrapped

    def get_system_prompt(self) -> str:
        """Generate system prompt including MCP tool documentation if loaded."""
        mcp_lines = []
        for name, tool in self.tools.items():
            if isinstance(tool, McpToolWrapper):
                mcp_lines.append(f"\nMCP TOOL: {name}\nDescription: {tool.description}")
        mcp_docs = "\n".join(mcp_lines)
        return SYSTEM_PROMPT_TEMPLATE.format(cwd=self.cwd, mcp_docs=mcp_docs)

    def execute(self, name: str, params: Dict[str, Any]) -> str:
        """Execute a tool by name."""
        tool = self.tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        try:
            return tool.execute(params)
        except Exception as e:
            return f"Error executing tool '{name}': {type(e).__name__}: {e}"

    def shutdown(self) -> None:
        """Stop all running MCP servers."""
        for client in self.mcp_clients:
            client.stop()


def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    """
    Parse XML tool calls from model output:
    <tool name="tool_name"><param1>val1</param1></tool>
    """
    calls = []
    # Match outer <tool name="...">...</tool>
    pattern = re.compile(r'<tool\s+name=["\']([\w\-]+)["\']>(.*?)</tool>', re.DOTALL)
    for m in pattern.finditer(text):
        name = m.group(1)
        body = m.group(2)
        params: Dict[str, Any] = {}
        # Match inner <param>value</param>
        param_pattern = re.compile(r'<([\w\-]+)>(.*?)</\1>', re.DOTALL)
        for pm in param_pattern.finditer(body):
            params[pm.group(1)] = pm.group(2)
        calls.append({"name": name, "params": params})
    return calls
