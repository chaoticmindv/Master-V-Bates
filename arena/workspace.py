"""
Local project folders for code (webdev) answers.

arena.ai sends each code answer as a webdev "init" event carrying the whole
project as files [{path, content}]. The app mirrors it to disk so the code
lives on the user's machine: new files are created, changed files rewritten,
and files an earlier answer wrote but the new one dropped are removed. Only
paths in the folder's manifest can be removed, so the user's own files stay.
"""

import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECTS_DIR = Path(os.environ.get("ARENA_PROJECTS_DIR") or (Path.home() / "ArenaProjects"))
MANIFEST = ".arena-files.json"
_SKIP = {".git", "node_modules", "__pycache__"}


def slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:limit].strip("-") or "project"


def project_dir(chat_id: str, title: str, lane: str, base: Path = None) -> Path:
    return (Path(base or PROJECTS_DIR) / f"{slug(title)}-{(chat_id or 'chat')[:8]}" / f"model-{lane}").resolve()


def _inside(root: Path, rel: str) -> Path:
    """Resolve rel under root, or raise ValueError for absolute paths and traversal."""
    rel = (rel or "").replace("\\", "/").lstrip("/")
    target = (root / rel).resolve()
    if not rel or root not in target.parents:
        raise ValueError(f"unsafe path: {rel!r}")
    return target


def _read(path: Path) -> str:
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def webdev_files(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    holders = [item]
    for key in ("data", "manifest"):
        if isinstance(item.get(key), dict):
            holders.append(item[key])
    for holder in holders:
        if isinstance(holder.get("files"), list):
            return [f for f in holder["files"] if isinstance(f, dict)]
    return []


def _manifest(root: Path) -> set:
    try:
        return set(json.loads((root / MANIFEST).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def plan_project(root: Path, files) -> Dict[str, Any]:
    """Work out what mirroring `files` into root would change, without touching disk."""
    root = Path(root).resolve()
    old = _manifest(root)
    writes: Dict[str, str] = {}
    keep, skipped = set(), 0
    for f in files or []:
        content = f.get("content")
        try:
            target = _inside(root, str(f.get("path") or ""))
        except ValueError:
            skipped += 1
            continue
        if not isinstance(content, str):
            skipped += 1
            continue
        rel = target.relative_to(root).as_posix()
        if target.is_file() and _read(target) == content:
            keep.add(rel)
        else:
            writes[rel] = content
    new = keep | set(writes)
    deletes = []
    for rel in sorted(old - new):
        try:
            if _inside(root, rel).is_file():
                deletes.append(rel)
        except ValueError:
            pass
    return {"root": str(root), "writes": writes, "deletes": deletes, "unchanged": len(keep),
            "skipped": skipped, "files": sorted(new)}


def apply_project(plan: Dict[str, Any], write: bool = True, delete: bool = True) -> Tuple[int, int]:
    root = Path(plan["root"])
    written = deleted = 0
    if write:
        for rel, content in plan["writes"].items():
            target = _inside(root, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")
            written += 1
    if delete:
        for rel in plan["deletes"]:
            target = _inside(root, rel)
            if target.is_file():
                target.unlink()
                deleted += 1
    if write or delete:
        if write:
            tracked = set(plan["files"]) | (set() if delete else set(plan["deletes"]))
        else:
            tracked = _manifest(root) - set(plan["deletes"])
        root.mkdir(parents=True, exist_ok=True)
        (root / MANIFEST).write_text(json.dumps(sorted(tracked), indent=0), encoding="utf-8")
    return written, deleted


def zip_dir(root: Path) -> bytes:
    root = Path(root)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if p.is_file() and p.name != MANIFEST and not (_SKIP & set(rel.parts)):
                z.write(p, rel.as_posix())
    return buf.getvalue()


def list_projects(base: Path = None) -> List[Dict[str, Any]]:
    base = Path(base or PROJECTS_DIR)
    out = []
    if not base.is_dir():
        return out
    for proj in base.iterdir():
        if not proj.is_dir():
            continue
        models = sorted(m.name for m in proj.iterdir() if m.is_dir() and (m / MANIFEST).exists())
        if models:
            out.append({"name": proj.name, "path": str(proj), "models": models, "updated": proj.stat().st_mtime})
    return sorted(out, key=lambda p: -p["updated"])
