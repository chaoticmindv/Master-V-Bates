"""
arena.ai wire contracts, kept in one place.

The client relies only on what arena's own web app sends over the wire:
endpoint paths, JSON field names and enum values. Bundle chunk names, hashes
and minified symbols are never used, so a rebuilt or redesigned arena.ai
frontend does not break the client. Paths and reCAPTCHA keys can be patched
without a rebuild in ~/.arena-cli/contracts.json, for example
{"paths": {"create": "/nextjs-api/stream/create-evaluation"}, "v3_key": "6L..."}.
"""

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ORIGIN = "https://arena.ai"

PATHS: Dict[str, str] = {
    "home": "/",
    "create": "/nextjs-api/stream/create-evaluation",
    "post": "/nextjs-api/stream/post-to-evaluation/{eval_id}",
    "me": "/api/me",
    "catalog": "/nextjs-api/model-catalog",
    "webdev": "/api/evaluation/webdev/{message_id}",
    "sign_out": "/nextjs-api/sign-out",
    "storage_upload": "/api/storage/generate-upload-url",
    "storage_signed": "/api/storage/get-signed-url",
}
KEYS: Dict[str, str] = {
    "v3": "6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0",
    "v2": "6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL",
}
RECAPTCHA_ACTION = "chat_submit"
AUTH_COOKIE_PREFIX = "arena-auth-prod-v1"
SITE_KEY_RE = re.compile(r"6L[0-9A-Za-z_-]{38}")

API_MODES = ("battle", "side-by-side", "direct-battle", "direct")
API_MODALITIES = ("auto", "chat", "webdev", "search", "image", "p2l", "video", "audio")
UI_MODES = {"battle": "battle", "side-by-side": "side-by-side", "direct": "direct-battle", "agent": "direct-battle"}
UI_MODALITIES = {"auto": "chat", "text": "chat", "chat": "chat", "code": "webdev", "webdev": "webdev",
                 "search": "search", "image": "image", "video": "video", "audio": "audio"}

# AI SDK data-stream type codes. arena prefixes each line with a lane: a or b.
STREAM_TYPES = {"0": "text", "2": "data", "3": "error", "8": "annotation", "9": "tool_call",
                "a": "tool_result", "b": "tool_start", "c": "tool_delta",
                "d": "finish", "e": "step", "f": "step_start", "g": "reasoning", "h": "source", "k": "file"}


def api_mode(ui_mode: str) -> str:
    mode = UI_MODES.get(ui_mode, ui_mode)
    if mode not in API_MODES:
        raise ValueError(f"Unknown mode {ui_mode!r}")
    return mode


def api_modality(ui_modality: str) -> str:
    modality = UI_MODALITIES.get(ui_modality, ui_modality)
    if modality not in API_MODALITIES:
        raise ValueError(f"Unknown modality {ui_modality!r}")
    return modality


def load_overrides(path: Optional[Path] = None) -> List[str]:
    """Apply contracts.json overrides; returns what changed."""
    if path is None:
        from arena.config import CONFIG_DIR
        path = CONFIG_DIR / "contracts.json"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    changed = []
    for name, value in (data.get("paths") or {}).items():
        if isinstance(value, str) and value.startswith("/"):
            PATHS[name] = value
            changed.append(f"paths.{name}")
    for name in ("v2", "v3"):
        value = data.get(f"{name}_key")
        if isinstance(value, str) and SITE_KEY_RE.fullmatch(value):
            KEYS[name] = value
            changed.append(f"{name}_key")
    return changed


def discover_site_keys(html: str) -> Dict[str, str]:
    """Find the v3 key in the live page's reCAPTCHA script URL (render=KEY)."""
    m = re.search(r"recaptcha[^\"'<>\s]*?[?&]render=(6L[0-9A-Za-z_-]{38})", html or "")
    return {"v3": m.group(1)} if m else {}


def build_chat(*, eval_id: str, new: bool, mode: str, modality: str, content: str, ids: Callable[[], str],
               model_a: Optional[str] = None, model_b: Optional[str] = None, attachments=None,
               v2_token: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Return (path, body) for one user message. mode and modality are arena values.

    arena enforces: battle takes no model ids; direct starts as direct-battle with one
    model and no B message; follow-ups carry no mode; message ids are UUIDv7s created
    after eval_id, so ids() must be monotonic.
    """
    if mode not in API_MODES:
        raise ValueError(f"Unknown mode {mode!r}")
    if mode != "battle" and not model_a:
        raise ValueError("Pick a model first: this mode talks to the model you choose.")
    if mode == "side-by-side" and not model_b:
        raise ValueError("Side by Side compares two models: pick model B too.")
    body: Dict[str, Any] = {
        "id": eval_id,
        "userMessageId": ids(),
        "modelAMessageId": ids(),
        "userMessage": {"content": content, "experimental_attachments": list(attachments or []), "metadata": {}},
        "modality": modality,
    }
    if mode in ("battle", "side-by-side"):
        body["modelBMessageId"] = ids()
    if mode != "battle":
        body["modelAId"] = model_a
    if mode == "side-by-side":
        body["modelBId"] = model_b
    if v2_token:
        body["recaptchaV2Token"] = v2_token
    else:
        body["recaptchaV3Token"] = None
    if new:
        body["mode"] = mode
        return PATHS["create"], body
    return PATHS["post"].format(eval_id=eval_id), body


def parse_line(line: str) -> Optional[Tuple[str, str, Any]]:
    """Parse one stream line into (lane, kind, value); None for lines the app ignores."""
    line = (line or "").strip()
    if len(line) >= 3 and line[0] in "ab" and line[2] == ":" and line[1] in STREAM_TYPES:
        lane, code, raw = line[0], line[1], line[3:]
    elif len(line) >= 2 and line[1] == ":" and line[0] in STREAM_TYPES:
        lane, code, raw = "a", line[0], line[2:]
    else:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    return lane, STREAM_TYPES[code], value


class LineSplitter:
    """Turns arbitrary text chunks into complete lines."""

    def __init__(self):
        self._buf = ""

    def feed(self, chunk: str) -> List[str]:
        self._buf += chunk
        *lines, self._buf = self._buf.split("\n")
        return lines

    def flush(self) -> List[str]:
        rest, self._buf = self._buf, ""
        return [rest] if rest.strip() else []


def classify_error(status: int, text: str = "") -> Dict[str, Any]:
    """Turn an arena.ai failure into a code, a plain-language message and retry advice."""
    raw = text or ""
    low = raw.lower()
    detail = raw
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            detail = str(obj.get("error") or obj.get("message") or raw)
    except ValueError:
        pass
    detail = " ".join(detail.split())[:300]

    def out(code, message, retry=False, wait=0):
        return {"code": code, "status": status, "message": message, "detail": detail, "retry": retry, "wait": wait}

    if status == 0:
        return out("network", "Can't reach arena.ai. Check your internet connection, then retry.", True, 5)
    if "just a moment" in low or "cf-chl" in low or ("cloudflare" in low and status in (403, 503)):
        return out("cloudflare", "Cloudflare wants to check this browser. Finish the check in the arena.ai window that opened.", True)
    if "too many requests" in low or "rate limit" in low or "rate-limit" in low:
        return out("rate_limit", "arena.ai is rate-limiting this account. Wait about a minute, then send again.", True, 60)
    if "captcha" in low:
        return out("challenge", "arena.ai asked for a quick human check. Complete it in the arena.ai window; "
                                "your message resends by itself.", True)
    if status == 401:
        return out("auth", "Your arena.ai session ended. Sign in again from Settings, Account.")
    if status == 429:
        return out("rate_limit", "arena.ai is rate-limiting this account. Wait about a minute, then send again.", True, 60)
    if "cannot pass model for battle" in low:
        return out("bad_request", "Battle mode picks the models for you. Switch to Direct to choose one.")
    if "must start with one model" in low:
        return out("bad_request", "Direct chat takes exactly one model. Pick one model and resend.")
    if "uuid" in low:
        return out("client_bug", "arena.ai rejected the message ids. Start a new chat and resend.")
    if status == 404:
        return out("eval_gone", "arena.ai no longer has this conversation.")
    if status == 413:
        return out("too_large", "That message or attachment is too large for arena.ai.")
    if status >= 500:
        return out("server", f"arena.ai had a server error ({status}). It is on their side; retry in a minute.", True, 30)
    if status == 403:
        return out("forbidden", "arena.ai refused the request (403). Sign in again; if it repeats, wait a few minutes.", True)
    return out("http", f"arena.ai returned HTTP {status}: {detail or 'no details'}")


_PREVIEW_KEYS = ("previewUrl", "sandboxPreviewUrl", "sandboxUrl", "deploymentUrl", "deployUrl", "webUrl")


def find_preview_url(value: Any, depth: int = 0) -> Optional[str]:
    if depth > 8:
        return None
    if isinstance(value, dict):
        for key in _PREVIEW_KEYS:
            v = value.get(key)
            if isinstance(v, str) and v.startswith("http"):
                return v
        items = list(value.values())
    elif isinstance(value, list):
        items = value
    elif isinstance(value, str) and value.startswith("http") and ".arena.site" in value:
        return value
    else:
        return None
    for v in items:
        found = find_preview_url(v, depth + 1)
        if found:
            return found
    return None


_PATH_KEYS = ("path", "file_path", "filePath", "filename", "file", "target_file", "targetFile", "relative_path")
_CONTENT_KEYS = ("content", "file_text", "fileText", "contents", "code", "new_content", "text")
_OLD_KEYS = ("old_str", "old_string", "oldString", "old_text", "oldText", "context", "search", "find")
_NEW_KEYS = ("new_str", "new_string", "newString", "new_text", "newText", "replace", "replacement")
_URL_KEYS = ("url", "src", "source_url", "image_url", "imageUrl", "media_url")
_LOOK_WORDS = ("read", "view", "cat", "list", "ls", "open", "get", "search", "find", "grep", "inspect", "glob")


def sandbox_op(call: Dict[str, Any]) -> Dict[str, Any]:
    """What one of arena.ai's own sandbox tool calls does: write, edit, delete or download a file,
    read (look only), run a command, change a file some other way (touch) or something else."""
    name = str(call.get("toolName") or call.get("name") or "tool")
    args = call.get("args", call.get("input"))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    args = args if isinstance(args, dict) else {}

    def pick(keys):
        return next((args[k] for k in keys if isinstance(args.get(k), str)), None)

    low, sub = name.lower(), str(args.get("command") or "").lower()
    op = {"id": call.get("toolCallId") or call.get("id"), "tool": name, "path": pick(_PATH_KEYS)}
    content, old, new, url = pick(_CONTENT_KEYS), pick(_OLD_KEYS), pick(_NEW_KEYS), pick(_URL_KEYS)
    if op["path"] and old is not None and new is not None:
        op.update(kind="edit", old=old, new=new)
    elif op["path"] and content is not None and sub != "view":
        op.update(kind="write", content=content)
    elif op["path"] and url and url.startswith("http"):
        op.update(kind="download", url=url)
    elif op["path"] and ("delete" in low or "remove" in low or sub in ("delete", "rm")):
        op["kind"] = "delete"
    elif op["path"]:
        op["kind"] = "read" if any(w in low or w == sub for w in _LOOK_WORDS) else "touch"
    elif any(w in low for w in ("bash", "shell", "terminal", "exec", "command", "run")):
        op.update(kind="run", detail=str(args.get("command") or args.get("cmd") or "")[:200])
    else:
        op.update(kind="other", detail=", ".join(str(k) for k in list(args)[:4]))
    return op


def webdev_items(value: Any) -> List[Dict[str, Any]]:
    items = value if isinstance(value, list) else [value]
    return [i for i in items if isinstance(i, dict) and i.get("type") == "webdev"]


_MEDIA_EXT = {"png": "image", "jpg": "image", "jpeg": "image", "webp": "image", "gif": "image", "avif": "image",
              "mp4": "video", "webm": "video", "mov": "video",
              "mp3": "audio", "wav": "audio", "ogg": "audio", "m4a": "audio"}


def find_media(value: Any) -> List[Dict[str, str]]:
    """Image, video and audio URLs anywhere inside a data or file part."""
    found: List[Dict[str, str]] = []
    seen = set()

    def add(url, kind):
        if url not in seen:
            seen.add(url)
            found.append({"url": url, "kind": kind})

    def walk(v, depth):
        if depth > 8:
            return
        if isinstance(v, str):
            if v.startswith(("https://", "http://")):
                ext = v.split("?", 1)[0].split("#", 1)[0].rsplit(".", 1)[-1].lower()
                if ext in _MEDIA_EXT:
                    add(v, _MEDIA_EXT[ext])
        elif isinstance(v, dict):
            mime = str(v.get("mimeType") or v.get("contentType") or v.get("mediaType") or "")
            kind = mime.split("/", 1)[0]
            if kind in ("image", "video", "audio"):
                url = next((v[k] for k in ("url", "src", "imageUrl", "videoUrl", "audioUrl")
                            if isinstance(v.get(k), str)), None)
                if url and url.startswith(("https://", "http://", "data:")):
                    add(url, kind)
                elif isinstance(v.get("data"), str) and len(v["data"]) > 16:
                    add(f"data:{mime};base64,{v['data']}", kind)
            for x in v.values():
                walk(x, depth + 1)
        elif isinstance(v, list):
            for x in v:
                walk(x, depth + 1)

    walk(value, 0)
    return found
