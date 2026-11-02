"""
Main command implementations and CLI entry point for Arena Code.
"""

import os
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any

from rich.panel import Panel
from rich.table import Table

from arena.console import con
from arena.config import (
    get_cookie, save_cookie, load_config, save_config,
    write_pid, cleanup_pid, UserAbort
)
from arena.auth import (
    detect_installed_browsers, parse_cookie_input,
    check_clipboard_for_cookies, launch_browser_cdp
)
from arena.models import (
    sync_models, fetch_models, get_popular_models,
    format_models_table, display_available_models,
    get_models_for_modality, check_model_capability,
    MODALITIES, MAX_ROUTER_ID
)
from arena.api import ArenaClient, _cdp_find_arena_tab
from arena.tools import ToolRegistry, parse_tool_calls
from arena.ui import (
    print_banner, render_markdown, print_tool_call, print_tool_result,
    print_deployment_preview, print_search_sources, get_chat_input
)
from arena.menu import show_main_menu


def print_cli_help() -> None:
    """Print command-line usage and available subcommands."""
    con.print(Panel(
        "[bold #F4F0EB]Arena Code CLI — Free AI Coding Assistant[/bold #F4F0EB]\n"
        "[dim]Powered by arena.ai · 400+ Top Models (GPT-5, Claude, Grok, DeepSeek)[/dim]\n\n"
        "[bold white]Commands:[/bold white]\n"
        "  [bold #299BFF]start.bat[/bold #299BFF]                 Launch interactive arrow-key selector\n"
        "  [bold #299BFF]arena.bat[/bold #299BFF]                 Launch interactive arrow-key menu\n"
        "  [bold #299BFF]arena.bat chat[/bold #299BFF]            Start AI coding session with tools\n"
        "  [bold #299BFF]arena.bat mode [name][/bold #299BFF]     Switch modality (chat, webdev, search, image, router)\n"
        "  [bold #299BFF]arena.bat login[/bold #299BFF]           Log in via browser (Brave, Edge, Chrome) or clipboard\n"
        "  [bold #299BFF]arena.bat models[/bold #299BFF]          Browse 400+ live models across 6 arenas\n"
        "  [bold #299BFF]arena.bat set-model[/bold #299BFF]       Change active model\n"
        "  [bold #299BFF]arena.bat mcp[/bold #299BFF]             Inspect local tools and Brave Search MCP server\n"
        "  [bold #299BFF]arena.bat ask \"query\"[/bold #299BFF]     Ask a single question and stream the answer\n\n"
        "[bold #F4F0EB]Modalities:[/bold #F4F0EB]\n"
        "  [bold #10B981]chat[/bold #10B981]      General reasoning, coding, tool execution\n"
        "  [bold #10B981]webdev[/bold #10B981]    Builds interactive web apps and deploys live preview URLs\n"
        "  [bold #10B981]search[/bold #10B981]    Real-time web search with source citations\n"
        "  [bold #10B981]image[/bold #10B981]     Text-to-image synthesis\n"
        "  [bold #10B981]router[/bold #10B981]    Max Auto-Router (dynamically routes to highest-ranked model)",
        title="Arena CLI Help",
        border_style="#299BFF",
        width=75
    ))


def read_cookie_input(prompt_label: str = "  Cookie> ") -> str:
    """Read cookie input supporting both clipboard auto-capture and multi-line paste."""
    # Check clipboard first
    clip = check_clipboard_for_cookies()
    if clip:
        return clip[0]

    lines = []
    con.print("  [dim]Enter/paste cookie lines below (hit Enter on an empty line when done):[/dim]")
    try:
        first = input(prompt_label).strip()
        if first:
            lines.append(first)
        while True:
            extra = input().strip()
            if not extra:
                break
            lines.append(extra)
    except (EOFError, KeyboardInterrupt):
        pass
    return "\n".join(lines).strip()


def cmd_login() -> None:
    """Enhanced login supporting Brave, Edge, Chrome, clipboard, and manual paste."""
    con.print(Panel("[bold #F4F0EB]Arena CLI Authentication[/bold #F4F0EB]", style="#299BFF"))

    # Helper to sync and display models after any successful login
    def _on_login_success(c_val: str, u_data: Optional[Dict[str, Any]] = None):
        save_cookie(c_val)
        email_str = f" for {u_data['email']}" if u_data and u_data.get("email") else ""
        con.print(f"\n  [bold #10B981]✓ Authenticated successfully{email_str}![/bold #10B981]")
        con.print("  [dim]Synchronizing live model catalog from arena.ai...[/dim]")
        m_list = sync_models(c_val, force=True)
        con.print(f"  [bold #10B981]✓ Catalog updated: {len(m_list)} live models across 6 arenas[/bold #10B981]\n")
        cfg_cur = load_config()
        display_available_models(m_list, active_id=cfg_cur.get("model_id"), max_display=30)

        # Launch CDP browser for reCAPTCHA (needed for chat to work)
        from arena.api import _cdp_find_arena_tab
        if not _cdp_find_arena_tab():
            con.print("\n  [bold #299BFF]Launching CDP browser for chat reliability...[/bold #299BFF]")
            browsers = detect_installed_browsers()
            browser_path = None
            for name in ("Brave", "Google Chrome", "Microsoft Edge"):
                if name in browsers:
                    browser_path = browsers[name]
                    break
            if browser_path:
                proc = launch_browser_cdp(browser_path, 9222)
                if proc:
                    import time as _t
                    _t.sleep(3)
                    con.print(f"  [bold #10B981]✓ CDP browser launched on port 9222[/bold #10B981]")
                else:
                    con.print("  [dim yellow]Could not launch CDP browser. Chat may require manual browser setup.[/dim yellow]")

    # 1. Check clipboard first for instant zero-friction login
    clip_result = check_clipboard_for_cookies()
    if clip_result:
        cookie_str, u_info = clip_result
        email_str = f" ({u_info['email']})" if u_info and u_info.get("email") else ""
        con.print(f"  [bold #10B981]✓ Found Arena cookies in your clipboard!{email_str}[/bold #10B981]")
        con.print("  Press [bold green]Enter[/bold green] to use clipboard cookies, or type [bold]n[/bold] to pick a browser:")
        try:
            choice = input("  > ").strip().lower()
            if choice not in ("n", "no"):
                _on_login_success(cookie_str, u_info)
                return
        except (EOFError, KeyboardInterrupt):
            con.print("\n  [dim]Cancelled.[/dim]")
            return

    # 2. Detect installed browsers
    browsers = detect_installed_browsers()
    con.print("\n  [bold white]Select how you want to log in:[/bold white]\n")

    options = []
    idx = 1
    # Prioritize Brave if present
    if "Brave" in browsers:
        options.append(("Brave", browsers["Brave"], f"[bold #10B981]Brave Browser[/bold #10B981] [dim](Recommended - already logged in)[/dim]"))
    for b_name, b_path in browsers.items():
        if b_name != "Brave":
            options.append((b_name, b_path, f"{b_name}"))

    for i, (_, _, label) in enumerate(options, 1):
        con.print(f"  [bold cyan]{i}[/bold cyan]  {label}")

    paste_idx = len(options) + 1
    con.print(f"  [bold cyan]{paste_idx}[/bold cyan]  Paste cookies manually (from DevTools Application tab)")
    con.print("  [dim]Esc or Ctrl+C to go back[/dim]\n")

    try:
        sel_str = input(f"  Choice [1-{paste_idx}]> ").strip()
        if not sel_str:
            return
        sel = int(sel_str)
    except (ValueError, EOFError, KeyboardInterrupt):
        con.print("  [dim]Cancelled.[/dim]")
        return

    cfg = load_config()

    if 1 <= sel <= len(options):
        b_name, b_path, _ = options[sel - 1]
        cfg["browser"] = b_name
        save_config(cfg)

        con.print(f"\n  Opening [bold cyan]https://arena.ai[/bold cyan] in {b_name}...")
        try:
            # Launch normal browser tab if already running or standard
            webbrowser.open("https://arena.ai")
        except Exception:
            pass

        con.print("\n  [bold #299BFF]Quick Cookie Grab:[/bold #299BFF]")
        con.print(f"  1. Go to your {b_name} window on [link=https://arena.ai]arena.ai[/link]")
        con.print("  2. Press [bold]F12[/bold] → Application tab → Cookies → [bold]https://arena.ai[/bold]")
        con.print("  3. Click any cookie and press [bold]Ctrl+A[/bold], then [bold]Ctrl+C[/bold] (or Console: copy(document.cookie))")
        con.print("  4. Come back here and hit [bold green]Enter[/bold green] (it will auto-read from clipboard!):\n")

        try:
            input("  Press Enter once copied... ")
            clip_res = check_clipboard_for_cookies()
            if clip_res:
                cookie_str, u_info = clip_res
                _on_login_success(cookie_str, u_info)
                return
            else:
                con.print("  [yellow]Clipboard did not contain arena cookies. Paste below directly:[/yellow]")
                raw_paste = read_cookie_input("  Cookie> ")
                if raw_paste:
                    c_str, _, u_info = parse_cookie_input(raw_paste)
                    _on_login_success(c_str, u_info)
        except (EOFError, KeyboardInterrupt):
            con.print("\n  [dim]Cancelled.[/dim]")
            return

    elif sel == paste_idx:
        con.print("\n  [bold]Paste your Arena cookies[/bold] (Supports raw header or tabbed DevTools copy):")
        try:
            raw_input_data = read_cookie_input("  Cookie> ")
            if not raw_input_data:
                con.print("  [dim]Empty input.[/dim]")
                return
            c_str, _, u_info = parse_cookie_input(raw_input_data)
            _on_login_success(c_str, u_info)
        except (EOFError, KeyboardInterrupt):
            con.print("\n  [dim]Cancelled.[/dim]")


def cmd_models() -> None:
    """Display catalog of available Arena models."""
    cookie = get_cookie()
    con.print("  [dim]Fetching live model catalog from arena.ai...[/dim]")
    models = sync_models(cookie, force=True)
    if not models:
        con.print("[red]Could not load models. Check connection.[/red]")
        return
    cfg = load_config()
    active_id = cfg.get("model_id")
    display_available_models(models, active_id=active_id, max_display=50)
    con.print("  [dim]Press Enter to continue...[/dim]")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass


def cmd_set_model() -> None:
    """Interactive model picker."""
    cookie = get_cookie()
    con.print("  [dim]Loading models...[/dim]")
    models = fetch_models(cookie)
    if not models:
        return

    cfg = load_config()
    active_id = cfg.get("model_id")
    popular = get_popular_models(models)

    table = format_models_table(popular[:25], active_id=active_id, title="Top Popular Models")
    con.print(table)
    con.print("  [dim]Enter number to select, or type search text (Esc to cancel):[/dim]")

    try:
        choice = input("\n  Model> ").strip()
    except (EOFError, KeyboardInterrupt):
        con.print("  [dim]Cancelled.[/dim]")
        return

    if not choice:
        return

    target = None
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(popular):
            target = popular[idx]
    else:
        matches = [m for m in models if choice.lower() in m["name"].lower() and m.get("arena") == "text"]
        if not matches:
            con.print(f"[red]No models match '{choice}'[/red]")
            return
        if len(matches) == 1:
            target = matches[0]
        else:
            con.print(f"  Multiple matches for '{choice}':")
            for i, m in enumerate(matches[:10], 1):
                con.print(f"  {i}. [bold green]{m['name']}[/bold green] ({m['org']})")
            try:
                sub_c = input("\n  Select number> ").strip()
                if sub_c.isdigit() and 1 <= int(sub_c) <= len(matches[:10]):
                    target = matches[int(sub_c) - 1]
            except (EOFError, KeyboardInterrupt):
                return

    if target:
        cfg["model_id"] = target["id"]
        cfg["model_name"] = target["name"]
        cfg["model_org"] = target["org"]
        save_config(cfg)
        con.print(f"  [bold #10B981]✓ Active model set to {target['name']} ({target['org']})[/bold #10B981]")


def cmd_mode() -> None:
    """Interactive modality switcher."""
    con.print(Panel(
        "[bold #299BFF]Select Modality / Capability Mode[/bold #299BFF]\n"
        "[dim]Arena.ai handles each modality differently with dedicated models & sandboxes[/dim]",
        border_style="#299BFF",
        width=75,
    ))
    con.print("  [bold cyan]1[/bold cyan]  [bold #10B981]Code / Webdev[/bold #10B981] — Builds and deploys live web preview sandboxes")
    con.print("  [bold cyan]2[/bold cyan]  [bold #38BDF8]Search / Grounding[/bold #38BDF8] — Real-time web search with live source citations")
    con.print("  [bold cyan]3[/bold cyan]  [bold #EC4899]Image Generation[/bold #EC4899] — AI image generation models")
    con.print("  [bold cyan]4[/bold cyan]  [bold white]Text / Chat[/bold white] — General multi-turn coding and conversation")
    con.print("  [bold cyan]5[/bold cyan]  [bold #EAB308]⚡ Max Router[/bold #EAB308] — Automatically routes each prompt to the top-ranking S-tier model\n")

    try:
        c = input("  Choice [1-5]> ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    cfg = load_config()
    if c == "1":
        cfg["modality"] = "webdev"
        con.print("  [bold #10B981]✓ Modality set to: Code / Webdev (Sandbox live preview enabled)[/bold #10B981]")
    elif c == "2":
        cfg["modality"] = "search"
        con.print("  [bold #38BDF8]✓ Modality set to: Search / Grounding (Live citations enabled)[/bold #38BDF8]")
    elif c == "3":
        cfg["modality"] = "image"
        con.print("  [bold #EC4899]✓ Modality set to: Image Generation[/bold #EC4899]")
    elif c == "4":
        cfg["modality"] = "chat"
        con.print("  [bold white]✓ Modality set to: Standard Text / Chat[/bold white]")
    elif c == "5":
        cfg["modality"] = "chat"
        cfg["model_id"] = MAX_ROUTER_ID
        cfg["model_name"] = "Max (Router)"
        con.print("  [bold #EAB308]⚡ Max Router activated! Prompts will route to the best model automatically.[/bold #EAB308]")
    save_config(cfg)


def cmd_mcp() -> None:
    """Display status of loaded MCP tools and multi-browser integration."""
    tools = ToolRegistry(os.getcwd())
    con.print(Panel("[bold #299BFF]MCP & Multi-Browser Integration Status[/bold #299BFF]", style="#299BFF"))
    
    con.print("  [bold cyan]Covered Browsers (6 Platforms):[/bold cyan]")
    from arena.auth import detect_installed_browsers
    installed = detect_installed_browsers()
    for b_name in ["Brave", "Google Chrome", "Microsoft Edge", "Mozilla Firefox", "Opera", "Vivaldi"]:
        if b_name in installed or any(b_name.lower() in k.lower() for k in installed):
            con.print(f"    • [bold #10B981]✓ {b_name}[/bold #10B981] (Installed & Available)")
        else:
            con.print(f"    • [dim]○ {b_name} (Not detected on system)[/dim]")

    con.print(f"\n  [bold cyan]Active Developer & Browser Tools ({len(tools.tools)}):[/bold cyan]")
    for t_name, t_obj in tools.tools.items():
        desc = t_obj.description or "Local tool"
        con.print(f"    • [bold white]{t_name:<24s}[/bold white] [dim]{desc}[/dim]")

    tools.shutdown()
    con.print("\n  [dim]Press Enter to continue...[/dim]")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass


def _show_settings_menu(settings: Dict[str, Any], save_fn, debug_ref) -> None:
    """Interactive arrow-key settings editor."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.styles import Style as PTStyle

    items = [
        ("theme", "Theme", ["arena", "dark", "light"]),
        ("show_reasoning", "Show Reasoning", [False, True]),
        ("auto_copy", "Auto Copy Response", [False, True]),
        ("max_history", "Max History Messages", list(range(5, 55, 5))),
        ("cdp_port", "CDP Browser Port", [9222, 9223, 9224, 9225]),
    ]
    sel = [0]
    changed = [False]

    def get_text():
        lines = []
        lines.append(("class:title", "  Settings\n\n"))
        lines.append(("class:dim", "  ↑↓ select · ←→ change value · Enter save · Esc cancel\n\n"))
        for i, (key, label, options) in enumerate(items):
            cur_val = settings.get(key, options[0])
            prefix = " ▸ " if i == sel[0] else "   "
            style = "class:sel" if i == sel[0] else "class:item"
            val_str = str(cur_val)
            if isinstance(cur_val, bool):
                val_str = "ON" if cur_val else "OFF"
            lines.append((style, f"{prefix}{label:<24s}"))
            lines.append(("class:val" if i == sel[0] else "class:dim", f" {val_str}\n"))
        lines.append(("", "\n"))
        persona_preview = settings.get("persona", "")[:60]
        lines.append(("class:dim", f"  Persona: {persona_preview}...\n"))
        lines.append(("class:dim", "  (use /persona <text> to change)\n"))
        return lines

    kb = KeyBindings()

    @kb.add("up")
    def _up(e):
        sel[0] = (sel[0] - 1) % len(items)

    @kb.add("down")
    def _down(e):
        sel[0] = (sel[0] + 1) % len(items)

    @kb.add("right")
    def _right(e):
        key, _, options = items[sel[0]]
        cur = settings.get(key, options[0])
        try:
            idx = options.index(cur)
        except ValueError:
            idx = 0
        settings[key] = options[(idx + 1) % len(options)]
        changed[0] = True

    @kb.add("left")
    def _left(e):
        key, _, options = items[sel[0]]
        cur = settings.get(key, options[0])
        try:
            idx = options.index(cur)
        except ValueError:
            idx = 0
        settings[key] = options[(idx - 1) % len(options)]
        changed[0] = True

    @kb.add("enter")
    def _enter(e):
        if changed[0]:
            save_fn(settings)
        e.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _esc(e):
        e.app.exit()

    style = PTStyle.from_dict({
        "title": "bold #299BFF",
        "dim": "#6B7280",
        "sel": "bold #10B981",
        "item": "#E5E7EB",
        "val": "bold #06B6D4",
    })

    app = Application(
        layout=Layout(HSplit([Window(FormattedTextControl(get_text), wrap_lines=False)])),
        key_bindings=kb, style=style, full_screen=False,
    )
    try:
        app.run()
        if changed[0]:
            con.print("[bold #10B981]Settings saved.[/bold #10B981]")
    except Exception:
        # Fallback: just show the panel
        con.print(Panel(
            f"Theme: {settings['theme']}\n"
            f"Show Reasoning: {settings['show_reasoning']}\n"
            f"Auto Copy: {settings['auto_copy']}\n"
            f"Max History: {settings['max_history']}\n"
            f"CDP Port: {settings['cdp_port']}\n"
            f"Persona: {settings.get('persona', '')[:80]}...\n\n"
            "[dim]Use /settings key=value to change (e.g. /settings theme=dark)[/dim]",
            title="[bold #299BFF]Settings[/bold #299BFF]",
            border_style="#299BFF", width=70,
        ))


def cmd_chat(initial_msg: Optional[str] = None) -> None:
    """Full-featured AI coding session modeled after Claude Code."""
    cookie = get_cookie()
    if not cookie:
        con.print("[yellow]No active session found. Running login first...[/yellow]")
        cmd_login()
        cookie = get_cookie()
        if not cookie:
            con.print("[red]Login required to start coding session.[/red]")
            return

    cfg = load_config()
    model_id = cfg.get("model_id")
    model_name = cfg.get("model_name", "gpt-5.1-high")
    active_browser = cfg.get("browser", "Brave")
    active_modality = cfg.get("modality", "chat")

    # Set default model if unset
    if not model_id:
        models = fetch_models(cookie)
        popular = get_popular_models(models)
        if popular:
            model_id = popular[0]["id"]
            model_name = popular[0]["name"]
            cfg["model_id"] = model_id
            cfg["model_name"] = model_name
            save_config(cfg)

    # Decode user info for banner
    _, _, u_info = parse_cookie_input(cookie)
    user_email = u_info.get("email") if u_info else None

    tools = ToolRegistry(os.getcwd())
    client = ArenaClient(cookie)
    client.active_modality = active_modality
    debug = "--debug" in sys.argv

    write_pid()
    print_banner(model_name, tools.cwd, browser=active_browser, user_email=user_email, modality=active_modality)

    if client.use_cdp:
        con.print("  [bold #10B981]CDP browser connected[/bold #10B981] [dim](reCAPTCHA + cookies via browser)[/dim]")
    else:
        con.print("  [dim yellow]No CDP browser detected. Launch browser with --remote-debugging-port=9222 for best reliability.[/dim yellow]")

    history = []
    sys_prompt = tools.get_system_prompt()

    try:
        while True:
            if initial_msg:
                user_input = initial_msg
                initial_msg = None
            else:
                try:
                    user_input = get_chat_input()
                except UserAbort:
                    con.print("\n[dim]Session paused. Returning to menu...[/dim]")
                    break

            if not user_input:
                continue

            # Slash commands
            if user_input.startswith("/"):
                parts = user_input.split(None, 1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd in ("/quit", "/exit", "/q"):
                    break
                elif cmd == "/help":
                    con.print(Panel(
                        "[bold cyan]/model NAME[/bold cyan]  — Switch active model\n"
                        "[bold cyan]/models[/bold cyan]      — Browse all 100+ free models\n"
                        "[bold cyan]/mode MODE[/bold cyan]   — Switch modality (chat/code/search/image)\n"
                        "[bold cyan]/settings[/bold cyan]    — View and change settings\n"
                        "[bold cyan]/persona[/bold cyan]     — Set custom AI persona / system prompt\n"
                        "[bold cyan]/new[/bold cyan]         — Start clean conversation session\n"
                        "[bold cyan]/clear[/bold cyan]       — Clear terminal screen\n"
                        "[bold cyan]/tools[/bold cyan]       — List active tools & MCP servers\n"
                        "[bold cyan]/cd PATH[/bold cyan]     — Change current working directory\n"
                        "[bold cyan]/debug[/bold cyan]       — Toggle raw stream debug logging\n"
                        "[bold cyan]/quit[/bold cyan]        — Exit to main menu",
                        title="Available Commands",
                        border_style="#299BFF",
                        width=60,
                    ))
                    continue
                elif cmd == "/settings":
                    from arena.config import get_settings, save_settings
                    s = get_settings()
                    if not arg:
                        _show_settings_menu(s, save_settings, debug)
                    else:
                        parts_s = arg.split("=", 1)
                        if len(parts_s) == 2:
                            key_s, val_s = parts_s[0].strip().lower(), parts_s[1].strip()
                            if key_s == "theme" and val_s in ("arena", "dark", "light"):
                                s["theme"] = val_s
                            elif key_s == "reasoning":
                                s["show_reasoning"] = val_s.lower() in ("true", "on", "1", "yes")
                                debug = s["show_reasoning"]
                            elif key_s == "autocopy":
                                s["auto_copy"] = val_s.lower() in ("true", "on", "1", "yes")
                            elif key_s == "history":
                                s["max_history"] = max(1, min(100, int(val_s)))
                            elif key_s == "cdp_port":
                                s["cdp_port"] = int(val_s)
                            else:
                                con.print(f"[dim]Unknown setting: {key_s}[/dim]")
                                continue
                            save_settings(s)
                            con.print(f"[bold #10B981]Setting {key_s} updated.[/bold #10B981]")
                        else:
                            con.print("[dim]Usage: /settings key=value (e.g. /settings theme=dark)[/dim]")
                    continue
                elif cmd == "/persona":
                    from arena.config import get_settings, save_settings
                    if arg:
                        s = get_settings()
                        s["persona"] = arg
                        save_settings(s)
                        sys_prompt = tools.get_system_prompt().replace(
                            "You are a helpful AI coding assistant",
                            arg[:500]
                        )
                        con.print(f"[bold #10B981]Persona updated.[/bold #10B981]")
                    else:
                        con.print("[dim]Usage: /persona <your custom system prompt>[/dim]")
                        con.print("[dim]Example: /persona You are a security expert who writes Python exploits[/dim]")
                    continue
                elif cmd in ("/mode", "/modality"):
                    clean_m = arg.lower().strip()
                    if clean_m in ("code", "webdev", "dev"):
                        client.active_modality = "webdev"
                        cfg["modality"] = "webdev"
                        con.print("[bold #10B981]✓ Switched to Code / Webdev mode (Builds & deploys live previews)[/bold #10B981]")
                    elif clean_m in ("search", "grounding", "web"):
                        client.active_modality = "search"
                        cfg["modality"] = "search"
                        con.print("[bold #10B981]✓ Switched to Search / Grounding mode (Live web citations)[/bold #10B981]")
                    elif clean_m in ("image", "img", "draw"):
                        client.active_modality = "image"
                        cfg["modality"] = "image"
                        con.print("[bold #10B981]✓ Switched to Image Generation mode[/bold #10B981]")
                    elif clean_m in ("router", "max"):
                        client.active_modality = "chat"
                        model_id = MAX_ROUTER_ID
                        model_name = "Max (Router)"
                        cfg["model_id"] = model_id
                        cfg["model_name"] = model_name
                        con.print("[bold #EAB308]⚡ Activated Max (Auto-Router: routes dynamically to best S-tier model)[/bold #EAB308]")
                    else:
                        client.active_modality = "chat"
                        cfg["modality"] = "chat"
                        con.print("[bold #10B981]✓ Switched to Standard Chat / Coding mode[/bold #10B981]")
                    save_config(cfg)
                    continue
                elif cmd == "/router":
                    model_id = MAX_ROUTER_ID
                    model_name = "Max (Router)"
                    cfg["model_id"] = model_id
                    cfg["model_name"] = model_name
                    save_config(cfg)
                    con.print("[bold #EAB308]⚡ Activated Max (Auto-Router: routes dynamically to best S-tier model)[/bold #EAB308]")
                    continue
                elif cmd == "/login":
                    cmd_login()
                    cookie = get_cookie()
                    if cookie:
                        client.set_cookie(cookie)
                        client.use_cdp = _cdp_find_arena_tab(client.cdp_port) is not None
                        if client.use_cdp:
                            from arena.api import inject_cookies_via_cdp
                            inject_cookies_via_cdp(cookie, client.cdp_port)
                            con.print("[bold #10B981]CDP browser reconnected.[/bold #10B981]")
                    continue
                elif cmd == "/models":
                    cmd_models()
                    continue
                elif cmd == "/clear":
                    os.system("cls" if os.name == "nt" else "clear")
                    print_banner(model_name, tools.cwd, browser=active_browser, user_email=user_email)
                    continue
                elif cmd == "/new":
                    client.reset_conversation()
                    history.clear()
                    con.print("[bold #10B981]✓ Started fresh conversation.[/bold #10B981]")
                    continue
                elif cmd == "/debug":
                    debug = not debug
                    con.print(f"Debug logging: [{'green' if debug else 'dim'}]{'ON' if debug else 'OFF'}[/{'green' if debug else 'dim'}]")
                    continue
                elif cmd == "/tools":
                    con.print(f"[bold cyan]Active Tools ({len(tools.tools)}):[/bold cyan]")
                    for t_name, t_obj in tools.tools.items():
                        con.print(f"  • [bold white]{t_name}[/bold white]: {t_obj.description}")
                    continue
                elif cmd == "/model":
                    if arg:
                        all_m = fetch_models(cookie)
                        hits = [m for m in all_m if arg.lower() in m["name"].lower()]
                        if hits:
                            m = hits[0]
                            model_id, model_name = m["id"], m["name"]
                            cfg["model_id"] = model_id
                            cfg["model_name"] = model_name
                            save_config(cfg)
                            con.print(f"[bold #10B981]✓ Switched model to {model_name}[/bold #10B981]")
                        else:
                            con.print(f"[red]No model matching '{arg}'[/red]")
                    else:
                        cmd_set_model()
                        cfg = load_config()
                        model_id = cfg.get("model_id", model_id)
                        model_name = cfg.get("model_name", model_name)
                    continue
                elif cmd == "/cd" and arg:
                    try:
                        os.chdir(arg)
                        tools.cwd = os.getcwd()
                        sys_prompt = tools.get_system_prompt()
                        con.print(f"[bold #10B981]✓ Working directory: {tools.cwd}[/bold #10B981]")
                    except Exception as e:
                        con.print(f"[red]Failed to change directory: {e}[/red]")
                    continue
                else:
                    con.print(f"[dim]Unknown command '{cmd}'. Type /help for list.[/dim]")
                    continue

            # Context assembly
            if not history:
                full_msg = f"[System]\n{sys_prompt}\n\n[User]\n{user_input}"
            else:
                ctx = "\n".join(f"[{h['role']}]\n{h['text']}" for h in history[-6:])
                full_msg = f"[System]\n{sys_prompt}\n\n{ctx}\n\n[User]\n{user_input}"

            history.append({"role": "User", "text": user_input})
            current_msg = full_msg

            # Agentic tool loop (up to 5 rounds)
            for tool_round in range(5):
                con.print(f"\n[bold #F4F0EB]{model_name}[/bold #F4F0EB]:", end=" ")

                full_text = ""

                # Try CDP browser first (handles reCAPTCHA + cookies automatically)
                if client.use_cdp:
                    text_result, err = client.send_chat_browser(model_id, current_msg)
                    if err:
                        if "No CDP browser" in str(err) or "No browser" in str(err):
                            client.use_cdp = False
                            con.print(f"\n[dim yellow]CDP browser disconnected — falling back to direct API.[/dim yellow]")
                        elif "429" in str(err) or "Rate limit" in str(err):
                            con.print(f"\n[yellow]{err}[/yellow]")
                            break
                        elif "reCAPTCHA rejected" in str(err):
                            con.print(f"\n[yellow]{err}[/yellow]")
                            break
                        elif "Session expired" in str(err) or "401" in str(err) or "Authentication" in str(err):
                            con.print(f"\n[yellow]{err}[/yellow]")
                            break
                        elif "server error" in str(err).lower() or "500" in str(err):
                            con.print(f"\n[yellow]{err}[/yellow]")
                            break
                        elif "CDP connection error" in str(err):
                            con.print(f"\n[dim yellow]Browser connection lost. Retrying...[/dim yellow]")
                            client.use_cdp = _cdp_find_arena_tab(client.cdp_port) is not None
                            if not client.use_cdp:
                                con.print(f"[dim yellow]CDP unavailable — falling back to direct API.[/dim yellow]")
                        else:
                            con.print(f"\n[red]{err}[/red]")
                            break
                    else:
                        print(text_result or "", flush=True)
                        full_text = text_result or ""

                # Fallback: direct HTTP (may fail without reCAPTCHA)
                if not full_text and not client.use_cdp:
                    resp, err = client.send_chat(model_id, current_msg)
                    if err:
                        con.print(f"\n[red]Error: {err}[/red]")
                        break

                    try:
                        for typ, val in client.parse_stream(resp, debug=debug):
                            if typ == "text" and isinstance(val, str):
                                print(val, end="", flush=True)
                                full_text += val
                            elif typ == "preview_url":
                                print()
                                print_deployment_preview(val)
                            elif typ == "source":
                                pass
                            elif typ == "error":
                                emsg = val if isinstance(val, str) else json.dumps(val)
                                con.print(f"\n[red]Stream error: {emsg}[/red]")
                    except KeyboardInterrupt:
                        con.print("\n[dim]  (interrupted)[/dim]")
                        break
                    except Exception as e:
                        con.print(f"\n[red]Stream exception: {e}[/red]")

                print()

                # Print search sources if any were received
                if client.sources:
                    print_search_sources(client.sources)

                if not full_text.strip():
                    con.print("[dim](empty response from model)[/dim]")
                    break

                # Parse and execute tools if present
                tcalls = parse_tool_calls(full_text)
                if not tcalls:
                    history.append({"role": "Assistant", "text": full_text[:3000]})
                    break

                tool_results = []
                for tc in tcalls:
                    print_tool_call(tc["name"], tc["params"])
                    res = tools.execute(tc["name"], tc["params"])
                    print_tool_result(tc["name"], res)
                    tool_results.append(f'<tool_result name="{tc["name"]}">\n{res[:4000]}\n</tool_result>')

                history.append({"role": "Assistant", "text": full_text[:3000]})
                results_text = "\n".join(tool_results)
                history.append({"role": "System", "text": results_text[:3500]})

                ctx = "\n".join(f"[{h['role']}]\n{h['text']}" for h in history[-8:])
                current_msg = f"[System]\n{sys_prompt}\n\n{ctx}\n\n[Tool Results]\n{results_text}\n\nContinue executing next tools or give final answer."

    finally:
        tools.shutdown()
        cleanup_pid()


def main() -> None:
    """CLI dispatcher."""
    if len(sys.argv) < 2:
        # Interactive arrow-key menu loop
        while True:
            choice = show_main_menu()
            if not choice or choice == "quit":
                con.print("\n  [dim]Exiting Arena CLI. Goodbye![/dim]\n")
                break
            elif choice == "chat":
                cmd_chat()
            elif choice == "mode":
                cmd_mode()
            elif choice == "login":
                cmd_login()
            elif choice == "models":
                cmd_models()
            elif choice in ("set-model", "model"):
                cmd_set_model()
            elif choice == "mcp":
                cmd_mcp()
            elif choice == "ask":
                con.print("\n  [bold cyan]What is your question?[/bold cyan]")
                try:
                    q = input("  > ").strip()
                    if q:
                        cmd_chat(initial_msg=q)
                except (EOFError, KeyboardInterrupt):
                    pass
            con.print()
        return

    cmd = sys.argv[1].lower().strip("-")
    try:
        if cmd in ("help", "h"):
            print_cli_help()
        elif cmd == "login":
            cmd_login()
        elif cmd in ("mode", "modality"):
            cmd_mode()
        elif cmd == "models":
            cmd_models()
        elif cmd in ("set-model", "model", "set"):
            cmd_set_model()
        elif cmd == "chat":
            cmd_chat()
        elif cmd == "mcp":
            cmd_mcp()
        elif cmd == "ask":
            msg = " ".join(sys.argv[2:])
            if msg:
                cmd_chat(initial_msg=msg)
            else:
                con.print("[red]Usage: arena.bat ask \"your question\"[/red]")
        else:
            cmd_chat(initial_msg=" ".join(sys.argv[1:]))
    except (KeyboardInterrupt, UserAbort):
        con.print("\n[dim]Cancelled.[/dim]")
    except Exception as e:
        con.print(f"[red]Fatal error: {type(e).__name__}: {e}[/red]")
        if "--debug" in sys.argv:
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
