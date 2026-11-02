"""
Shell execution tool for running system commands.
"""

import os
import subprocess
from typing import Dict, Any

from arena.tools.base import BaseTool


class RunCmdTool(BaseTool):
    name = "run_cmd"
    description = "Execute a command in the local shell."

    def execute(self, params: Dict[str, Any]) -> str:
        cmd = params.get("cmd", "").strip()
        if not cmd:
            return "Error: No command specified."

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=45,
                cwd=self.cwd,
                env=env,
            )
            stdout = (res.stdout or "").strip()
            stderr = (res.stderr or "").strip()

            out_parts = []
            if stdout:
                out_parts.append(stdout[-4000:])
            if stderr:
                out_parts.append(f"[STDERR]\n{stderr[-1500:]}")
            if res.returncode != 0:
                out_parts.append(f"[Process exited with code {res.returncode}]")

            return "\n".join(out_parts) if out_parts else "(command finished with no output)"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 45 seconds."
        except Exception as e:
            return f"Error executing command: {e}"

