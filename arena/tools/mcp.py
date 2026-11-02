"""
MCP (Model Context Protocol) Client integration.
Connects to external MCP servers (STDIO transport) such as Brave Search MCP.
"""

import json
import os
import subprocess
import threading
from typing import Dict, Any, List, Optional
from pathlib import Path

from arena.tools.base import BaseTool


class McpStdioClient:
    """Lightweight STDIO client for MCP servers implementing JSON-RPC 2.0."""

    def __init__(self, command: List[str], env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None):
        self.command = command
        self.env = {**os.environ, **(env or {})}
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()
        self._responses: Dict[int, Any] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self.tools: List[Dict[str, Any]] = []

    def start(self) -> bool:
        """Spawn the MCP server process and initialize."""
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self.cwd,
                env=self.env,
            )
            self._running = True
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            # MCP Handshake: initialize
            init_res = self.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "arena-cli", "version": "1.0.0"}
            }, timeout=10)

            if not init_res:
                return False

            # Send initialized notification
            self.send_notification("notifications/initialized", {})

            # Discover available tools
            tools_res = self.send_request("tools/list", {}, timeout=10)
            if tools_res and "tools" in tools_res:
                self.tools = tools_res["tools"]
            return True
        except Exception:
            return False

    def _read_loop(self) -> None:
        """Background thread reading JSON-RPC responses from stdout."""
        while self._running and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if "id" in msg:
                        with self._lock:
                            self._responses[msg["id"]] = msg
                except Exception:
                    pass
            except Exception:
                break

    def send_request(self, method: str, params: Dict[str, Any], timeout: float = 15.0) -> Optional[Dict[str, Any]]:
        """Send a synchronous JSON-RPC request and await response."""
        with self._lock:
            self._req_id += 1
            req_id = self._req_id

        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        try:
            payload = json.dumps(msg) + "\n"
            if self.process and self.process.stdin:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
        except Exception:
            return None

        # Poll for response
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                if req_id in self._responses:
                    resp = self._responses.pop(req_id)
                    if "result" in resp:
                        return resp["result"]
                    if "error" in resp:
                        return {"error": resp["error"]}
                    return resp
            time.sleep(0.05)

        return None

    def send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification."""
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            payload = json.dumps(msg) + "\n"
            if self.process and self.process.stdin:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
        except Exception:
            pass

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call an MCP tool and format response as text."""
        res = self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        }, timeout=30)

        if not res:
            return f"Error: MCP tool '{tool_name}' timed out."
        if "error" in res:
            return f"MCP Error: {res['error']}"

        content_list = res.get("content", [])
        text_outputs = []
        for item in content_list:
            if item.get("type") == "text":
                text_outputs.append(item.get("text", ""))
            else:
                text_outputs.append(json.dumps(item))

        return "\n".join(text_outputs) if text_outputs else "(MCP tool returned empty content)"

    def stop(self) -> None:
        """Shut down the MCP server process."""
        self._running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass


class McpToolWrapper(BaseTool):
    """Wraps an MCP tool into an Arena BaseTool."""

    def __init__(self, cwd: str, client: McpStdioClient, tool_info: Dict[str, Any]):
        super().__init__(cwd)
        self.client = client
        self.name = tool_info.get("name", "mcp_tool")
        self.description = tool_info.get("description", "External MCP tool")
        self.input_schema = tool_info.get("inputSchema", {})

    def execute(self, params: Dict[str, Any]) -> str:
        return self.client.call_tool(self.name, params)

