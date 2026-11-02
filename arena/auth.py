"""
Authentication and cookie management for Arena CLI.
Supports Brave, Edge, Chrome, clipboard detection, and smart cookie parsing.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import winreg
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from rich.panel import Panel
from arena.console import con
from arena.config import save_cookie, get_cookie, load_config, save_config, UserAbort


def detect_installed_browsers() -> Dict[str, str]:
    """
    Detect all installed browsers on Windows.
    Returns dict mapping friendly name -> executable path.
    """
    candidates = {
        "Brave": [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ],
        "Microsoft Edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "Google Chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        "Mozilla Firefox": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
        "Opera": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera\launcher.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera GX\launcher.exe"),
        ],
        "Vivaldi": [
            os.path.expandvars(r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe"),
            r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
        ],
    }

    found: Dict[str, str] = {}
    for name, paths in candidates.items():
        for p in paths:
            if os.path.isfile(p):
                found[name] = p
                break

    # Also check Windows App Paths registry
    reg_keys = [
        ("Brave", "brave.exe"),
        ("Microsoft Edge", "msedge.exe"),
        ("Google Chrome", "chrome.exe"),
        ("Mozilla Firefox", "firefox.exe"),
    ]
    for b_name, exe in reg_keys:
        if b_name not in found:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if os.path.isfile(val):
                        found[b_name] = val
            except Exception:
                pass

    return found


def parse_cookie_input(raw: str) -> Tuple[str, Dict[str, str], Optional[Dict[str, Any]]]:
    """
    Parse cookie string from any input format:
    1. Raw cookie header: 'name=val; name2=val2'
    2. DevTools Application tab copy (tab-separated lines):
       'arena-auth-prod-v1.0\tbase64-...\tarena.ai\t/ ...'
    3. JSON dictionary: '{"name": "value"}'
    
    Returns:
      (normalized_cookie_header, cookie_dict, decoded_user_info)
    """
    raw = raw.strip()
    cookies: Dict[str, str] = {}

    # Format 2: Tab-separated table lines from Chrome/Brave/Edge DevTools
    lines = raw.splitlines()
    if any("\t" in line for line in lines):
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 2:
                name = parts[0].strip()
                val = parts[1].strip()
                if name and val:
                    cookies[name] = val

    # Format 3: JSON
    elif raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                cookies = {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass

    # Format 1: Standard 'name=value; name2=value2' or individual lines
    if not cookies:
        # Split on semicolons or newlines
        items = re.split(r"[;\r\n]+", raw)
        for item in items:
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                cookies[k.strip()] = v.strip()
            elif item.startswith("base64-"):
                cookies["arena-auth-prod-v1.0"] = item

    # Normalize cookie header
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

    # Decode Supabase session if present to verify user info
    user_info = None
    v0 = cookies.get("arena-auth-prod-v1.0", "")
    v1 = cookies.get("arena-auth-prod-v1.1", "")
    if v0:
        try:
            combined = v0.replace("base64-", "") + v1
            # Add padding
            combined += "=" * ((4 - len(combined) % 4) % 4)
            decoded_text = base64.b64decode(combined).decode("utf-8", errors="ignore")
            session_data = json.loads(decoded_text)
            user_obj = session_data.get("user", {})
            meta = user_obj.get("user_metadata", {})
            user_info = {
                "email": user_obj.get("email") or session_data.get("email"),
                "id": user_obj.get("id"),
                "full_name": meta.get("full_name") or meta.get("name"),
                "avatar_url": meta.get("avatar_url") or meta.get("picture"),
                "expires_at": session_data.get("expires_at"),
                "access_token": session_data.get("access_token"),
            }
        except Exception:
            pass

    return cookie_str, cookies, user_info


def get_clipboard_text() -> str:
    """Safely get text from Windows clipboard via PowerShell."""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return (res.stdout or "").strip()
    except Exception:
        return ""


def check_clipboard_for_cookies() -> Optional[Tuple[str, Optional[Dict[str, Any]]]]:
    """Inspect clipboard for valid Arena cookies."""
    text = get_clipboard_text()
    if not text:
        return None
    if "arena-auth-prod" in text or "base64-eyJh" in text or "arena.ai" in text:
        header, c_dict, user_info = parse_cookie_input(text)
        if "arena-auth-prod-v1.0" in c_dict or any("auth" in k for k in c_dict):
            return header, user_info
    return None


def launch_browser_cdp(browser_path: str, port: int = 9222) -> Optional[subprocess.Popen]:
    """
    Launch browser with remote debugging enabled.
    Uses a persistent profile to maintain Cloudflare clearance across sessions.
    """
    from arena.config import CONFIG_DIR
    profile_dir = CONFIG_DIR / "cdp_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={str(profile_dir)}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "https://arena.ai",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc
    except Exception as e:
        con.print(f"[red]Failed to launch {browser_path}: {e}[/red]")
        return None
