"""
Configuration, paths, and persistent settings for Arena CLI.
"""

import json
import os
import atexit
from pathlib import Path
from typing import Dict, Any, Optional

CONFIG_DIR = Path.home() / ".arena-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
COOKIE_FILE = CONFIG_DIR / "cookies.txt"
HIST_FILE = CONFIG_DIR / "history.txt"
PID_FILE = CONFIG_DIR / "arena.pid"
CHATS_DIR = CONFIG_DIR / "chats"

BASE_URL = "https://arena.ai"
API_PREFIX = "/nextjs-api"


class UserAbort(Exception):
    """Raised when user presses Esc or Ctrl-C to cancel/go back."""
    pass


def ensure_config_dir() -> Path:
    """Ensure ~/.arena-cli exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def load_config() -> Dict[str, Any]:
    """Load configuration from disk."""
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: Dict[str, Any]) -> None:
    """Save configuration to disk."""
    ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_cookie() -> Optional[str]:
    """Retrieve the stored cookie string."""
    try:
        if COOKIE_FILE.exists():
            val = COOKIE_FILE.read_text(encoding="utf-8").strip()
            return val if val else None
    except Exception:
        pass
    return None


def save_cookie(val: str) -> None:
    """Save cookie string to disk."""
    ensure_config_dir()
    COOKIE_FILE.write_text(val.strip(), encoding="utf-8")


def clear_cookie() -> None:
    """Remove saved cookie file."""
    try:
        COOKIE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def write_pid() -> None:
    """Record current process PID."""
    ensure_config_dir()
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def cleanup_pid() -> None:
    """Remove PID file on clean exit."""
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


atexit.register(cleanup_pid)


DEFAULT_PERSONA = (
    "You are a helpful AI coding assistant powered by Arena.ai. "
    "You write clean, efficient code and explain your reasoning clearly. "
    "When editing files, you use the available tools (read_file, write_file, edit_file). "
    "Be concise and direct."
)

DEFAULT_SETTINGS = {
    "persona": DEFAULT_PERSONA,
    "theme": "arena",  # arena | dark | light
    "show_reasoning": False,
    "auto_copy": True,
    "max_history": 20,
    "cdp_port": 9222,
}


def get_settings() -> Dict[str, Any]:
    """Get merged settings (defaults + user overrides)."""
    cfg = load_config()
    settings = dict(DEFAULT_SETTINGS)
    if "settings" in cfg:
        settings.update(cfg["settings"])
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings to config."""
    cfg = load_config()
    cfg["settings"] = settings
    save_config(cfg)

