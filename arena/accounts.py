"""Multiple arena.ai accounts: saved sessions, active account and cookie-file compatibility.

The app still keeps the active session in ~/.arena-cli/cookies.txt (the engine imports it),
but every account is also kept in accounts.json so the user can switch without pasting a
cookie again. Cookies never leave the machine.
"""

import functools
import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from arena.auth import parse_cookie_input
from arena.config import CONFIG_DIR, COOKIE_FILE, ensure_config_dir

ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
AUTH_PREFIX = "arena-auth-prod-v1"
_LOCK = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _account_id(meta: Dict[str, Any]) -> str:
    """Stable across re-adds, so a removed account gets its chats back when it returns."""
    key = meta.get("user_id") or (meta.get("email") or "").casefold()
    if key:
        return "acct-" + hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]
    return uuid.uuid4().hex[:12]


def _read() -> Dict[str, Any]:
    ensure_config_dir()
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("accounts"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"active": None, "accounts": []}


def _write(data: Dict[str, Any]) -> None:
    ensure_config_dir()
    ACCOUNTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(ACCOUNTS_FILE, 0o600)
    except OSError:
        pass


def _sync_cookie_file(cookie: Optional[str]) -> None:
    try:
        if cookie:
            COOKIE_FILE.write_text(cookie.strip(), encoding="utf-8")
        else:
            COOKIE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _public(acc: Dict[str, Any], active_id: Optional[str]) -> Dict[str, Any]:
    return {
        "id": acc.get("id"),
        "email": acc.get("email") or "",
        "name": acc.get("full_name") or "",
        "avatar_url": acc.get("avatar_url") or "",
        "active": acc.get("id") == active_id,
    }


def _meta(cookie: str, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _, _, info = parse_cookie_input(cookie or "")
    info = info or {}
    user = user or {}
    return {
        "email": user.get("email") or info.get("email") or "",
        "user_id": str(user.get("id") or info.get("id") or ""),
        "full_name": user.get("name") or user.get("full_name") or info.get("full_name") or "",
        "avatar_url": user.get("avatarUrl") or user.get("avatar_url") or info.get("avatar_url") or "",
    }


@_locked
def ensure_seeded() -> Dict[str, Any]:
    """Load the store; on first run, adopt the existing single-account cookie file."""
    data = _read()
    accounts = data["accounts"]
    if not accounts:
        try:
            cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            cookie = ""
        if cookie and AUTH_PREFIX in cookie:
            meta = _meta(cookie)
            acc = {"id": _account_id(meta), "cookie": cookie, "added_at": _now(), **meta}
            data = {"active": acc["id"], "accounts": [acc]}
            _write(data)
            _sync_cookie_file(cookie)
            return data
    active = data.get("active")
    if accounts and not any(a.get("id") == active for a in accounts):
        data["active"] = accounts[0].get("id")
        _write(data)
        _sync_cookie_file(accounts[0].get("cookie"))
    return data


def _find(data: Dict[str, Any], account_id: str) -> Optional[Dict[str, Any]]:
    return next((a for a in data["accounts"] if a.get("id") == account_id), None)


def all_accounts() -> List[Dict[str, Any]]:
    return list(ensure_seeded()["accounts"])


def list_accounts() -> List[Dict[str, Any]]:
    data = ensure_seeded()
    active = data.get("active")
    return [_public(a, active) for a in data["accounts"]]


def active_id() -> Optional[str]:
    return ensure_seeded().get("active")


def first_id() -> Optional[str]:
    accounts = ensure_seeded()["accounts"]
    return accounts[0].get("id") if accounts else None


def active_account() -> Optional[Dict[str, Any]]:
    data = ensure_seeded()
    return _find(data, data.get("active") or "")


def get(account_id: str) -> Optional[Dict[str, Any]]:
    return _find(ensure_seeded(), account_id)


@_locked
def active_cookie() -> Optional[str]:
    acc = active_account()
    cookie = (acc or {}).get("cookie")
    if cookie:
        _sync_cookie_file(cookie)
    return cookie


@_locked
def remember(cookie: str, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add or update an account from a validated session and make it active."""
    cookie = (cookie or "").strip()
    data = ensure_seeded()
    meta = _meta(cookie, user)
    match = None
    for acc in data["accounts"]:
        same_email = meta["email"] and acc.get("email", "").casefold() == meta["email"].casefold()
        same_user = meta["user_id"] and acc.get("user_id") == meta["user_id"]
        same_cookie = cookie and acc.get("cookie") == cookie
        if same_email or same_user or same_cookie:
            match = acc
            break
    if match is None:
        match = {"id": _account_id(meta), "cookie": cookie, "added_at": _now(), **meta}
        data["accounts"].append(match)
    else:
        match.update(cookie=cookie, **{k: v for k, v in meta.items() if v})
    data["active"] = match["id"]
    _write(data)
    _sync_cookie_file(cookie)
    return _public(match, data["active"])


@_locked
def update_active(cookie: str, user: Optional[Dict[str, Any]] = None) -> None:
    """Refresh the active account after Supabase rotates its cookies."""
    data = ensure_seeded()
    acc = _find(data, data.get("active") or "")
    if not acc:
        if cookie:
            remember(cookie, user)
        return
    meta = _meta(cookie, user)
    acc["cookie"] = cookie
    for k, v in meta.items():
        if v:
            acc[k] = v
    _write(data)
    _sync_cookie_file(cookie)


@_locked
def set_active(account_id: str) -> Optional[Dict[str, Any]]:
    data = ensure_seeded()
    acc = _find(data, account_id)
    if not acc:
        return None
    data["active"] = account_id
    _write(data)
    _sync_cookie_file(acc.get("cookie"))
    return _public(acc, account_id)


@_locked
def remove(account_id: str) -> Optional[Dict[str, Any]]:
    """Forget one account. Returns the new active account (or None)."""
    data = ensure_seeded()
    acc = _find(data, account_id)
    if not acc:
        return None
    data["accounts"] = [a for a in data["accounts"] if a.get("id") != account_id]
    if data.get("active") == account_id:
        data["active"] = data["accounts"][0].get("id") if data["accounts"] else None
    _write(data)
    new_active = _find(data, data.get("active") or "")
    _sync_cookie_file(new_active.get("cookie") if new_active else None)
    return _public(new_active, data.get("active")) if new_active else None
