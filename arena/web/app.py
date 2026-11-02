"""
Flask web backend for Arena.ai desktop client.
Serves the web UI and proxies chat requests to arena.ai.
"""

import difflib
import hashlib
import json
import logging
import mimetypes
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, stream_with_context

# Add parent to path for arena imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from arena.config import (
    BASE_URL,
    CHATS_DIR,
    COOKIE_FILE,
    load_config,
    save_config,
)
from arena.api import ArenaClient, extract_bearer_token, fetch_cookies_via_cdp
from arena.models import sync_models, get_models_for_modality, ORG_COLOR_MAP
from arena.auth import detect_installed_browsers, parse_cookie_input
from arena.web.openai_compat import (
    API_LOGGER,
    resolve_model,
    format_model_list,
    format_messages_to_prompt,
    estimate_tokens,
    format_openai_sse_chunk,
    format_openai_completion,
    format_openai_error,
)

import base64
import ctypes
import ctypes.wintypes
import re
import shutil
import sqlite3
import tempfile
import uuid
import codecs
import functools
import http.server
import io
import mimetypes
import urllib.parse

import requests
from datetime import datetime, timezone


def _dpapi_decrypt(data: bytes):
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                     ("pbData", ctypes.POINTER(ctypes.c_char))]
    p = ctypes.create_string_buffer(data, len(data))
    bi = DATA_BLOB(len(data), p)
    bo = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(bi), None, None, None, None, 0, ctypes.byref(bo)
    ):
        result = ctypes.string_at(bo.pbData, bo.cbData)
        ctypes.windll.kernel32.LocalFree(bo.pbData)
        return result
    return None


def _decrypt_cookie_val(enc: bytes, key: bytes):
    if len(enc) < 16:
        return None
    if enc[:3] in (b'v10', b'v11', b'v20'):
        nonce = enc[3:15]
        ct = enc[15:]
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            return AESGCM(key).decrypt(nonce, ct, None).decode('utf-8', errors='ignore')
        except Exception:
            return None
    d = _dpapi_decrypt(enc)
    return d.decode('utf-8', errors='ignore') if d else None


def _extract_browser_cookies():
    dirs = {
        'chrome': os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data'),
        'edge': os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Edge\User Data'),
        'brave': os.path.expandvars(r'%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data'),
    }
    for name, ud in dirs.items():
        if not os.path.isdir(ud):
            continue
        r = _try_chromium_cookies(ud)
        if r:
            return r
    return None


def _try_chromium_cookies(ud):
    ls_file = os.path.join(ud, 'Local State')
    if not os.path.isfile(ls_file):
        return None
    try:
        with open(ls_file, 'r', encoding='utf-8') as f:
            ls = json.load(f)
        ek = base64.b64decode(ls['os_crypt']['encrypted_key'])[5:]
        key = _dpapi_decrypt(ek)
        if not key:
            return None
    except Exception:
        return None

    for profile in ['Default'] + [f'Profile {i}' for i in range(1, 6)]:
        cdb = os.path.join(ud, profile, 'Cookies')
        if not os.path.isfile(cdb):
            continue
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False).name
        try:
            shutil.copy2(cdb, tmp)
            conn = sqlite3.connect(tmp)
            rows = conn.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%arena.ai%'"
            ).fetchall()
            conn.close()
        except Exception:
            continue
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

        cookies = {}
        for cname, cval in rows:
            if cval and len(cval) > 3:
                v = _decrypt_cookie_val(cval, key)
                if v:
                    cookies[cname] = v
        if 'arena-auth-prod-v1.0' in cookies:
            return '; '.join(f'{k}={v}' for k, v in cookies.items())
    return None

def _find_preview_url(val):
    if isinstance(val, dict):
        for k in ("sandboxUrl", "previewUrl", "deploymentUrl", "deployUrl", "webUrl"):
            if k in val and isinstance(val[k], str) and val[k].startswith("http"):
                return val[k]
        for v in val.values():
            r = _find_preview_url(v)
            if r:
                return r
    elif isinstance(val, list):
        for item in val:
            r = _find_preview_url(item)
            if r:
                return r
    return None


from arena import accounts, agent, contracts, permissions, workspace
from arena.api import generate_uuidv7
from arena.auth import get_clipboard_text
from arena.engine import ENGINE

_overrides = contracts.load_overrides()
MODE_API_MAP = dict(contracts.UI_MODES)
MODALITY_API_MAP = dict(contracts.UI_MODALITIES)
VALID_API_MODES = contracts.API_MODES
VALID_API_MODALITIES = ("chat", "webdev", "search", "image", "video")
BROKER = permissions.PermissionBroker()
_stop = threading.Event()
_last_webdev: dict = {}

if getattr(sys, 'frozen', False):
    _base = Path(sys._MEIPASS)
else:
    _base = Path(__file__).parent
STATIC_DIR = _base / "arena" / "web" / "static" if getattr(sys, 'frozen', False) else Path(__file__).parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")

# Global client instance
_client: Optional[ArenaClient] = None
_conversation_history: list = []
_ui_mode = 'battle'
_ui_modality = 'auto'
_current_chat_id: Optional[str] = None

_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def _validate_chat_id(chat_id: str) -> bool:
    return bool(_UUID_RE.match(chat_id))


def _save_chat(chat_id: str, title: str, messages: list,
               mode: str = 'battle', modality: str = 'auto',
               model_a: str = None, model_b: str = None, eval_id: str = None):
    if not _validate_chat_id(chat_id):
        return
    chat_dir = CHATS_DIR / chat_id
    chat_dir.mkdir(parents=True, exist_ok=True)
    chat_file = chat_dir / "chat.json"
    now = datetime.now(timezone.utc).isoformat()
    existing = {}
    if chat_file.exists():
        try:
            existing = json.loads(chat_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    data = {
        "id": chat_id,
        "title": title,
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "account_id": existing.get("account_id") or _active_account_id(),
        "mode": mode,
        "modality": modality,
        "model_a": model_a,
        "model_b": model_b,
        "eval_id": eval_id,
        "pinned": bool(existing.get("pinned")),
        "messages": messages,
    }
    chat_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _load_chat(chat_id: str) -> Optional[dict]:
    if not _validate_chat_id(chat_id):
        return None
    chat_file = CHATS_DIR / chat_id / "chat.json"
    if not chat_file.exists():
        return None
    try:
        return json.loads(chat_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def _chat_owned_by_active(data: dict) -> bool:
    active = _active_account_id()
    if not active:
        return True
    owner = data.get("account_id")
    if not owner:
        try:
            owner = accounts.first_id()
        except Exception:
            owner = None
    return owner == active


def _list_chats() -> list:
    if not CHATS_DIR.exists():
        return []
    active = _active_account_id()
    try:
        legacy = accounts.first_id() if active else None
    except Exception:
        legacy = None
    chats = []
    for d in CHATS_DIR.iterdir():
        if not d.is_dir():
            continue
        f = d / "chat.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            owner = data.get("account_id")
            if not owner and legacy:  # chats from before accounts existed belong to the original account
                owner = data["account_id"] = legacy
                try:
                    f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                except OSError:
                    pass
            if active and owner != active:
                continue
            chats.append({
                "id": data.get("id", d.name),
                "title": data.get("title", "Untitled"),
                "updated_at": data.get("updated_at", ""),
                "mode": data.get("mode"),
                "modality": data.get("modality"),
                "pinned": bool(data.get("pinned")),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            pass
    chats.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
    chats.sort(key=lambda c: not c.get("pinned"))  # pinned chats first, newest first inside each group
    return chats


def _delete_chat(chat_id: str) -> bool:
    if not _validate_chat_id(chat_id):
        return False
    data = _load_chat(chat_id)
    if data and not _chat_owned_by_active(data):
        return False
    chat_dir = CHATS_DIR / chat_id
    if chat_dir.exists() and chat_dir.is_dir():
        shutil.rmtree(chat_dir)
        return True
    return False


def get_client() -> ArenaClient:
    global _client
    if _client is None:
        cookie_str = None
        try:
            cookie_str = accounts.active_cookie()
        except Exception:
            cookie_str = None
        if not cookie_str and COOKIE_FILE.exists():
            cookie_str = COOKIE_FILE.read_text(encoding="utf-8").strip()
        _client = ArenaClient(cookie_str=cookie_str)
    return _client


def _active_account_id():
    try:
        return accounts.active_id()
    except Exception:
        return None


def _reset_conversation(client=None) -> None:
    """A new account must not continue the previous account's arena conversation."""
    global _current_chat_id, _conversation_history
    _current_chat_id = None
    _conversation_history = []
    client = client or get_client()
    client.eval_id = None
    try:
        client.sources.clear()
    except Exception:
        pass


# ---------- Static serving ----------

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/dashboard")
def api_dashboard():
    return send_from_directory(str(STATIC_DIR), "dashboard.html")


# ---------- API routes ----------

_me_cache = {"t": 0.0, "user": None, "err": None}
_engine_restore = {"t": 0.0}


def _restore_engine_session(cookie: str) -> None:
    """Put the saved active account back into the embedded page after a missing/expired session."""
    now = time.time()
    if not cookie or now - _engine_restore["t"] < 20:
        return
    _engine_restore["t"] = now
    threading.Thread(target=ENGINE.import_cookies, args=(cookie,), daemon=True).start()


def _engine_on() -> bool:
    return ENGINE.window is not None


def _perm_mode() -> str:
    return permissions.normalize(load_config().get("permission_mode"))


def _remember_session(client: ArenaClient, user: dict) -> None:
    """Save rotated cookies for the active account; never overwrite it with a different arena session."""
    if not user or not client.cookie_str:
        return
    try:
        active = accounts.active_account() or {}
        saved_email = (active.get("email") or "").casefold()
        live_email = (user.get("email") or "").casefold()
        if saved_email and live_email and saved_email != live_email:
            LOG.warning("engine is signed in as %s while the active account is %s", live_email, saved_email)
            return
        accounts.update_active(client.cookie_str, user)
    except Exception:
        pass


def _get_me(client: ArenaClient):
    """Ask arena.ai who is signed in. In the desktop app only the engine uses the session:
    Supabase revokes a refresh token that two clients keep rotating."""
    if _engine_on():
        user, err = ENGINE.get_me()
        ENGINE.sync_to(client)
        _remember_session(client, user)
        return user, err
    user, err = client.get_me()
    _remember_session(client, user)
    return user, err


def _check_session(client: ArenaClient, force: bool = False):
    if not force and time.time() - _me_cache["t"] < 120:
        return _me_cache["user"], _me_cache["err"]
    user, err = _get_me(client)
    _me_cache.update(t=time.time(), user=user, err=err)
    return user, err


def _signed_in_somewhere(client: ArenaClient) -> bool:
    return bool(client.cookie_str) or (_engine_on() and ENGINE.ready() and ENGINE.has_session())


@app.route("/api/status")
def api_status():
    client = get_client()
    out = {
        "authenticated": False, "email": None, "full_name": None, "avatar_url": None,
        "session_error": None, "offline": False, "loading": False,
        "mode": _ui_mode, "modality": _ui_modality, "eval_id": client.eval_id,
        "desktop": _engine_on(), "engine": ENGINE.state(), "permission_mode": _perm_mode(),
        "workspace": str(_workspace_dir()), "projects_dir": str(workspace.PROJECTS_DIR),
        "pending_permissions": len(BROKER.pending()),
    }
    cookie_user = (parse_cookie_input(client.cookie_str)[2] if client.cookie_str else None) or {}
    ident = {"email": cookie_user.get("email"), "full_name": cookie_user.get("full_name"),
             "avatar_url": cookie_user.get("avatar_url")}
    if _engine_on() and not ENGINE.ready():
        # arena.ai is still loading or waiting on a check; answer now, the UI polls again
        out.update(ident, loading=True, authenticated=bool(client.cookie_str))
        return jsonify(out)
    if _engine_on() and ENGINE.ready() and client.cookie_str and not ENGINE.has_session():
        _restore_engine_session(client.cookie_str)
        out.update(ident, loading=True, authenticated=True)
        return jsonify(out)
    if not _signed_in_somewhere(client):
        return jsonify(out)
    user, err = _check_session(client, force=request.args.get("refresh") == "1")
    if user:
        out.update(ident, authenticated=True, email=user.get("email") or ident["email"],
                   avatar_url=user.get("avatarUrl") or ident["avatar_url"])
    elif err and err.startswith("Network error"):
        out.update(ident, authenticated=True, offline=True)
    else:
        out["session_error"] = err
    return jsonify(out)


def _activate_cookie(cookie_str: str, method: str):
    """Adopt a cookie only after arena.ai confirms the session; returns (response, ok)."""
    global _client
    previous = accounts.active_account()
    previous_cookie = (previous or {}).get("cookie")
    candidate = ArenaClient(cookie_str=cookie_str)
    expected = ((parse_cookie_input(cookie_str)[2] or {}).get("email") or "").casefold()
    if _engine_on():
        if not ENGINE.import_cookies(cookie_str):
            return jsonify({"ok": False, "error": "No arena-auth-prod-v1 cookie found in that text."}), False
        if not ENGINE.wait_ready(45):
            hint = f" It is waiting for a {ENGINE.challenge} check: press Show arena.ai." if ENGINE.challenge else ""
            if previous_cookie:
                ENGINE.import_cookies(previous_cookie)
                ENGINE.wait_ready(30)
            return jsonify({"ok": False, "error": "arena.ai did not finish loading." + hint + " Try again in a moment."}), False
        user, err = ENGINE.get_me()
        live = (user.get("email") or "").casefold() if user else ""
        if user and expected and live and live != expected:
            err = f"arena.ai stayed signed in as {user.get('email')} instead of the selected account"
            user = None
        if user:
            ENGINE.sync_to(candidate)
        elif previous_cookie:
            ENGINE.import_cookies(previous_cookie)
            ENGINE.wait_ready(30)
    else:
        user, err = candidate.get_me()
        live = (user.get("email") or "").casefold() if user else ""
        if user and expected and live and live != expected:
            err = f"arena.ai stayed signed in as {user.get('email')} instead of the selected account"
            user = None
    if not user:
        return jsonify({"ok": False, "error": f"arena.ai rejected this session ({err}). Sign in on arena.ai again, then copy fresh cookies."}), False
    accounts.remember(candidate.cookie_str, user)
    _client = candidate
    _reset_conversation(candidate)
    _me_cache.update(t=time.time(), user=user, err=None)
    _, _, cookie_user = parse_cookie_input(candidate.cookie_str)
    return jsonify({
        "ok": True, "method": method, "email": user.get("email"),
        "full_name": (cookie_user or {}).get("full_name"), "avatar_url": user.get("avatarUrl"),
    }), True


@app.route("/api/models")
def api_models():
    try:
        models = sync_models(force=request.args.get("refresh") == "1")
    except Exception:
        models = {}
    modality = request.args.get("modality", "auto")
    api_mod = MODALITY_API_MAP.get(modality, modality)
    if api_mod not in VALID_API_MODALITIES:
        api_mod = "chat"
    filtered = get_models_for_modality(models, api_mod)
    result = []
    for m in filtered:
        raw_org = m.get("org", m.get("organization", "unknown"))
        if isinstance(raw_org, dict):
            org_name = raw_org.get("name", "unknown").lower()
            org_display = raw_org.get("name", org_name)
        else:
            org_name = str(raw_org).lower()
            org_display = str(raw_org)
        result.append({
            "id": m.get("model_id", m.get("id", "")),
            "name": m.get("name", ""),
            "org": org_name,
            "org_display": org_display,
            "color": ORG_COLOR_MAP.get(org_name, "#C7C2BC"),
            "rank": m.get("rank", m.get("arena_rank")),
            "capabilities": m.get("capabilities", []),
            "arena_score": m.get("arena_score"),
        })
    resp = jsonify(result)
    resp.headers["Cache-Control"] = "no-store"  # the picker polls this as arena's catalog changes
    return resp


_LOGIN_STEPS = ("In your browser: sign in on arena.ai, press F12, open the Console tab, type copy(document.cookie) "
                "and press Enter, then press Paste from clipboard here.")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    method = data.get("method") or ("auto" if data.get("auto") else "manual")
    if method == "window":
        if not _engine_on():
            return jsonify({"ok": False, "error": "The sign-in window is part of the desktop app (arena-ai.exe). " + _LOGIN_STEPS}), 400
        ENGINE.open_login()
        return jsonify({"ok": True, "pending": True})
    if method == "auto":
        last_error = None
        for name, finder in (("cdp", fetch_cookies_via_cdp), ("browser_db", _extract_browser_cookies)):
            try:
                found = finder()
            except Exception as e:
                found, last_error = None, f"{name}: {e}"
            if found and contracts.AUTH_COOKIE_PREFIX in found:
                resp, ok = _activate_cookie(found, name)
                if ok:
                    return resp
                last_error = resp.get_json().get("error")
        return jsonify({"ok": False, "snippet": "copy(document.cookie)", "error": (
            last_error or "No signed-in arena.ai session was found in Chrome, Edge or Brave. "
            "Recent Chrome versions lock their cookies so other apps cannot read them.") + " " + _LOGIN_STEPS}), 400
    raw = get_clipboard_text() if method == "clipboard" else data.get("cookie")
    raw = (raw or "").strip()
    if not raw:
        where = "The clipboard is empty." if method == "clipboard" else "No cookie text was given."
        return jsonify({"ok": False, "error": f"{where} {_LOGIN_STEPS}"}), 400
    cookie_str, cookie_dict, _ = parse_cookie_input(raw)
    if not any(k.startswith(contracts.AUTH_COOKIE_PREFIX) for k in cookie_dict):
        return jsonify({"ok": False, "error": "That text has no arena-auth-prod-v1 cookie, so it is not an arena.ai "
                        "session. " + _LOGIN_STEPS}), 400
    resp, ok = _activate_cookie(cookie_str, method)
    return (resp, 200) if ok else (resp, 401)


@app.route("/api/login/poll")
def api_login_poll():
    """Sign-in window: report once the arena.ai page holds a confirmed account session."""
    if not _engine_on():
        return jsonify({"ok": False, "done": True, "error": "The sign-in window is part of the desktop app."})
    st = ENGINE.state()
    if not (ENGINE.ready() and ENGINE.has_session()):
        if st["login_open"]:
            return jsonify({"ok": False, "done": False, "hint": "Finish signing in in the arena.ai window."})
        return jsonify({"ok": False, "done": True, "error": "The arena.ai window was closed before sign-in finished. "
                        "If Google sign-in fails in the embedded window, use email sign-in or the cookie steps."})
    user, err = ENGINE.get_me()
    if not user or not user.get("email"):
        err = err or "Signed in as a guest only. Sign in with Google or email in the arena.ai window."
        return jsonify({"ok": False, "done": not st["login_open"], "hint": err,
                        "error": None if st["login_open"] else err})
    client = get_client()
    ENGINE.sync_to(client)
    accounts.remember(client.cookie_str, user)
    _reset_conversation(client)
    _me_cache.update(t=time.time(), user=user, err=None)
    ENGINE.finish_login()
    return jsonify({"ok": True, "done": True, "email": user.get("email"), "avatar_url": user.get("avatarUrl"),
                    "active": accounts.active_id()})


def _sign_out_account(account_id: Optional[str]):
    """Forget one account. Removing the active one switches to the next saved account first."""
    global _client
    target = accounts.get(account_id or "")
    if not target:
        return jsonify({"ok": False, "error": "Account not found."}), 404
    if account_id != accounts.active_id():
        accounts.remove(account_id)
        return jsonify({"ok": True, "active": accounts.active_id()}), 200
    others = [a for a in accounts.all_accounts() if a.get("id") != account_id]
    if others:
        resp, ok = _activate_cookie(others[0]["cookie"], "switch")
        if not ok:
            return resp, 401
        accounts.remove(account_id)
        account = accounts.active_account() or {}
        return jsonify({"ok": True, "active": accounts.active_id(), "switched_to": account.get("email")}), 200
    accounts.remove(account_id)
    if _engine_on():
        ENGINE.logout()
    _client = ArenaClient(cookie_str=None)
    _reset_conversation(_client)
    _me_cache.update(t=0.0, user=None, err=None)
    return jsonify({"ok": True, "active": None}), 200


@app.route("/api/accounts")
def api_accounts():
    return jsonify({"accounts": accounts.list_accounts(), "active": accounts.active_id()})


@app.route("/api/accounts/switch", methods=["POST"])
def api_account_switch():
    data = request.get_json(silent=True) or {}
    target = accounts.get(data.get("id") or "")
    if not target:
        return jsonify({"ok": False, "error": "Account not found."}), 404
    resp, ok = _activate_cookie(target.get("cookie") or "", "switch")
    return (resp, 200) if ok else (resp, 401)


@app.route("/api/accounts/remove", methods=["POST"])
def api_account_remove():
    data = request.get_json(silent=True) or {}
    return _sign_out_account(data.get("id"))


@app.route("/api/logout", methods=["POST"])
def api_logout():
    global _client
    data = request.get_json(silent=True) or {}
    account_id = data.get("id") or accounts.active_id()
    if account_id:
        return _sign_out_account(account_id)
    if COOKIE_FILE.exists():
        COOKIE_FILE.unlink(missing_ok=True)
    if _engine_on():
        ENGINE.logout()
    _client = ArenaClient(cookie_str=None)
    _reset_conversation(_client)
    _me_cache.update(t=0.0, user=None, err=None)
    return jsonify({"ok": True, "active": None})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify(load_config())
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    cfg.update(data)
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/mode", methods=["POST"])
def api_mode():
    global _ui_mode, _ui_modality
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "battle")
    api_mode_val = MODE_API_MAP.get(mode, mode)
    if api_mode_val not in VALID_API_MODES:
        return jsonify({"ok": False, "error": f"Invalid mode: {mode}"}), 400
    client = get_client()
    client.active_mode = api_mode_val
    client.eval_id = None
    _ui_mode = mode
    if mode == "agent":  # Agent mode runs the local tool loop; other modalities would bypass it
        _ui_modality = "auto"
        client.active_modality = "chat"
    return jsonify({"ok": True, "mode": mode, "api_mode": api_mode_val, "modality": _ui_modality})


@app.route("/api/modality", methods=["POST"])
def api_modality():
    global _ui_modality
    data = request.get_json(silent=True) or {}
    modality = data.get("modality", "chat")
    if _ui_mode == "agent" and modality != "auto":
        return jsonify({"ok": False, "error": "Agent mode uses Auto only."}), 400
    api_mod = MODALITY_API_MAP.get(modality, modality)
    if api_mod not in VALID_API_MODALITIES:
        return jsonify({"ok": False, "error": f"Invalid modality: {modality}"}), 400
    client = get_client()
    client.active_modality = api_mod
    client.eval_id = None
    _ui_modality = modality
    return jsonify({"ok": True, "modality": modality, "api_modality": api_mod})


@app.route("/api/new", methods=["POST"])
def api_new_chat():
    global _conversation_history, _current_chat_id
    client = get_client()
    client.eval_id = None
    client.sources.clear()
    _conversation_history = []
    _current_chat_id = str(uuid.uuid4())
    return jsonify({"ok": True, "chat_id": _current_chat_id})


@app.route("/api/history")
def api_history():
    return jsonify(_conversation_history)


@app.route("/api/chats")
def api_chats_list():
    return jsonify(_list_chats())


@app.route("/api/chats/<chat_id>")
def api_chat_load(chat_id):
    global _conversation_history, _current_chat_id
    data = _load_chat(chat_id)
    if not data or not _chat_owned_by_active(data):
        return jsonify({"error": "Chat not found"}), 404
    _current_chat_id = chat_id
    _conversation_history = data.get("messages", [])
    client = get_client()
    client.eval_id = data.get("eval_id")
    return jsonify(data)


@app.route("/api/chats/<chat_id>/delete", methods=["POST"])
def api_chat_delete(chat_id):
    if _delete_chat(chat_id):
        return jsonify({"ok": True})
    return jsonify({"error": "Chat not found"}), 404


@app.route("/api/chats/<chat_id>/update", methods=["POST"])
def api_chat_update(chat_id):
    """Rename or pin a chat from the sidebar's more-options menu."""
    data = _load_chat(chat_id)
    if not data or not _chat_owned_by_active(data):
        return jsonify({"error": "Chat not found"}), 404
    body = request.get_json(silent=True) or {}
    changed = False
    if "title" in body:
        title = str(body.get("title") or "").strip()[:120]
        if not title:
            return jsonify({"error": "A chat needs a name."}), 400
        data["title"] = title
        changed = True
    if "pinned" in body:
        data["pinned"] = bool(body.get("pinned"))
        changed = True
    if not changed:
        return jsonify({"error": "Nothing to update."}), 400
    chat_file = CHATS_DIR / chat_id / "chat.json"
    try:
        chat_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        return jsonify({"error": f"Could not save the chat: {exc}"}), 500
    return jsonify({"ok": True, "title": data.get("title"), "pinned": bool(data.get("pinned"))})


LOG = logging.getLogger("arena.desktop")
_tl = threading.local()  # per request: the last error shown to the user, kept in the chat history


def _sse(obj) -> str:
    if obj.get("type") == "error":
        _tl.error = obj.get("message")
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _sse_wrap(gen):
    """A crash must not end the stream silently: report it as an error event."""
    try:
        yield from gen
    except Exception as e:
        yield _sse({"type": "error", "code": "internal", "message": "The app hit an internal error.",
                    "detail": f"{type(e).__name__}: {e}", "retry": True})
        yield _sse({"type": "done", "text_a": "", "text_b": ""})


def _workspace_dir() -> Path:
    raw = load_config().get("workspace_dir")
    return Path(raw).expanduser() if raw else workspace.PROJECTS_DIR / "workspace"


def _chosen_ws() -> Optional[Path]:
    """The folder the user picked in the composer, or None when they have not picked one."""
    raw = load_config().get("workspace_dir")
    return Path(raw).expanduser() if raw else None


class _HttpStream:
    """A requests response with the EngineResponse interface, for running without the desktop engine."""

    def __init__(self, resp=None, error=None):
        self._r, self.error = resp, error
        self.status_code = resp.status_code if resp is not None else 0

    def iter_text(self):
        if self._r is None:
            return
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        for chunk in self._r.iter_content(chunk_size=None):
            if chunk:
                yield dec.decode(chunk)
        yield dec.decode(b"", final=True)

    @property
    def text(self) -> str:
        if not hasattr(self, "_text"):
            self._text = "".join(self.iter_text())
        return self._text


def _send(client: ArenaClient, path: str, body: dict):
    if _engine_on():
        if not ENGINE.wait_ready(30):
            return _HttpStream(error=f"arena.ai is waiting for a {ENGINE.challenge} check" if ENGINE.challenge
                               else "arena.ai window is still loading")
        return ENGINE.request(path, body)
    try:
        r = client.session.post(contracts.ORIGIN + path, json=body, stream=True, timeout=(15, 300))
    except requests.RequestException as e:
        return _HttpStream(error=str(e))
    client.sync_cookies()
    return _HttpStream(r)


# ---------- Attachments (arena's own upload flow) ----------

ATTACHMENT_MAX_BYTES = 15 * 1024 * 1024
ATTACHMENT_MAX_COUNT = 12
_TEXT_MIMES = {"application/json", "application/xml", "application/javascript", "application/x-javascript",
               "application/x-httpd-php", "application/x-sh", "application/x-yaml", "application/yaml",
               "application/sql"}
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
                  ".ini", ".cfg", ".conf", ".log", ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
                  ".html", ".htm", ".css", ".scss", ".sass", ".less", ".xml", ".sql", ".sh", ".bash",
                  ".bat", ".cmd", ".ps1", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".java", ".kt",
                  ".go", ".rs", ".rb", ".php", ".swift", ".lua", ".r", ".m", ".mm", ".pl", ".vue",
                  ".svelte", ".astro", ".env", ".gitignore", ".dockerfile", ".makefile"}


def _arena_reply_error(status: int, text: str) -> str:
    detail = " ".join((text or "").split())[:200]
    try:
        obj = json.loads(text or "")
        if isinstance(obj, dict):
            detail = str(obj.get("error") or obj.get("message") or detail)[:200]
    except ValueError:
        pass
    return f"arena.ai returned HTTP {status}" + (f": {detail}" if detail else "")


def _arena_json(client: ArenaClient, path: str, payload: dict, timeout: int = 60) -> dict:
    """POST JSON through the signed-in arena.ai page (desktop) or session (browser mode)."""
    if _engine_on():
        if not ENGINE.wait_ready(30):
            raise RuntimeError(f"arena.ai is waiting for a {ENGINE.challenge} check" if ENGINE.challenge
                               else "arena.ai window is still loading")
        r = ENGINE.request(path, payload, timeout=timeout)
        if r.status_code == 0:
            raise RuntimeError(r.error or "arena.ai did not answer")
        text = r.text
        if not r.ok:
            raise RuntimeError(_arena_reply_error(r.status_code, text))
        try:
            return json.loads(text or "{}")
        except ValueError:
            raise RuntimeError("arena.ai sent an unexpected reply")
    try:
        r = client.session.post(contracts.ORIGIN + path, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise RuntimeError(f"Can't reach arena.ai: {e}")
    client.sync_cookies()
    if not r.ok:
        raise RuntimeError(_arena_reply_error(r.status_code, r.text))
    try:
        return r.json()
    except ValueError:
        raise RuntimeError("arena.ai sent an unexpected reply")


def _arena_cookies(client: ArenaClient) -> dict:
    if _engine_on():
        return ENGINE.cookies()
    return {c.name: c.value for c in client.session.cookies
            if (c.domain or "").lstrip(".").endswith("arena.ai")}


def _arena_upload(client: ArenaClient, name: str, content_type: str, blob: bytes) -> dict:
    """Give one file to arena: ask for an upload URL, PUT the bytes, then resolve its signed URL."""
    gen = _arena_json(client, contracts.PATHS["storage_upload"],
                      {"fileName": name, "contentType": content_type})
    upload_url, key = gen.get("uploadUrl"), gen.get("key")
    if not isinstance(upload_url, str) or not upload_url or not key:
        raise RuntimeError("arena.ai did not return an upload URL")
    if upload_url.startswith("/"):
        upload_url = contracts.ORIGIN + upload_url
    kwargs = {"timeout": (15, 120)}
    host = (urlparse(upload_url).hostname or "").lower()
    if host == "arena.ai" or host.endswith(".arena.ai"):
        kwargs["cookies"] = _arena_cookies(client)
    try:
        put = requests.put(upload_url, data=blob, headers={"Content-Type": content_type}, **kwargs)
    except requests.RequestException as e:
        raise RuntimeError(f"Upload failed: {e}")
    if not put.ok:
        raise RuntimeError(f"Upload failed (HTTP {put.status_code})")
    signed = _arena_json(client, contracts.PATHS["storage_signed"], {"key": str(key).lstrip("/")})
    url = signed.get("url")
    if isinstance(url, str) and url.startswith("/"):
        url = contracts.ORIGIN + url
    if not isinstance(url, str) or not url.startswith("http"):
        raise RuntimeError("arena.ai did not return a file URL")
    return {"name": name, "contentType": content_type, "url": url}


def _is_text_file(name: str, content_type: str) -> bool:
    return (content_type.startswith("text/") or content_type in _TEXT_MIMES
            or Path(name).suffix.lower() in _TEXT_SUFFIXES)


def _upload_entry(client: ArenaClient, entry) -> dict:
    """Turn one composer file (browser data URL, pasted text or a native path) into text or an attachment."""
    if not isinstance(entry, dict):
        raise ValueError("Invalid file entry")
    name = Path(str(entry.get("name") or "file")).name[:200] or "file"
    content_type = str(entry.get("type") or "").split(";")[0].strip().lower()
    data = entry.get("data")
    raw = None
    if entry.get("path"):
        p = Path(str(entry["path"])).expanduser()
        if not p.is_file():
            raise ValueError(f"{name}: file not found")
        if p.stat().st_size > ATTACHMENT_MAX_BYTES:
            raise ValueError(f"{name} is larger than 15 MB")
        raw = p.read_bytes()
    elif isinstance(data, str):
        binary = entry.get("binary")
        if data.startswith("data:") and binary is not False:
            header, _, body = data.partition(",")
            content_type = content_type or header[5:].split(";")[0].strip().lower()
            try:
                raw = base64.b64decode(body) if ";base64" in header else urllib.parse.unquote_to_bytes(body)
            except ValueError:
                raise ValueError(f"{name}: the file data is damaged")
        else:
            raw = data.encode("utf-8")
            content_type = content_type or "text/plain"
    if not raw:
        raise ValueError(f"{name} is empty")
    if len(raw) > ATTACHMENT_MAX_BYTES:
        raise ValueError(f"{name} is larger than 15 MB")
    if not content_type or content_type in ("application/octet-stream", "binary/octet-stream"):
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if _is_text_file(name, content_type):
        text = raw.decode("utf-8", errors="replace")
        if "\x00" not in text[:4096]:
            return {"name": name, "type": content_type, "size": len(raw), "text": text}
    return {"name": name, "type": content_type, "size": len(raw),
            "attachment": _arena_upload(client, name, content_type, raw)}


def _clean_attachments(raw) -> list:
    """Keep only the attachment fields arena expects; drop anything else the frontend may send."""
    out = []
    for a in (raw if isinstance(raw, list) else [])[:ATTACHMENT_MAX_COUNT]:
        if not isinstance(a, dict):
            continue
        url = str(a.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        out.append({"name": str(a.get("name") or "file")[:200],
                    "contentType": str(a.get("contentType") or "application/octet-stream")[:120],
                    "url": url})
    return out


@app.route("/api/upload", methods=["POST"])
def api_upload():
    data = request.get_json(silent=True) or {}
    files = data.get("files")
    if not isinstance(files, list) or not files:
        return jsonify({"error": "No files to upload"}), 400
    if len(files) > ATTACHMENT_MAX_COUNT:
        return jsonify({"error": f"Attach at most {ATTACHMENT_MAX_COUNT} files at once."}), 400
    client = get_client()
    if not _signed_in_somewhere(client):
        return jsonify({"error": "Not signed in. Press Sign in first.", "code": "auth"}), 401
    out = []
    for entry in files:
        try:
            out.append(_upload_entry(client, entry))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 502
    return jsonify({"files": out})


def _wait_for(check, seconds: int):
    """Poll check() once a second with keep-alive pings; returns its first truthy value."""
    for i in range(seconds):
        value = check()
        if value or _stop.is_set():
            return value
        time.sleep(1)
        if i % 10 == 9:
            yield _sse({"type": "ping"})
    return check()


def _pause(seconds: int):
    """Wait between arena.ai attempts, keeping the stream alive; returns False when the user pressed Stop."""
    deadline = time.time() + max(1, int(seconds))
    yield _sse({"type": "ping"})
    yield from _wait_for(lambda: time.time() >= deadline, int(seconds) + 2)
    return not _stop.is_set()


def _permit(mode: str, tool: str, info: dict):
    """Apply the permission mode to one action, asking the user when needed.
    Yields SSE events; returns "allow", "deny" (the user said no) or "blocked" (the mode forbids it)."""
    verdict = BROKER.check(mode, tool, info.get("inside", True), info.get("command", ""))
    if verdict == "allow":
        return "allow"
    if verdict == "deny":
        why = "Plan mode is read-only" if mode == "plan" else "This command is never allowed"
        yield _sse({"type": "notice", "level": "warn", "text": f"{why}: {info.get('summary')}"})
        return "blocked"
    pid = BROKER.ask(dict(info, mode=mode))
    yield _sse(dict(info, type="permission", id=pid, mode=mode))
    answer = yield from _wait_for(lambda: BROKER.wait(pid, 0), 600)
    if not answer:
        BROKER.resolve(pid, "deny")
        BROKER.wait(pid, 0)
        answer = "deny"
    yield _sse({"type": "permission_done", "id": pid, "decision": answer})
    return answer


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


_preview = {"port": None}
_preview_lock = threading.Lock()


def _preview_url(root: Path):
    """Serve generated sites from a separate port (a separate origin) so their scripts cannot call this app's API."""
    if not (Path(root) / "index.html").is_file():
        return None
    base = workspace.PROJECTS_DIR.resolve()
    try:
        rel = Path(root).resolve().relative_to(base).as_posix()
    except ValueError:
        return None
    with _preview_lock:
        if _preview["port"] is None:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(base)))
            _preview["port"] = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{_preview['port']}/{urllib.parse.quote(rel)}/index.html"


def _save_webdev(lane: str, files: list, conv: dict):
    """Mirror a code answer into its local project folder, asking first unless the mode allows edits."""
    root = workspace.project_dir(conv["chat_id"], conv["title"], lane, base=_chosen_ws())
    plan = workspace.plan_project(root, files)
    mode = _perm_mode()
    write = delete = False
    if plan["writes"]:
        write = (yield from _permit(mode, "write_project", {
            "tool": "write_project", "path": str(root), "rel": root.name, "inside": True,
            "summary": f"Save {len(plan['writes'])} code file(s) from model {lane.upper()} to {root}",
            "files": sorted(plan["writes"])[:50]})) == "allow"
    if plan["deletes"]:
        delete = (yield from _permit(mode, "delete", {
            "tool": "delete", "path": str(root), "rel": root.name, "inside": True,
            "summary": f"Remove {len(plan['deletes'])} file(s) the new answer dropped from {root}",
            "files": plan["deletes"][:50]})) == "allow"
    written, deleted = workspace.apply_project(plan, write=write, delete=delete) if (write or delete) else (0, 0)
    saved = write or not plan["writes"]
    yield _sse({"type": "files_written", "model": lane, "root": str(root), "written": written, "deleted": deleted,
                "unchanged": plan["unchanged"], "skipped": plan["skipped"], "saved": saved,
                "files": plan["files"], "preview": _preview_url(root) if saved else None})


def _webdev_event(lane: str, item: dict, conv: dict):
    event = item.get("event")
    if event == "title" and isinstance(item.get("title"), str):
        conv["title"] = item["title"][:80]
    yield _sse({"type": "webdev", "model": lane, "event": event, "data": item})
    files = workspace.webdev_files(item)
    if files:
        _last_webdev[(conv["chat_id"], lane)] = {"title": conv["title"], "files": files}
        yield from _save_webdev(lane, files, conv)
    url = contracts.find_preview_url(item)
    if event == "preview-ready" or url:
        yield _sse({"type": "preview", "model": lane, "url": url, "status": item.get("status"),
                    "message": item.get("message") or item.get("reason")})


# ARENA_STREAM_DUMP=1 writes every raw stream line to ~/.arena-cli/streams/<chat>.txt, to study arena's stream parts.
_DUMP_DIR = (CHATS_DIR.parent / "streams") if os.environ.get("ARENA_STREAM_DUMP") else None


def _dump_line(conv: dict, line) -> None:
    raw = line if isinstance(line, str) else line.decode("utf-8", "replace")
    try:
        _DUMP_DIR.mkdir(parents=True, exist_ok=True)
        with open(_DUMP_DIR / f"{conv['chat_id'][:8]}.txt", "a", encoding="utf-8") as f:
            f.write(raw.rstrip("\r\n") + "\n")
    except OSError:
        pass


def _save_media(m: dict, lane: str, conv: dict):
    """Keep a generated image, video or sound in the folder the user picked (when they picked one)."""
    ws = _chosen_ws()
    done = conv.setdefault("media_saved", set())
    if ws is None or m["url"] in done:
        return
    done.add(m["url"])
    try:
        r = requests.get(m["url"], timeout=120)
        r.raise_for_status()
        ext = Path(urlparse(m["url"]).path).suffix[:6] or mimetypes.guess_extension(
            (r.headers.get("content-type") or "").split(";")[0].strip()) or ".bin"
        ws.mkdir(parents=True, exist_ok=True)
        target = ws / f"{workspace.slug(conv['title'])}-{lane}-{uuid.uuid4().hex[:6]}{ext}"
        target.write_bytes(r.content)
    except (requests.RequestException, OSError) as e:
        yield _sse({"type": "notice", "model": lane, "text": f"Could not save the {m.get('kind') or 'file'}: {e}"})
        return
    yield _sse({"type": "notice", "model": lane, "text": f"Saved to {target}"})


def _code_root(chat_id: str, title: str, lane: str, mode: str) -> Path:
    """Where the files an AI builds land: the picked folder (option-a/option-b when two models answer),
    else this chat's own folder under ArenaProjects."""
    ws = _chosen_ws()
    if ws is None:
        return workspace.project_dir(chat_id, title, lane)
    return (ws / agent.LANE_DIRS[lane] if mode in ("battle", "side-by-side") else ws).expanduser().resolve()


def _sync_file(root: Path) -> Path:
    return CHATS_DIR.parent / "sync" / (hashlib.sha1(str(root).lower().encode()).hexdigest()[:16] + ".json")


def _sync_load(root: Path) -> dict:
    """What the AI last wrote to each file in a folder (path -> sha1), to spot the user's own edits."""
    try:
        return json.loads(_sync_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sync_save(root: Path, man: dict) -> None:
    try:
        f = _sync_file(root)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(man), encoding="utf-8")
    except OSError:
        pass


def _digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _line_delta(old: str, new: str):
    """Lines added and removed between two versions of a file."""
    add = rem = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            rem += i2 - i1
        if tag in ("replace", "insert"):
            add += j2 - j1
    return add, rem


_SB_VERB = {"read": "Read", "run": "Ran", "touch": "Changed"}


def _sandbox_call(lane: str, call: dict, conv: dict):
    """arena.ai's model used one of arena's own sandbox tools. Copy file writes, edits, deletes and downloads
    into the local project folder, and show the step as an activity row like arena.ai's."""
    op = contracts.sandbox_op(call)
    LOG.info("chat %s sandbox %s %s %s", conv["chat_id"][:8], lane, op["tool"], op.get("path") or op.get("detail", ""))
    row = {"id": op["id"], "kind": op["kind"], "tool": op["tool"], "path": op.get("path"), "detail": op.get("detail"),
           "verb": _SB_VERB.get(op["kind"], op["tool"])}
    if op["kind"] in ("write", "edit") and not (op.get("content") or op.get("old")):
        # arena.ai streams each call twice: first with empty arguments, then complete. Write on the complete one.
        row.update(verb="Writing" if op["kind"] == "write" else "Editing", pending=True)
    elif op["kind"] in ("write", "edit", "delete", "download"):
        root = _code_root(conv["chat_id"], conv["title"], lane, conv["mode"])
        if conv.get("mirror_ok") is None:
            info = {"tool": "write_file", "summary": f"Copy the files the AI writes into {root}", "inside": True,
                    "path": str(root), "rel": ".", "model": lane}
            conv["mirror_ok"] = (yield from _permit(_perm_mode(), "write_file", info)) == "allow"
        try:
            if not conv["mirror_ok"]:
                raise PermissionError("not copied: the permission mode does not allow it")
            target = workspace._inside(root, op["path"])
            rel = target.relative_to(root).as_posix()
            man = _sync_load(root)
            old = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
            if op["kind"] == "delete":
                if target.is_file():
                    target.unlink()
                man.pop(rel, None)
                row["verb"] = "Deleted"
            else:
                if op["kind"] == "download":
                    r = requests.get(op["url"], timeout=60)
                    r.raise_for_status()
                    data = r.content
                    row["verb"] = "Saved"
                else:
                    if op["kind"] == "edit":
                        if old is None or op["old"] not in old:
                            raise ValueError("not copied: your copy of this file differs from the AI's")
                        new = old.replace(op["old"], op["new"], 1)
                    else:
                        new = op["content"]
                    row["add"], row["del"] = _line_delta(old or "", new)
                    row["verb"] = "Created" if old is None else "Edited"
                    data = new.encode("utf-8")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                man[rel] = _digest(data)
            _sync_save(root, man)
            row.update(abs=str(target), root=str(root))
        except (OSError, ValueError, requests.RequestException) as e:
            row["error"] = str(e)[:160]
    rows = conv.setdefault("sandbox", [])
    if row["id"]:
        rows[:] = [r for r in rows if not (r.get("id") == row["id"] and r.get("model") == lane)]
    rows.append(dict(row, model=lane))
    yield _sse(dict(row, type="sandbox", model=lane))


def _sandbox_result(lane: str, res: dict, conv: dict):
    """A sandbox tool finished: tick its row, and pass on any preview link (<id>.arena.site) it carries."""
    rid = res.get("toolCallId") or res.get("id")
    out = res.get("result", res.get("output"))
    bad = isinstance(out, dict) and bool(out.get("error") or out.get("success") is False or out.get("isError"))
    for row in conv.get("sandbox", []):
        if row.get("id") == rid and row.get("model") == lane:
            row["ok"] = not bad
    yield _sse({"type": "sandbox_done", "model": lane, "id": rid, "ok": not bad})
    url = contracts.find_preview_url(out)
    if url and url not in conv.setdefault("previews", set()):
        conv["previews"].add(url)
        yield _sse({"type": "preview", "model": lane, "url": url})


def _local_edits(root: Path):
    """Files the user changed on disk since the AI last wrote them, as a note in front of the next message."""
    man = _sync_load(root)
    changed, parts, size = [], [], 0
    for rel, digest in list(man.items()):
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        if _digest(data) == digest:
            continue
        changed.append(rel)
        text = data.decode("utf-8", "replace")
        if size + len(text) <= 60_000 and len(parts) < 12:
            parts.append(f"--- {rel} ---\n{text}")
            size += len(text)
        man[rel] = _digest(data)
    if not changed:
        return [], ""
    _sync_save(root, man)
    extra = [r for r in changed if not any(p.startswith(f"--- {r} ---") for p in parts)]
    note = ("I edited these files on my computer since your last change. Update your copy of each one to exactly "
            "this content before you continue:\n\n" + "\n\n".join(parts)
            + (f"\n\nAlso changed (too large to include): {', '.join(extra)}" if extra else "") + "\n\nMy message:\n")
    return changed, note


def _line_events(r, conv: dict):
    """Turn arena's stream into SSE events; returns the answer text per lane."""
    out = {"a": "", "b": ""}
    split = contracts.LineSplitter()

    def handle(line):
        if _DUMP_DIR:
            _dump_line(conv, line)
        parsed = contracts.parse_line(line)
        if not parsed:
            return
        lane, kind, value = parsed
        if kind == "text":
            out[lane] += str(value)
            yield _sse({"type": "text", "model": lane, "text": str(value)})
        elif kind == "reasoning":
            yield _sse({"type": "reasoning", "model": lane, "text": str(value)})
        elif kind == "source":
            yield _sse({"type": "source", "model": lane, "data": value})
        elif kind == "error":
            yield _sse({"type": "error", "code": "model", "model": lane, "retry": True,
                        "message": f"Model {lane.upper()} stopped with an error: {value}"})
        elif kind == "tool_call" and isinstance(value, dict):
            yield from _sandbox_call(lane, value, conv)
        elif kind == "tool_result" and isinstance(value, dict):
            yield from _sandbox_result(lane, value, conv)
        elif kind in ("data", "file", "annotation"):
            items = contracts.webdev_items(value)
            for item in items:
                yield from _webdev_event(lane, item, conv)
            if not items:
                for m in contracts.find_media(value):
                    yield _sse(dict(m, type="media", model=lane))
                    yield from _save_media(m, lane, conv)
                url = contracts.find_preview_url(value)
                if url:
                    yield _sse({"type": "preview", "model": lane, "url": url})

    for chunk in r.iter_text():
        for line in split.feed(chunk):
            yield from handle(line)
        if _stop.is_set():
            yield _sse({"type": "notice", "text": "Stopped."})
            return out
    for line in split.flush():
        yield from handle(line)
    return out


def _turn(client: ArenaClient, content: str, conv: dict, attachments=None):
    """Send one message and stream the answer. Yields SSE events; returns {"a": text, "b": text},
    or None after sending an error event."""
    v2 = None
    rate_waits = 0
    while True:
        if conv["new"] and not conv.get("eval_id"):
            conv["eval_id"] = generate_uuidv7()
        try:
            path, body = contracts.build_chat(
                eval_id=conv["eval_id"], new=conv["new"], mode=conv["mode"], modality=conv["modality"],
                content=content, ids=generate_uuidv7, model_a=conv.get("model_a"), model_b=conv.get("model_b"),
                attachments=attachments, v2_token=v2)
        except ValueError as e:
            yield _sse({"type": "error", "code": "bad_request", "message": str(e), "retry": False})
            return None
        v2 = None
        r = _send(client, path, body)
        LOG.info("chat %s: HTTP %s (v2 token sent: %s)", conv["chat_id"][:8], r.status_code, bool(body.get("recaptchaV2Token")))
        if r.status_code == 200:
            conv["new"] = False
            out = yield from _line_events(r, conv)
            if _engine_on():
                ENGINE.sync_to(client)
            return out
        err = contracts.classify_error(r.status_code, r.text if r.status_code else (r.error or ""))
        LOG.info("chat %s: %s - %s", conv["chat_id"][:8], err.get("code"), str(err.get("message", ""))[:200])
        if r.status_code == 0 and _engine_on() and ENGINE.challenge == "cloudflare":
            err["code"] = "cloudflare"
        if err["code"] == "challenge" and _engine_on():
            ENGINE.request_human_check()
            yield _sse({"type": "challenge", "kind": "recaptcha", "message": "arena.ai wants a quick human check. "
                        "Tick the box in the arena.ai window; your message is resent right after."})
            token = yield from _wait_for(
                lambda: ENGINE.take_v2_token() or (ENGINE.challenge != "recaptcha" and "closed"), 300)
            if token == "closed":
                token = ENGINE.take_v2_token()
            LOG.info("chat %s: human check %s", conv["chat_id"][:8], "passed" if token else "not finished")
            if not token:
                ENGINE.cancel_check()
                yield _sse({"type": "error", "code": "challenge", "retry": True,
                            "message": "The human check was not finished, so nothing was sent."})
                return None
            yield _sse({"type": "challenge_done"})
            v2 = token
            continue
        if err["code"] == "cloudflare" and _engine_on():
            if ENGINE.ready():
                ENGINE.show_cloudflare()
            yield _sse({"type": "challenge", "kind": "cloudflare",
                        "message": "arena.ai is showing a Cloudflare check. Finish it in the arena.ai window."})
            if not (yield from _wait_for(ENGINE.ready, 300)):
                yield _sse({"type": "error", "code": "cloudflare", "retry": True,
                            "message": "The Cloudflare check was not finished."})
                return None
            yield _sse({"type": "challenge_done"})
            continue
        if err["code"] == "eval_gone" and not conv["new"]:
            conv.update(new=True, eval_id=None)
            yield _sse({"type": "notice", "text": "arena.ai no longer has this conversation, so a new one was started."})
            continue
        if err["code"] == "rate_limit":
            rate_waits += 1
            wait = max(15, int(err.get("wait") or 60))
            if rate_waits > 1:
                wait = min(wait * rate_waits, 300)
            # Pace later tool rounds slower after a limit, so a long task does not walk into it again.
            conv["pace"] = max(float(conv.get("pace") or 0), min(wait / 10.0, 10.0))
            yield _sse({"type": "notice", "text": f"arena.ai rate-limited this account. Waiting {wait}s, then retrying "
                                                  "automatically. Press Stop to cancel."})
            if not (yield from _pause(wait)):
                yield _sse({"type": "notice", "text": "Stopped."})
                return None
            continue
        if err["code"] in ("challenge", "cloudflare"):
            err["message"] += " Open Arena Desktop (arena-ai.exe): it shows arena.ai's check so you can finish it."
        yield _sse(dict(err, type="error"))
        return None


def _agent_run(client: ArenaClient, message: str, conv: dict, attachments=None):
    """Local tools in a text chat: each model asks for tools and the app runs them under the permission mode.
    In Battle and Side by Side each model writes to its own copy of the folder (option-a, option-b)."""
    root = _workspace_dir()
    root.mkdir(parents=True, exist_ok=True)
    lanes = ("a", "b") if conv["mode"] in ("battle", "side-by-side") else ("a",)
    dual = len(lanes) == 2
    tools = {l: agent.LocalTools(root, root / agent.LANE_DIRS[l] if dual else None) for l in lanes}
    mode = _perm_mode()
    content = message
    if conv["new"]:
        content = agent.guide(root, permissions.MODES[mode], agent.MODE_NOTES[mode], dual) + message
    total = {"a": "", "b": ""}
    yield _sse({"type": "agent", "root": str(root), "mode": mode, "dual": dual})
    rnd = 0
    while True:
        rnd += 1
        pace = float(conv.get("pace") or 0)
        if rnd > 1 and pace > 0:
            if not conv.get("paced_notice"):
                conv["paced_notice"] = True
                yield _sse({"type": "notice", "text": f"Pacing tool rounds by {int(pace)}s to stay under arena.ai's rate limit."})
            if not (yield from _pause(pace)):
                break
        out = yield from _turn(client, content, conv, attachments if rnd == 1 else None)
        if out is None:
            break
        calls = {l: agent.parse_tool_calls(out[l]) for l in lanes}
        for l in lanes:
            total[l] += out[l]
        if not any(calls.values()) or _stop.is_set():
            break
        mode = _perm_mode()
        results = {}
        for l in lanes:
            results[l] = outcomes = []
            for call in calls[l]:
                if _stop.is_set():
                    outcomes.append((call, "skipped: the user pressed Stop", ""))
                    continue
                info = dict(tools[l].describe(call), model=l)
                yield _sse(dict(info, type="tool_call"))
                if call["name"] not in permissions.KIND:
                    ok, output = tools[l].run(call)
                    status = "error"
                else:
                    answer = yield from _permit(mode, call["name"], info)
                    if answer == "allow":
                        ok, output = tools[l].run(call)
                        status = "ok" if ok else "error"
                    else:
                        ok, output = False, ""
                        status = ("blocked: plan mode is read-only" if mode == "plan" else "blocked by safety rules") \
                            if answer == "blocked" else "denied by the user"
                outcomes.append((call, status, output))
                conv.setdefault("tools", []).append({"tool": call["name"], "summary": info.get("summary"), "lane": l,
                                                     "diff": info.get("diff"), "ok": ok, "status": status})
                yield _sse({"type": "tool_result", "model": l, "tool": call["name"], "rel": info.get("rel"), "ok": ok,
                            "status": status, "output": (output or "")[:4000]})
        if _stop.is_set():
            break
        content = agent.format_lane_results(results) if dual else agent.format_results(results["a"])
        for l in lanes:
            total[l] += "\n\n"
        yield _sse({"type": "round", "n": rnd + 1})
    return total


def _model_name(model_id):
    """Display name for a model id from the cached catalog (None when unknown)."""
    if not model_id:
        return None
    try:
        stack = [sync_models(force=False)]
    except Exception:
        return None
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("model_id", cur.get("id")) == model_id and cur.get("name"):
                return cur["name"]
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


@app.route("/api/chat", methods=["POST"])
def api_chat():
    global _current_chat_id, _conversation_history
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    attachments = _clean_attachments(data.get("attachments"))
    if not message and not attachments:
        return jsonify({"error": "Empty message"}), 400
    client = get_client()
    if not _signed_in_somewhere(client):
        return jsonify({"error": "Not signed in. Press Sign in first.", "code": "auth"}), 401
    mode, modality = contracts.api_mode(_ui_mode), contracts.api_modality(_ui_modality)
    model_a, model_b = data.get("model_id") or None, data.get("model_id_b") or None
    if mode != "battle" and not model_a:
        return jsonify({"error": "Pick a model first: Direct, Agent and Side by Side need one.", "code": "bad_request"}), 400
    if mode == "side-by-side" and not model_b:
        return jsonify({"error": "Pick a second model for Side by Side.", "code": "bad_request"}), 400
    _current_chat_id = data.get("chat_id") or str(uuid.uuid4())
    _stop.clear()
    existing = _load_chat(_current_chat_id) or {}
    if existing and not _chat_owned_by_active(existing):
        _current_chat_id = str(uuid.uuid4())  # never append to another account's saved chat
        existing = {}
    # Each chat keeps its own history and arena conversation. Switching models keeps it, like arena.ai's own
    # follow-up box; a new mode or modality starts a new one.
    same = bool(existing) and (existing.get("mode"), existing.get("modality")) == (_ui_mode, _ui_modality)
    eval_id = existing.get("eval_id") if same else None
    title = message or (attachments[0]["name"] if attachments else "New chat")
    conv = {"eval_id": eval_id, "new": not eval_id, "mode": mode, "modality": modality,
            "model_a": model_a, "model_b": model_b, "chat_id": _current_chat_id,
            "title": existing.get("title") or title[:50], "tools": []}
    history = list(existing.get("messages") or [])
    history.append({"role": "user", "text": message})
    _conversation_history = history
    ui_mode, ui_modality = _ui_mode, _ui_modality
    names = {"a": _model_name(model_a), "b": _model_name(model_b)}
    dual = mode in ("battle", "side-by-side")
    # Once the user picks a folder, every text chat can use it, whatever the mode; Agent always can.
    tools_on = ui_mode == "agent" or (_chosen_ws() is not None and modality in ("chat", "search"))

    def generate():
        _tl.error = None
        yield _sse({"type": "meta", "dual": dual, "mode": ui_mode, "modality": ui_modality,
                    "chat_id": conv["chat_id"], "permission_mode": _perm_mode(), "names": names})
        send = message
        if modality == "webdev" and not dual and not conv["new"]:
            changed, note = _local_edits(_code_root(conv["chat_id"], conv["title"], "a", conv["mode"]))
            if changed:
                send = note + message
                yield _sse({"type": "notice", "text": "Sent your local edits to the AI: " + ", ".join(changed)})
        if tools_on:
            out = yield from _agent_run(client, send, conv, attachments)
        else:
            out = yield from _turn(client, send, conv, attachments)
        out = out or {"a": "", "b": ""}
        client.eval_id = None if conv["new"] else conv["eval_id"]
        clean = agent.strip_tool_calls if tools_on else str
        reply = {"role": "assistant", "text": clean(out["a"]), "text_b": clean(out["b"]), "names": names}
        if conv["tools"]:
            reply["tools"] = conv["tools"]
        if conv.get("sandbox"):
            reply["sandbox"] = conv["sandbox"]
        if not (out["a"] or out["b"]) and _tl.error:
            reply["error"] = _tl.error
        history.append(reply)
        _save_chat(conv["chat_id"], title=conv["title"], messages=history, mode=ui_mode,
                   modality=ui_modality, model_a=model_a, model_b=model_b, eval_id=client.eval_id)
        yield _sse({"type": "done", "text_a": out["a"], "text_b": out["b"], "dual": dual, "chat_id": conv["chat_id"]})

    return Response(
        stream_with_context(_sse_wrap(generate())),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- OpenAI-Compatible /v1 Endpoints & API Dashboard ----------

@app.after_request
def _add_cors_headers(response):
    if request.path.startswith("/v1/") or request.path.startswith("/api/v1/") or request.path.startswith("/dashboard"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return response


@app.route("/v1/models", methods=["GET", "OPTIONS"])
def v1_models():
    if request.method == "OPTIONS":
        return Response("", status=204)
    all_models = sync_models(force=False)
    return jsonify(format_model_list(all_models))


def _v1_execute_turn(client, prompt: str, model_id: str):
    """Executes a chat turn against Arena, automatically handling reCAPTCHA v2 / Cloudflare checks."""
    eval_id = generate_uuidv7()
    v2 = None
    challenge_occurred = False

    while True:
        try:
            path, send_body = contracts.build_chat(
                eval_id=eval_id,
                new=True,
                mode=contracts.api_mode("direct"),
                modality="chat",
                content=prompt,
                ids=generate_uuidv7,
                model_a=model_id,
                v2_token=v2,
            )
        except ValueError as e:
            return None, str(e), 400, challenge_occurred

        r = _send(client, path, send_body)
        if r.status_code == 200:
            if _engine_on():
                ENGINE.sync_to(client)
            return r, None, 200, challenge_occurred

        err = contracts.classify_error(r.status_code, r.text if r.status_code else (r.error or ""))
        if err.get("code") == "challenge" and _engine_on():
            challenge_occurred = True
            LOG.info("API request triggered human check: showing challenge window")
            ENGINE.request_human_check()
            end = time.time() + 180
            token = None
            while time.time() < end:
                token = ENGINE.take_v2_token()
                if token or ENGINE.challenge != "recaptcha":
                    break
                time.sleep(0.5)
            if not token:
                ENGINE.cancel_check()
                return None, "reCAPTCHA verification was not completed in the Arena window.", 429, challenge_occurred
            v2 = token
            continue

        if err.get("code") == "cloudflare" and _engine_on():
            challenge_occurred = True
            if ENGINE.ready():
                ENGINE.show_cloudflare()
            end = time.time() + 180
            while time.time() < end and not ENGINE.ready():
                time.sleep(0.5)
            if not ENGINE.ready():
                return None, "Cloudflare check was not completed in the Arena window.", 429, challenge_occurred
            continue

        msg = err.get("message") or f"Arena API returned HTTP {r.status_code}"
        status = 429 if err.get("code") == "rate_limit" else (r.status_code or 500)
        return None, msg, status, challenge_occurred


@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def v1_chat_completions():
    if request.method == "OPTIONS":
        return Response("", status=204)

    start_time = time.time()
    req_id = "chatcmpl-" + uuid.uuid4().hex[:16]
    data = request.get_json(silent=True) or {}
    messages = data.get("messages")
    if not messages or not isinstance(messages, list):
        return jsonify(format_openai_error("Missing or invalid 'messages' array", "invalid_request_error", 400)), 400

    raw_model = data.get("model")
    if raw_model is not None and not str(raw_model).strip():
        return jsonify(format_openai_error("Model name cannot be empty", "invalid_request_error", 400)), 400
    model_param = (raw_model or "gpt-4o").strip()
    all_models = sync_models(force=False)
    model_id, display_name = resolve_model(model_param, all_models)
    if not model_id:
        return jsonify(format_openai_error(f"Model '{model_param}' not found in catalog", "invalid_request_error", 404)), 404

    client = get_client()
    if not _signed_in_somewhere(client):
        return jsonify(format_openai_error("Arena session not signed in. Open Arena Desktop and sign in first.", "authentication_error", 401)), 401

    stream = bool(data.get("stream", False))
    prompt = format_messages_to_prompt(messages)
    prompt_tokens = estimate_tokens(prompt)

    r, err_msg, status, challenge = _v1_execute_turn(client, prompt, model_id)
    if err_msg or not r:
        latency_ms = int((time.time() - start_time) * 1000)
        API_LOGGER.log_request(
            req_id, model_param, model_id, status, latency_ms, stream, prompt_tokens, 0, err_msg, challenge
        )
        return jsonify(format_openai_error(err_msg, "api_error", status)), status

    if not stream:
        full_text = ""
        full_reasoning = ""
        split = contracts.LineSplitter()
        for chunk in r.iter_text():
            for line in split.feed(chunk):
                parsed = contracts.parse_line(line)
                if not parsed:
                    continue
                lane, kind, value = parsed
                if kind == "text":
                    full_text += str(value)
                elif kind == "reasoning":
                    full_reasoning += str(value)
        for line in split.flush():
            parsed = contracts.parse_line(line)
            if parsed:
                lane, kind, value = parsed
                if kind == "text":
                    full_text += str(value)
                elif kind == "reasoning":
                    full_reasoning += str(value)

        comp_tokens = estimate_tokens(full_text)
        latency_ms = int((time.time() - start_time) * 1000)
        API_LOGGER.log_request(
            req_id, model_param, model_id, 200, latency_ms, False, prompt_tokens, comp_tokens, None, challenge
        )
        return jsonify(format_openai_completion(
            req_id=req_id,
            model=model_param,
            content=full_text,
            reasoning=full_reasoning if full_reasoning else None,
            prompt_tokens=prompt_tokens,
            completion_tokens=comp_tokens,
        ))

    def generate_sse():
        split = contracts.LineSplitter()
        comp_chars = 0
        try:
            for chunk in r.iter_text():
                for line in split.feed(chunk):
                    parsed = contracts.parse_line(line)
                    if not parsed:
                        continue
                    lane, kind, value = parsed
                    if kind == "text":
                        text_val = str(value)
                        comp_chars += len(text_val)
                        yield format_openai_sse_chunk(req_id, model_param, content=text_val)
                    elif kind == "reasoning":
                        yield format_openai_sse_chunk(req_id, model_param, reasoning=str(value))
            for line in split.flush():
                parsed = contracts.parse_line(line)
                if parsed:
                    lane, kind, value = parsed
                    if kind == "text":
                        text_val = str(value)
                        comp_chars += len(text_val)
                        yield format_openai_sse_chunk(req_id, model_param, content=text_val)
                    elif kind == "reasoning":
                        yield format_openai_sse_chunk(req_id, model_param, reasoning=str(value))

            yield format_openai_sse_chunk(req_id, model_param, finish_reason="stop")
            yield "data: [DONE]\n\n"
            latency_ms = int((time.time() - start_time) * 1000)
            API_LOGGER.log_request(
                req_id, model_param, model_id, 200, latency_ms, True, prompt_tokens, max(1, comp_chars // 4), None, challenge
            )
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            API_LOGGER.log_request(
                req_id, model_param, model_id, 500, latency_ms, True, prompt_tokens, max(1, comp_chars // 4), str(e), challenge
            )
            yield f"data: {json.dumps(format_openai_error(str(e)))}\n\n"

    return Response(
        stream_with_context(generate_sse()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/v1/stats", methods=["GET"])
def api_v1_stats():
    limit = request.args.get("limit", default=50, type=int)
    stats = API_LOGGER.get_stats()
    logs = API_LOGGER.get_recent(limit=limit)
    port = request.host.split(":")[-1] if ":" in request.host else "80"
    return jsonify({
        "stats": stats,
        "logs": logs,
        "port": port,
        "base_url": f"http://127.0.0.1:{port}/v1",
    })


@app.route("/api/v1/logs/clear", methods=["POST"])
def api_v1_logs_clear():
    API_LOGGER.clear()
    return jsonify({"status": "cleared"})


# ---------- File CRUD (IDE) ----------

def _safe_resolve(rel_path: str) -> Path:
    """Resolve a user-supplied path, blocking traversal outside home."""
    home = Path.home().resolve()
    if rel_path in ("", "."):
        return home
    p = Path(rel_path).expanduser()
    p = (p if p.is_absolute() else home / p).resolve()
    if p != home and home not in p.parents:
        raise PermissionError("Access denied: outside home directory")
    return p


@app.route("/api/files")
def api_files_list():
    rel = request.args.get("path", ".")
    try:
        p = _safe_resolve(rel)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    if not p.is_dir():
        return jsonify({"error": "Not a directory"}), 400
    items = []
    try:
        for child in sorted(p.iterdir()):
            try:
                items.append({
                    "name": child.name,
                    "path": str(child),
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else 0,
                })
            except (PermissionError, OSError):
                pass
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    return jsonify({"files": items, "cwd": str(p)})


@app.route("/api/files/read")
def api_files_read():
    rel = request.args.get("path", "")
    if not rel:
        return jsonify({"error": "No path"}), 400
    try:
        p = _safe_resolve(rel)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    if not p.is_file():
        return jsonify({"error": "Not a file"}), 404
    if p.stat().st_size > 2 * 1024 * 1024:
        return jsonify({"error": "File too large (>2 MB)"}), 400
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"content": content, "path": str(p)})


@app.route("/api/files/write", methods=["POST"])
def api_files_write():
    data = request.get_json(silent=True) or {}
    rel = data.get("path", "")
    content = data.get("content", "")
    if not rel:
        return jsonify({"error": "No path"}), 400
    try:
        p = _safe_resolve(rel)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return jsonify({"ok": True, "path": str(p)})


@app.route("/api/files/delete", methods=["POST"])
def api_files_delete():
    data = request.get_json(silent=True) or {}
    rel = data.get("path", "")
    if not rel:
        return jsonify({"error": "No path"}), 400
    try:
        p = _safe_resolve(rel)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    if p.is_file():
        p.unlink()
    elif p.is_dir():
        import shutil
        shutil.rmtree(p)
    else:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/files/mkdir", methods=["POST"])
def api_files_mkdir():
    data = request.get_json(silent=True) or {}
    rel = data.get("path", "")
    if not rel:
        return jsonify({"error": "No path"}), 400
    try:
        p = _safe_resolve(rel)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    p.mkdir(parents=True, exist_ok=True)
    return jsonify({"ok": True, "path": str(p)})


# ---------- Terminal ----------

@app.route("/api/terminal", methods=["POST"])
def api_terminal():
    import subprocess
    data = request.get_json(silent=True) or {}
    cmd = data.get("command", "").strip()
    if not cmd:
        return jsonify({"error": "No command"}), 400
    blocked = ["format", "del /s", "rd /s", "rmdir /s", "rm -rf /"]
    for b in blocked:
        if b in cmd.lower():
            return jsonify({"error": f"Blocked: {b}"}), 403
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=30, cwd=str(Path.home()),
        )
        return jsonify({
            "output": result.stdout[-4000:] if result.stdout else "",
            "error": result.stderr[-2000:] if result.stderr else "",
            "code": result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Command timed out (30s)"}), 408
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- Guard, permissions, engine, diagnostics, workspace ----------

@app.before_request
def _local_same_origin_only():
    """Only this app's own page may drive the API: blocks other sites, DNS rebinding and generated previews."""
    if request.path.startswith("/v1/") or request.path.startswith("/api/v1/"):
        return None
    if request.host.rsplit(":", 1)[0] not in ("127.0.0.1", "localhost"):
        return jsonify({"error": "Unknown host"}), 403
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    origin = request.headers.get("Origin")
    if origin and origin != request.host_url.rstrip("/"):
        return jsonify({"error": "Cross-origin request blocked"}), 403
    if request.path.startswith("/api/") and request.get_data() and not request.is_json:
        return jsonify({"error": "JSON body required"}), 415
    return None


@app.route("/api/permission-mode", methods=["GET", "POST"])
def api_permission_mode():
    cfg = load_config()
    if request.method == "POST":
        mode = (request.get_json(silent=True) or {}).get("mode")
        if mode not in permissions.MODES:
            return jsonify({"ok": False, "error": f"Unknown permission mode: {mode}"}), 400
        cfg["permission_mode"] = mode
        save_config(cfg)
    mode = permissions.normalize(cfg.get("permission_mode"))
    return jsonify({"ok": True, "mode": mode, "label": permissions.MODES[mode], "modes": permissions.MODES})


@app.route("/api/permissions")
def api_permissions():
    return jsonify(BROKER.pending())


@app.route("/api/permissions/<pid>", methods=["POST"])
def api_permission_answer(pid):
    decision = (request.get_json(silent=True) or {}).get("decision")
    if decision not in ("allow", "always", "deny"):
        return jsonify({"ok": False, "error": "decision must be allow, always or deny"}), 400
    if not BROKER.resolve(pid, decision):
        return jsonify({"ok": False, "error": "This request was already answered or has expired."}), 404
    return jsonify({"ok": True})


@app.route("/api/engine")
def api_engine():
    return jsonify(dict(ENGINE.state(), desktop=_engine_on()))


@app.route("/api/engine/show", methods=["POST"])
def api_engine_show():
    if not _engine_on():
        return jsonify({"ok": False, "error": "The arena.ai window exists only in the desktop app."}), 400
    ENGINE.show()
    return jsonify({"ok": True})


@app.route("/api/engine/hide", methods=["POST"])
def api_engine_hide():
    if _engine_on():
        ENGINE.close_pane()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    _stop.set()
    cancelled = BROKER.cancel_all()
    if _engine_on() and ENGINE.challenge == "recaptcha":
        ENGINE.cancel_check()
    return jsonify({"ok": True, "cancelled": cancelled})


@app.route("/api/doctor")
def api_doctor():
    """Check each outside contract the app relies on and explain failures in plain words."""
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": ok, "detail": detail})

    client = get_client()
    html = ""
    try:
        r = requests.get(contracts.ORIGIN, timeout=15, headers={"User-Agent": client.session.headers.get("User-Agent", "")})
        html = r.text
        add("arena.ai reachable", r.status_code == 200, f"HTTP {r.status_code}" if r.status_code == 200
            else contracts.classify_error(r.status_code, html[:4000])["message"])
    except requests.RequestException as e:
        add("arena.ai reachable", False, f"Network error: {e}")
    live = (ENGINE.page_site_key() if _engine_on() and ENGINE.ready() else None) or contracts.discover_site_keys(html).get("v3")
    if not live:
        add("reCAPTCHA key", None, "not found in the page; the engine falls back to the built-in key")
    else:
        add("reCAPTCHA key", True, "matches the built-in key" if live == contracts.KEYS["v3"]
            else "arena.ai uses a new key; the engine reads it from the page, so chats keep working")
    try:
        models = sync_models(force=False)
        add("Model catalog", bool(models), f"{len(models)} models" if models
            else "empty: arena.ai may have changed /nextjs-api/model-catalog")
    except Exception as e:
        add("Model catalog", False, str(e))
    st = ENGINE.state()
    if _engine_on():
        add("arena.ai engine", st["ready"], "ready" if st["ready"] else
            (f"waiting for a {st['challenge']} check: press Show arena.ai" if st["challenge"]
             else f"loading ({st['host'] or 'no page yet'})"))
    else:
        add("arena.ai engine", None, "off: run arena-ai.exe for in-app sign-in and human checks")
    if _signed_in_somewhere(client):
        user, err = _check_session(client, force=True)
        add("Session", bool(user), (user.get("email") or "guest session") if user else (err or "not signed in"))
    else:
        add("Session", False, "not signed in")
    ws = _workspace_dir()
    try:
        ws.mkdir(parents=True, exist_ok=True)
        probe = ws / ".arena-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("Workspace writable", True, str(ws))
    except OSError as e:
        add("Workspace writable", False, f"{ws}: {e}")
    add("Contract overrides", None if _overrides else True,
        ", ".join(_overrides) if _overrides else "none (built-in contracts)")
    return jsonify({"checks": checks, "permission_mode": _perm_mode()})


def _allowed_root(raw) -> Optional[Path]:
    try:
        p = Path(str(raw or "")).expanduser().resolve()
    except (OSError, ValueError):
        return None
    for base in (workspace.PROJECTS_DIR.resolve(), _workspace_dir().resolve()):
        if p == base or base in p.parents:
            return p
    return None


@app.route("/api/workspace")
def api_workspace():
    root = _workspace_dir()
    return jsonify({"workspace": str(root), "exists": root.is_dir(), "projects_dir": str(workspace.PROJECTS_DIR),
                    "projects": workspace.list_projects()})


@app.route("/api/workspace/set", methods=["POST"])
def api_workspace_set():
    raw = ((request.get_json(silent=True) or {}).get("path") or "").strip().strip('"')
    if not raw:
        return jsonify({"ok": False, "error": "No folder given"}), 400
    root = Path(raw).expanduser()
    if not root.is_absolute():
        return jsonify({"ok": False, "error": "Use a full folder path, like C:\\Users\\you\\project"}), 400
    root = root.resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        return jsonify({"ok": False, "error": "Pick a project folder, not a whole drive or your home folder."}), 400
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return jsonify({"ok": False, "error": f"Cannot use that folder: {e}"}), 400
    cfg = load_config()
    cfg["workspace_dir"] = str(root)
    save_config(cfg)
    return jsonify({"ok": True, "workspace": str(root)})


@app.route("/api/workspace/save", methods=["POST"])
def api_workspace_save():
    """The user pressed Save to disk on a code answer: that click is the approval."""
    data = request.get_json(silent=True) or {}
    key = (data.get("chat_id") or _current_chat_id, data.get("lane") or "a")
    item = _last_webdev.get(key)
    if not item:
        return jsonify({"ok": False, "error": "No code files from this chat to save. Send a Code message first."}), 404
    root = workspace.project_dir(key[0], item["title"], key[1], base=_chosen_ws())
    plan = workspace.plan_project(root, item["files"])
    written, deleted = workspace.apply_project(plan)
    return jsonify({"ok": True, "root": str(root), "written": written, "deleted": deleted,
                    "files": plan["files"], "preview": _preview_url(root)})


@app.route("/api/workspace/zip")
def api_workspace_zip():
    root = _allowed_root(request.args.get("path"))
    if not root or not root.is_dir():
        return jsonify({"error": "Only project folders can be zipped."}), 403
    return send_file(io.BytesIO(workspace.zip_dir(root)), mimetype="application/zip", as_attachment=True,
                     download_name=f"{root.parent.name}-{root.name}.zip")


@app.route("/api/workspace/open", methods=["POST"])
def api_workspace_open():
    root = _allowed_root((request.get_json(silent=True) or {}).get("path"))
    if not root or not root.is_dir():  # folders only: opening a file would run it
        return jsonify({"ok": False, "error": "Only project folders can be opened."}), 403
    if not hasattr(os, "startfile"):
        return jsonify({"ok": False, "error": "Opening folders works on Windows only.", "path": str(root)}), 400
    os.startfile(str(root))
    return jsonify({"ok": True})


@app.route("/api/media/save", methods=["POST"])
def api_media_save():
    """Download a generated image, video or audio file into the projects folder."""
    url = str((request.get_json(silent=True) or {}).get("url") or "")
    folder = workspace.PROJECTS_DIR / "media"
    try:
        if url.startswith("data:"):
            head, _, payload = url.partition(",")
            mime = head[5:].split(";")[0]
            blob, stem = base64.b64decode(payload), "media"
        else:
            u = urllib.parse.urlparse(url)
            host = (u.hostname or "").lower()
            if u.scheme != "https" or not host or host == "localhost" or host.startswith(("127.", "10.", "192.168.", "169.254.")):
                return jsonify({"ok": False, "error": "Only https media links can be saved."}), 400
            r = requests.get(url, timeout=60, stream=True)
            r.raise_for_status()
            blob = b""
            for chunk in r.iter_content(1 << 16):
                blob += chunk
                if len(blob) > 300 * 1024 * 1024:
                    return jsonify({"ok": False, "error": "File is larger than 300 MB."}), 413
            mime = r.headers.get("Content-Type", "").split(";")[0]
            stem = Path(u.path).stem or "media"
    except (requests.RequestException, ValueError) as e:
        return jsonify({"ok": False, "error": f"Download failed: {e}"}), 502
    ext = mimetypes.guess_extension(mime) or Path(urllib.parse.urlparse(url).path).suffix or ".bin"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{workspace.slug(stem)}-{uuid.uuid4().hex[:6]}{ext}"
    target.write_bytes(blob)
    return jsonify({"ok": True, "path": str(target), "folder": str(folder)})


def run_server(port: int = 5000, open_browser: bool = True):
    """Start the Flask server and optionally open browser."""
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
