"""
Multi-browser MCP integration supporting 6 major browsers:
Brave, Google Chrome, Microsoft Edge, Mozilla Firefox, Opera, and Vivaldi.
Provides tools to inspect tabs, evaluate scripts, open URLs, and grab page data.
"""

import http.client
import json
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional

from arena.tools.base import BaseTool
from arena.auth import detect_installed_browsers


class BrowserDetectTool(BaseTool):
    name = "browser_detect"
    description = "Detect status of all 6 major browsers (Brave, Chrome, Edge, Firefox, Opera, Vivaldi)."

    def execute(self, params: Dict[str, Any]) -> str:
        installed = detect_installed_browsers()
        lines = ["Installed & Available Browsers:"]
        for name, path in installed.items():
            lines.append(f"  • {name}: {path}")

        # Check for active CDP debugging port (9222)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", 9222, timeout=2)
            conn.request("GET", "/json/version")
            resp = conn.getresponse()
            if resp.status == 200:
                ver_info = json.loads(resp.read().decode("utf-8"))
                lines.append(f"\nActive CDP Browser on port 9222:\n  • {ver_info.get('Browser', 'Unknown')}\n  • User-Agent: {ver_info.get('User-Agent', '')[:80]}...")
            conn.close()
        except Exception:
            lines.append("\nNo browser currently attached to remote debugging port 9222.")

        return "\n".join(lines)


class BrowserOpenUrlTool(BaseTool):
    name = "browser_open_url"
    description = "Open a URL in a specific browser (Brave, Chrome, Edge, Firefox, Opera, Vivaldi)."

    def execute(self, params: Dict[str, Any]) -> str:
        url = params.get("url", "").strip()
        browser_name = params.get("browser", "Brave").strip()

        if not url:
            return "Error: No URL provided."
        if not (url.startswith("http://") or url.startswith("https://")):
            url = f"https://{url}"

        installed = detect_installed_browsers()
        target_path = None
        for b_name, b_path in installed.items():
            if browser_name.lower() in b_name.lower():
                target_path = b_path
                browser_name = b_name
                break

        if not target_path:
            # Fallback to system default
            try:
                import webbrowser
                webbrowser.open(url)
                return f"Opened '{url}' in system default browser."
            except Exception as e:
                return f"Error opening URL: {e}"

        try:
            subprocess.Popen([target_path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Successfully launched {browser_name} with '{url}'."
        except Exception as e:
            return f"Error launching {browser_name}: {e}"


class BrowserListTabsTool(BaseTool):
    name = "browser_list_tabs"
    description = "List all open pages/tabs in the active CDP browser (port 9222)."

    def execute(self, params: Dict[str, Any]) -> str:
        port = int(params.get("port", 9222))
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/json")
            resp = conn.getresponse()
            if resp.status != 200:
                return f"Error: Browser CDP port {port} returned status {resp.status}."
            pages = json.loads(resp.read().decode("utf-8"))
            conn.close()

            lines = [f"Open browser tabs on port {port}:"]
            for i, p in enumerate(pages, 1):
                title = p.get("title", "(no title)")[:60]
                url = p.get("url", "")
                p_id = p.get("id", "")
                lines.append(f"  [{i}] {title}\n      URL: {url}\n      ID: {p_id}")
            return "\n".join(lines) if len(lines) > 1 else "No active tabs found."
        except ConnectionRefusedError:
            return f"Connection refused on port {port}. Please ensure a browser is running with --remote-debugging-port={port}."
        except Exception as e:
            return f"Error querying browser tabs: {e}"


class BrowserExecJsTool(BaseTool):
    name = "browser_exec_js"
    description = "Evaluate JavaScript in an active browser tab via CDP WebSocket."

    def execute(self, params: Dict[str, Any]) -> str:
        script = params.get("script", "").strip()
        port = int(params.get("port", 9222))
        target_url = params.get("url_match", "arena.ai")

        if not script:
            return "Error: No script provided."

        try:
            import websocket
        except ImportError:
            return "Error: websocket-client is not installed."

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/json")
            resp = conn.getresponse()
            pages = json.loads(resp.read().decode("utf-8"))
            conn.close()

            # Find matching page
            page = None
            for p in pages:
                if target_url in p.get("url", ""):
                    page = p
                    break
            if not page and pages:
                page = pages[0]

            if not page:
                return f"Error: No browser page matching '{target_url}' found."

            ws_url = page.get("webSocketDebuggerUrl")
            if not ws_url:
                return "Error: No webSocketDebuggerUrl available for target page."

            ws = websocket.create_connection(ws_url, timeout=5)
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": script,
                    "returnByValue": True,
                    "awaitPromise": True,
                }
            }))
            raw_res = json.loads(ws.recv())
            ws.close()

            res_val = raw_res.get("result", {}).get("result", {}).get("value")
            return json.dumps(res_val, indent=2) if isinstance(res_val, (dict, list)) else str(res_val)
        except Exception as e:
            return f"Error evaluating script: {e}"

