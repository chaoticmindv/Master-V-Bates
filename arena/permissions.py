"""
Permission modes for local actions, modelled on Claude Code.

default            ask before any change or command (reads are free)
acceptEdits        create and edit files freely; ask before deletes and commands
auto               work freely inside the project folder; ask for risky commands
                   and for anything outside it
plan               read-only: the model may look but never change anything
bypassPermissions  allow everything except catastrophic commands
"""

import re
import threading
import time
import uuid
from typing import Dict, List, Optional

MODES: Dict[str, str] = {
    "default": "Ask before edits",
    "acceptEdits": "Accept edits",
    "auto": "Auto",
    "plan": "Plan mode",
    "bypassPermissions": "Bypass permissions",
}

KIND = {"read_file": "read", "ls": "read", "search": "read",
        "write_file": "edit", "edit_file": "edit", "mkdir": "edit", "write_project": "edit",
        "delete": "delete", "run_cmd": "shell"}

SAFE_CMD = re.compile(
    r"^\s*(dir|ls|pwd|echo|type|cat|where|which|tree|git\s+(status|log|diff|show|branch)|"
    r"(python|py)(\s+-m)?\s+(pytest|unittest|--version)|node\s+(--version|-v)|"
    r"npm\s+(test|ls|-v|--version)|npm\s+run\s+(test|build|lint))\b", re.I)
SHELL_META = re.compile(r"[;&|<>`$]|\b(del|erase|rm|rmdir|rd|format|curl|wget|iwr|invoke-webrequest|"
                        r"powershell|pwsh|reg|shutdown|move|mv)\b", re.I)
CATASTROPHIC = re.compile(
    r"(\brm\s+-[a-z]*r[a-z]*\s+(/|~|\*|[a-z]:[\\/]?)(\s|$)|\bformat\s+[a-z]:|"
    r"\b(rd|rmdir)\s+/s\s+(/q\s+)?[a-z]:[\\/]?\s*$|\bdel\s+(/[a-z]\s+)*[a-z]:[\\/]\*|\bmkfs\b|"
    r"\bshutdown\b|:\(\)\s*\{|\bdiskpart\b|\bbcdedit\b|\bvssadmin\s+delete\b|\bcipher\s+/w)", re.I)


def normalize(mode: Optional[str]) -> str:
    return mode if mode in MODES else "default"


def decide(mode: str, tool: str, inside: bool = True, command: str = "") -> str:
    """Return 'allow', 'ask' or 'deny' for one action."""
    mode = normalize(mode)
    kind = KIND.get(tool, "shell")
    if kind == "shell" and CATASTROPHIC.search(command or ""):
        return "deny"
    if kind == "read":
        return "allow" if inside or mode == "bypassPermissions" else "ask"
    if mode == "plan":
        return "deny"
    if mode == "bypassPermissions":
        return "allow"
    if not inside:
        return "ask"
    if kind == "edit":
        return "allow" if mode in ("acceptEdits", "auto") else "ask"
    if kind == "delete":
        return "allow" if mode == "auto" else "ask"
    if mode == "auto" and SAFE_CMD.match(command or "") and not SHELL_META.search(command or ""):
        return "allow"
    return "ask"


class PermissionBroker:
    """Holds approval requests until the user answers them in the UI."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Dict[str, dict] = {}
        self._always: set = set()

    def check(self, mode: str, tool: str, inside: bool = True, command: str = "") -> str:
        verdict = decide(mode, tool, inside, command)
        if verdict == "ask" and inside and KIND.get(tool, "shell") in self._always:
            return "allow"
        return verdict

    def ask(self, info: dict) -> str:
        pid = uuid.uuid4().hex[:12]
        with self._lock:
            self._pending[pid] = {"event": threading.Event(), "decision": None,
                                  "info": dict(info, id=pid, created=time.time())}
        return pid

    def resolve(self, pid: str, decision: str) -> bool:
        if decision not in ("allow", "always", "deny"):
            return False
        with self._lock:
            item = self._pending.get(pid)
            if not item or item["decision"]:
                return False
            item["decision"] = decision
            if decision == "always":
                self._always.add(KIND.get(item["info"].get("tool"), "shell"))
            item["event"].set()
        return True

    def wait(self, pid: str, timeout: Optional[float] = None) -> Optional[str]:
        """'allow' or 'deny' once answered; None if still waiting after timeout."""
        item = self._pending.get(pid)
        if not item:
            return "deny"
        if not item["event"].wait(timeout):
            return None
        with self._lock:
            self._pending.pop(pid, None)
        return "deny" if item["decision"] == "deny" else "allow"

    def pending(self) -> List[dict]:
        with self._lock:
            return [p["info"] for p in self._pending.values() if not p["decision"]]

    def cancel_all(self) -> int:
        ids = [info["id"] for info in self.pending()]
        for pid in ids:
            self.resolve(pid, "deny")
        return len(ids)

    def reset_always(self) -> None:
        self._always.clear()
