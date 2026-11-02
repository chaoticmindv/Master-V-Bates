"""
Dynamic model catalog management, caching, multi-color rendering, and modality routing.
Supports 400+ dynamic models from arena.ai with no static hardcoding.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import requests
from rich.panel import Panel
from rich.table import Table

from arena.console import con
from arena.config import BASE_URL, API_PREFIX, CONFIG_DIR, load_config, save_config

CACHE_FILE = CONFIG_DIR / "models_cache.json"
CACHE_TTL_SECONDS = 300  # models are added/removed often; revalidate every 5 minutes

# Special Router Model ID
MAX_ROUTER_ID = "019b24bb-5caf-71c3-b854-37d0c7086f21"

# Distinct primary brand colors
ORG_COLOR_MAP = {
    "openai": "#10B981",       # Emerald Green
    "anthropic": "#F97316",    # Claude Coral / Orange
    "google": "#38BDF8",       # Sky Blue
    "xai": "#D946EF",          # Grok Magenta / Purple
    "alibaba": "#F59E0B",      # Qwen Amber / Gold
    "meta": "#06B6D4",         # Cyan
    "deepseek": "#3B82F6",     # Electric Blue
    "mistral": "#EF4444",      # Crimson Red
    "zai": "#8B5CF6",          # Violet
    "stepfun": "#EC4899",      # Pink
    "minimax": "#14B8A6",      # Teal
    "cohere": "#F43F5E",       # Rose
    "nvidia": "#76B900",       # Nvidia Green
    "boss-bandit": "#EAB308",  # Router Gold
}

# Dynamic color wheel for any newly introduced organizations
DYNAMIC_COLOR_PALETTE = [
    "#34D399", "#A78BFA", "#F472B6", "#FB923C", "#4ADE80",
    "#22D3EE", "#E879F9", "#FACC15", "#818CF8", "#F87171"
]

MODALITIES = {
    "chat": {
        "label": "Text / Chat",
        "badge": "[TEXT]",
        "arena": "text",
        "api_modality": "chat",
        "desc": "General reasoning, multi-turn coding and conversation",
    },
    "webdev": {
        "label": "Code / Webdev",
        "badge": "[CODE]",
        "arena": "code",
        "api_modality": "webdev",
        "desc": "Builds and deploys interactive web applications live on Arena",
    },
    "search": {
        "label": "Search / Grounding",
        "badge": "[SEARCH]",
        "arena": "search",
        "api_modality": "search",
        "desc": "Grounded search with live web sources and citations",
    },
    "image": {
        "label": "Image Generation",
        "badge": "[IMAGE]",
        "arena": "text-to-image",
        "api_modality": "image",
        "desc": "High quality image synthesis from text briefs",
    },
    "video": {
        "label": "Video Generation",
        "badge": "[VIDEO]",
        "arena": "text-to-video",
        "api_modality": "video",
        "desc": "Short video clips generated from a text brief",
    },
}


def get_org_color(org_name: str) -> str:
    """Return distinct color for known org or dynamically generate one from palette."""
    clean = (org_name or "unknown").strip().lower()
    if clean in ORG_COLOR_MAP:
        return ORG_COLOR_MAP[clean]
    idx = int(hashlib.md5(clean.encode()).hexdigest(), 16) % len(DYNAMIC_COLOR_PALETTE)
    return DYNAMIC_COLOR_PALETTE[idx]


def sync_models(cookie: Optional[str] = None, force: bool = False) -> List[Dict[str, Any]]:
    """
    Dynamically fetch and update the model catalog from arena.ai.
    Uses disk caching with TTL; force=True bypasses cache.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not force and CACHE_FILE.exists():
        try:
            cached_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            cached_time = cached_data.get("_cached_at", 0)
            if (time.time() - cached_time) < CACHE_TTL_SECONDS:
                return cached_data.get("models", [])
        except Exception:
            pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
    }
    if cookie:
        headers["Cookie"] = cookie

    try:
        r = requests.get(f"{BASE_URL}{API_PREFIX}/model-catalog", headers=headers, timeout=12)
        r.raise_for_status()
        raw_catalog = r.json()
    except Exception:
        if CACHE_FILE.exists():
            try:
                cached_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                return cached_data.get("models", [])
            except Exception:
                pass
        return []

    models: List[Dict[str, Any]] = []
    seen = set()

    for arena_block in raw_catalog:
        arena_name = arena_block.get("arena", "text")
        for m in arena_block.get("models", []):
            m_id = m.get("id")
            if not m_id:
                continue
            key = (m_id, arena_name)
            if key not in seen:
                seen.add(key)
                display_name = m.get("displayName") or m.get("publicName") or m_id
                public_name = m.get("publicName") or display_name
                org = m.get("organization", "community")
                provider = m.get("provider", "")
                rank = m.get("rank")
                user_selectable = bool(m.get("userSelectable", True))
                capabilities = m.get("capabilities", {})

                # Tag router model
                is_router = (m_id == MAX_ROUTER_ID or display_name.lower() == "max" or org == "boss-bandit")

                models.append({
                    "id": m_id,
                    "name": display_name,
                    "public_name": public_name,
                    "org": org,
                    "provider": provider,
                    "arena": arena_name,
                    "rank": rank,
                    "user_selectable": user_selectable,
                    "capabilities": capabilities,
                    "is_router": is_router,
                })

    try:
        CACHE_FILE.write_text(
            json.dumps({
                "_cached_at": time.time(),
                "total": len(models),
                "models": models,
            }, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass

    return models


def fetch_models(cookie: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch cached or live models."""
    return sync_models(cookie=cookie, force=False)


def get_popular_models(all_models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort text/code models by performance rank for quick selection."""
    selectable = [m for m in all_models if m.get("arena") in ("text", "code") and m.get("user_selectable")]
    return sorted(selectable, key=lambda x: (x.get("rank") is None, x.get("rank", 9999), x.get("name", "")))


def get_models_for_modality(all_models: List[Dict[str, Any]], modality: str = "chat") -> List[Dict[str, Any]]:
    """Filter models that support a given modality (chat, webdev, search, image)."""
    mod_info = MODALITIES.get(modality, MODALITIES["chat"])
    target_arena = mod_info["arena"]

    matches = []
    seen_ids = set()

    # Always ensure Max Router is included if present
    for m in all_models:
        if m.get("is_router") and m["id"] not in seen_ids:
            seen_ids.add(m["id"])
            matches.append(m)

    for m in all_models:
        if not m.get("user_selectable"):
            continue
        if m["id"] in seen_ids:
            continue
        # Direct arena match
        if m.get("arena") == target_arena:
            seen_ids.add(m["id"])
            matches.append(m)
        # Search capabilities check
        elif modality == "search" and m.get("capabilities", {}).get("outputCapabilities", {}).get("search"):
            seen_ids.add(m["id"])
            matches.append(m)
        # Webdev / code capabilities check
        elif modality == "webdev" and m.get("capabilities", {}).get("outputCapabilities", {}).get("web"):
            seen_ids.add(m["id"])
            matches.append(m)
        # Video capability check (catalog usually tags these as text-to-video already)
        elif modality == "video" and m.get("capabilities", {}).get("outputCapabilities", {}).get("video"):
            seen_ids.add(m["id"])
            matches.append(m)

    # Sort: Router first, then by rank, then name
    return sorted(matches, key=lambda x: (not x.get("is_router"), x.get("rank") is None, x.get("rank", 9999), x.get("name", "")))


def check_model_capability(model: Dict[str, Any], modality: str) -> bool:
    """Verify if a selected model can execute the requested modality."""
    if model.get("is_router") or model.get("id") == MAX_ROUTER_ID:
        return True  # Max Router handles all modalities

    target_arena = MODALITIES.get(modality, {}).get("arena", "text")
    if model.get("arena") == target_arena:
        return True

    caps = model.get("capabilities", {}).get("outputCapabilities", {})
    if modality == "search" and caps.get("search"):
        return True
    if modality == "webdev" and caps.get("web"):
        return True
    if modality == "image" and ("image" in caps or model.get("arena") == "text-to-image"):
        return True
    if modality == "video" and ("video" in caps or model.get("arena") == "text-to-video"):
        return True

    return False


def display_available_models(
    models: List[Dict[str, Any]],
    active_id: Optional[str] = None,
    modality: str = "chat",
    max_display: int = 40
) -> None:
    """
    Render a rich, color-coded display of available models for a specific modality.
    """
    mod_info = MODALITIES.get(modality, MODALITIES["chat"])
    filtered = get_models_for_modality(models, modality)

    con.print(Panel(
        f"[bold #299BFF]Available Models for {mod_info['label']}[/bold #299BFF] ({len(filtered)} models)\n"
        f"[dim]{mod_info['desc']} · Colored by Organization[/dim]",
        border_style="#299BFF",
        width=85,
    ))

    table = Table(show_lines=False, header_style="bold white", width=85)
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Rank", style="bold yellow", width=6, justify="center")
    table.add_column("Model Name", style="bold white", width=32)
    table.add_column("Organization", width=16)
    table.add_column("Capabilities", style="dim", width=16)

    for i, m in enumerate(filtered[:max_display], 1):
        org = m.get("org", "community")
        org_color = get_org_color(org)
        org_styled = f"[{org_color}]{org.upper()}[/{org_color}]"

        is_active = (m["id"] == active_id)
        marker = " [bold #10B981]★ active[/bold #10B981]" if is_active else ""
        
        if m.get("is_router"):
            rank_str = "ROUTER"
            name_display = f"[bold #EAB308]⚡ {m['name']} (Auto-Router)[/bold #EAB308]{marker}"
            caps_str = "All Modalities"
        else:
            rank_str = f"#{m['rank']}" if m.get("rank") is not None else "-"
            name_display = f"[{org_color}]{m['name']}[/{org_color}]{marker}"
            caps_list = []
            c = m.get("capabilities", {}).get("outputCapabilities", {})
            if c.get("web"): caps_list.append("web")
            if c.get("search"): caps_list.append("search")
            if c.get("text"): caps_list.append("text")
            caps_str = ", ".join(caps_list) if caps_list else m.get("arena", "text")

        table.add_row(
            str(i),
            rank_str,
            name_display,
            org_styled,
            caps_str,
        )

    con.print(table)
    if len(filtered) > max_display:
        con.print(f"  [dim]+ {len(filtered) - max_display} more models available for this modality.[/dim]\n")
def format_models_table(models: List[Dict[str, Any]], active_id: Optional[str] = None, title: str = "Models") -> Table:
    """Render models into a clean Rich table with dynamic org colors."""
    t = Table(title=title, show_lines=False, header_style="bold cyan", width=85)
    t.add_column("#", style="dim", width=4, justify="right")
    t.add_column("Rank", style="bold yellow", width=6, justify="center")
    t.add_column("Model Name", style="bold white", width=32)
    t.add_column("Organization", width=16)
    t.add_column("Arena", style="dim", width=10)

    for i, m in enumerate(models, 1):
        org = m.get("org", "community")
        org_color = get_org_color(org)
        org_styled = f"[{org_color}]{org.upper()}[/{org_color}]"
        marker = " [bold #10B981]★ active[/bold #10B981]" if m["id"] == active_id else ""
        rank_str = f"#{m['rank']}" if m.get("rank") is not None else "-"
        t.add_row(str(i), rank_str, f"[{org_color}]{m['name']}[/{org_color}]{marker}", org_styled, m.get("arena", "text"))

    return t
