"""
Local tools for chats: models work on a folder on this computer through tools the app runs.

The model asks for tools with XML tags in its reply. The app runs each one
under the current permission mode and sends the results back as the next
message; arena.ai keeps the conversation, so the guide is sent only once.
In Battle and Side by Side both models get the tools, and each one writes to
its own copy of the folder (option-a, option-b) so their work never collides.
"""

import difflib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

OUTPUT_LIMIT = 40_000
_TOOL_RE = re.compile(r"<tool\s+name\s*=\s*[\"']?([\w-]+)[\"']?\s*>(.*?)</tool\s*>", re.S | re.I)
_EMPTY_FENCE = re.compile(r"```[\w-]*[ \t]*\n?\s*```")
_PARAM_RE = re.compile(r"<([a-z_]+)>(.*?)</\1\s*>", re.S | re.I)
_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist", "build"}
_WRITES = {"write_file", "edit_file", "mkdir", "delete"}
LANE_DIRS = {"a": "option-a", "b": "option-b"}

GUIDE = """[Arena Desktop] The user is chatting through Arena Desktop, an app on their own computer. It connects you to a folder on that computer with working tools: you can list, read, search, create, edit and delete files there and run commands. Do not say you lack file access or tell the user to make the files themselves; use the tools. Your own built-in tools (a code sandbox, file or web tools) run on a remote server and cannot reach this computer, so for files here use only the tags below.
Folder: {root}
Permission mode: {mode_label}. {mode_note}{lane_note}

To use a tool, write its tag as plain text in your reply, not inside a code block. The app runs the tags in order and sends you the results in the next message.
<tool name="ls"><path>.</path></tool>
<tool name="read_file"><path>src/main.py</path></tool>
<tool name="search"><pattern>def main</pattern><path>.</path></tool>
<tool name="write_file"><path>index.html</path><content>
FULL FILE CONTENT
</content></tool>
<tool name="edit_file"><path>index.html</path><old_text>exact text to replace</old_text><new_text>replacement</new_text></tool>
<tool name="mkdir"><path>assets/img</path></tool>
<tool name="delete"><path>old_notes.txt</path></tool>
<tool name="run_cmd"><cmd>python -m pytest -q</cmd></tool>

Rules: paths are relative to the folder. Read a file before editing it. write_file takes the whole file. When the task is done, reply with a short summary and no tool tags. If the message does not need files, just answer it.

User message:
"""

LANE_NOTE = ("\nTwo assistants answer this chat side by side. Each one's file changes go to its own copy of the folder "
             "(option-a or option-b), so work as if you were alone. Results come back for both replies; use the ones "
             "for the tool calls you wrote.")

MODE_NOTES = {
    "plan": "Plan mode is on: only ls, read_file and search will run. Do not change anything; "
            "finish with a numbered plan the user can approve.",
    "default": "The user approves each change and command.",
    "acceptEdits": "File edits run without asking; deletes and commands need approval.",
    "auto": "Work inside the project folder runs without asking; risky commands need approval.",
    "bypassPermissions": "All tools run without asking.",
}


def guide(root, mode_label: str, mode_note: str, dual: bool = False) -> str:
    """The tool guide that goes in front of the first message of a conversation."""
    return GUIDE.format(root=root, mode_label=mode_label, mode_note=mode_note, lane_note=LANE_NOTE if dual else "")


def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    calls = []
    for m in _TOOL_RE.finditer(text or ""):
        params = {p.group(1).lower(): p.group(2) for p in _PARAM_RE.finditer(m.group(2))}
        calls.append({"name": m.group(1).lower(), "params": params})
    return calls


def strip_tool_calls(text: str) -> str:
    return _EMPTY_FENCE.sub("", _TOOL_RE.sub("", text or ""))


def _body(text: str) -> str:
    """Content between tags, minus the newline that follows the opening tag."""
    if text.startswith("\r\n"):
        return text[2:]
    if text.startswith("\n"):
        return text[1:]
    return text


def _read(path: Path) -> str:
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def _diff(old: str, new: str, name: str, limit: int = 80) -> str:
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm="", n=2))
    if len(lines) > limit:
        lines = lines[:limit] + [f"... {len(lines) - limit} more diff lines"]
    return "\n".join(lines)


def _result_lines(outcomes) -> List[str]:
    lines = []
    for i, (call, status, output) in enumerate(outcomes, 1):
        target = call["params"].get("path") or call["params"].get("cmd") or ""
        lines.append(f"[{i}] {call['name']} {target}: {status}")
        if output:
            lines.append(str(output)[:OUTPUT_LIMIT])
    return lines


_CONTINUE = "Continue the task. When it is complete, reply with a short summary and no tool tags."


def format_results(outcomes) -> str:
    return "\n".join(["Tool results:"] + _result_lines(outcomes) + [_CONTINUE])


def format_lane_results(per_lane) -> str:
    """Results for a two-model chat: one block per reply, each listing the calls it answers."""
    parts = ["Tool results for both replies. Use only the block for the tool calls you wrote."]
    for lane, outcomes in per_lane.items():
        parts.append(f"Reply {lane.upper()}:\n" + "\n".join(_result_lines(outcomes)) if outcomes
                     else f"Reply {lane.upper()}: no tool calls.")
    return "\n\n".join(parts + [_CONTINUE])


class LocalTools:
    """Runs tools against one project folder. With `out` (two-model chats), changes go to that copy
    of the folder and reads prefer it, so the original files stay as they were."""

    def __init__(self, root, out=None):
        self.root = Path(root).expanduser().resolve()
        self.out = Path(out).expanduser().resolve() if out else None

    def resolve(self, rel: str, write: bool = False) -> Tuple[Path, bool]:
        rel = (rel or ".").strip().strip("\"'") or "."
        p = Path(rel).expanduser()
        target = (p if p.is_absolute() else self.root / p).resolve()
        inside = target == self.root or self.root in target.parents
        own = self._own(target) if inside else None
        if own is not None and (write or own.is_file()):
            return own, True
        return target, inside

    def _own(self, target: Path):
        """This model's copy of a path in a two-model chat; None in one-model chats."""
        if self.out is None or target == self.out or self.out in target.parents:
            return None
        try:
            return self.out / target.relative_to(self.root)
        except ValueError:
            return None

    def _walk(self, top: Path):
        """Files under a folder and this model's copy of it, minus build output and the other model's copy."""
        for d in (top, self._own(top)):
            if d is None or not d.is_dir():
                continue
            for p in d.rglob("*"):
                parts = p.relative_to(d).parts
                if not p.is_file() or _SKIP & set(parts):
                    continue
                if self.out is not None and d == self.root and parts[0] in LANE_DIRS.values():
                    continue
                yield p

    def _rel(self, target: Path) -> str:
        try:
            return target.relative_to(self.root).as_posix() or "."
        except ValueError:
            return str(target)

    def describe(self, call: Dict[str, Any]) -> Dict[str, Any]:
        """What a call would do, for the permission card."""
        name, prm = call["name"], call["params"]
        if name == "run_cmd":
            cmd = (prm.get("cmd") or "").strip()
            return {"tool": name, "path": str(self.out or self.root), "rel": ".", "inside": True, "command": cmd,
                    "summary": f"Run: {cmd}"}
        target, inside = self.resolve(prm.get("path", "."), write=name in _WRITES)
        src, _ = self.resolve(prm.get("path", "."))
        rel = self._rel(target)
        info = {"tool": name, "path": str(target), "rel": rel, "inside": inside, "summary": f"{name} {rel}"}
        try:
            if name == "write_file":
                new = _body(prm.get("content", ""))
                old = _read(src) if src.is_file() else ""
                verb = "Overwrite" if src.exists() else "Create"
                info["summary"] = f"{verb} {rel} ({new.count(chr(10)) + 1} lines)"
                info["diff"] = _diff(old, new, rel)
            elif name == "edit_file":
                old = _read(src) if src.is_file() else ""
                new = old.replace(prm.get("old_text", ""), prm.get("new_text", ""), 1) if prm.get("old_text") else old
                info["summary"] = f"Edit {rel}"
                info["diff"] = _diff(old, new, rel)
            elif name == "delete":
                if target.is_dir():
                    info["summary"] = f"Delete folder {rel} ({sum(1 for _ in target.rglob('*'))} items)"
                else:
                    info["summary"] = f"Delete {rel}"
            elif name == "mkdir":
                info["summary"] = f"Create folder {rel}"
            elif name in ("read_file", "ls", "search"):
                info["summary"] = {"read_file": "Read", "ls": "List", "search": "Search"}[name] + f" {rel}"
        except OSError:
            pass
        return info

    def run(self, call: Dict[str, Any]) -> Tuple[bool, str]:
        fn = getattr(self, "_t_" + call["name"], None)
        if fn is None:
            return False, (f"Unknown tool '{call['name']}'. Available: ls, read_file, search, write_file, "
                           "edit_file, mkdir, delete, run_cmd.")
        try:
            return True, fn(call["params"])
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _t_ls(self, prm) -> str:
        target, _ = self.resolve(prm.get("path", "."))
        dirs = [d for d in (target, self._own(target)) if d is not None and d.is_dir()]
        if not dirs:
            raise NotADirectoryError(f"{self._rel(target)} is not a folder")
        kids = {}
        for d in dirs:
            for child in d.iterdir():
                if not (self.out is not None and d == self.root and child.name in LANE_DIRS.values()):
                    kids[child.name] = child
        rows = []
        for child in sorted(kids.values(), key=lambda c: (not c.is_dir(), c.name.lower()))[:300]:
            rows.append(child.name + "/" if child.is_dir() else f"{child.name}  ({child.stat().st_size} B)")
        return "\n".join(rows) or "(empty folder)"

    def _t_read_file(self, prm) -> str:
        target, _ = self.resolve(prm.get("path", ""))
        if not target.is_file():
            raise FileNotFoundError(f"{self._rel(target)} does not exist")
        if target.stat().st_size > 1_000_000:
            raise ValueError("file is larger than 1 MB")
        text = _read(target)
        return text if len(text) <= 40_000 else text[:40_000] + "\n...[truncated]"

    def _t_search(self, prm) -> str:
        target, _ = self.resolve(prm.get("path", "."))
        pattern = prm.get("pattern", "")
        try:
            rx = re.compile(pattern)
        except re.error:
            rx = re.compile(re.escape(pattern))
        if target.is_file():
            files = [target]
        else:
            files = self._walk(target)
        hits = []
        for f in files:
            try:
                if f.stat().st_size > 1_000_000:
                    continue
                data = f.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:1024]:
                continue
            for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{self._rel(f)}:{n}: {line.strip()[:200]}")
                    if len(hits) >= 100:
                        return "\n".join(hits) + "\n...[more matches]"
        return "\n".join(hits) or "no matches"

    def _t_write_file(self, prm) -> str:
        target, _ = self.resolve(prm.get("path", ""), write=True)
        if not (prm.get("path") or "").strip() or target in (self.root, self.out) or target.is_dir():
            raise ValueError("write_file needs a file path")
        content = _body(prm.get("content", ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        return f"Wrote {content.count(chr(10)) + 1} lines to {self._rel(target)}"

    def _t_edit_file(self, prm) -> str:
        src, _ = self.resolve(prm.get("path", ""))
        target, _ = self.resolve(prm.get("path", ""), write=True)
        if not src.is_file():
            raise FileNotFoundError(f"{self._rel(src)} does not exist")
        text = _read(src)
        old, new = prm.get("old_text", ""), prm.get("new_text", "")
        if not old:
            raise ValueError("old_text is empty")
        candidates = [(old, new), (old.strip("\r\n"), new.strip("\r\n"))]
        if "\r\n" in text:
            candidates += [(o.replace("\r\n", "\n").replace("\n", "\r\n"), n.replace("\r\n", "\n").replace("\n", "\r\n"))
                           for o, n in list(candidates)]
        for o, n in candidates:
            count = text.count(o) if o else 0
            if count == 1:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text.replace(o, n, 1), encoding="utf-8", newline="")
                return f"Edited {self._rel(target)}"
            if count > 1:
                raise ValueError(f"old_text matches {count} places; include more surrounding text")
        raise ValueError("old_text was not found; read the file and copy the exact text")

    def _t_mkdir(self, prm) -> str:
        target, _ = self.resolve(prm.get("path", ""), write=True)
        target.mkdir(parents=True, exist_ok=True)
        return f"Folder ready: {self._rel(target)}"

    def _t_delete(self, prm) -> str:
        target, _ = self.resolve(prm.get("path", ""), write=True)
        if target in (self.root, self.out) or target in self.root.parents:
            raise PermissionError("refusing to delete the project folder itself")
        if target.is_dir():
            shutil.rmtree(target)
            return f"Deleted folder {self._rel(target)}"
        if target.exists():
            target.unlink()
            return f"Deleted {self._rel(target)}"
        raise FileNotFoundError(f"{self._rel(target)} does not exist")

    def _t_run_cmd(self, prm) -> str:
        cmd = (prm.get("cmd") or "").strip()
        if not cmd:
            raise ValueError("cmd is empty")
        cwd = self.out or self.root
        cwd.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        return f"exit code {r.returncode}\n{out[-OUTPUT_LIMIT:]}".strip()
