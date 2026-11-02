"""
Interactive arrow-key main menu for start.bat.
"""

from typing import Optional
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Layout
from prompt_toolkit.styles import Style

from arena.config import get_cookie, load_config
from arena.auth import parse_cookie_input


def show_main_menu() -> Optional[str]:
    """Render interactive arrow-key menu and return selected command."""
    cookie = get_cookie()
    cfg = load_config()
    model_name = cfg.get("model_name", "not set")
    active_browser = cfg.get("browser", "Brave")
    active_modality = cfg.get("modality", "chat")
    mod_badge = f"[{active_modality.upper()}]"

    user_email = None
    if cookie:
        _, _, u_info = parse_cookie_input(cookie)
        if u_info:
            user_email = u_info.get("email")

    menu_items = [
        ("chat",      "chat",       "Start AI coding session"),
        ("mode",      "mode",       "Switch modality (Text, Code/Webdev, Search, Image, Max Router)"),
        ("login",     "login",      "Browser login / select browser (Brave, Edge, Chrome)"),
        ("models",    "models",     "Browse 100+ free models (filter by category)"),
        ("set-model", "set-model",  "Change active model"),
        ("mcp",       "mcp",        "MCP & Multi-Browser tools status"),
        ("ask",       "ask",        "Ask one-shot question"),
        ("quit",      "quit",       "Exit"),
    ]
    selected = [0]
    result = [None]

    def get_menu_text():
        lines = []
        lines.append(("class:title", " ╻╻╻ "))
        lines.append(("class:title", "Arena Code"))
        lines.append(("class:dim", " — Free AI Coding Assistant\n"))
        lines.append(("class:dim", "      Powered by arena.ai · 100+ Top Models\n"))

        # Status line
        if cookie:
            lines.append(("class:ok", "  ✓ Connected"))
            lines.append(("class:dim", f" ({user_email or 'active'})  "))
            lines.append(("class:dim", "│  Model: "))
            lines.append(("class:model", f"{model_name}"))
            lines.append(("class:dim", "  │  "))
            lines.append(("class:ok", f"{mod_badge}"))
            lines.append(("class:dim", f"  │  {active_browser}\n"))
        else:
            lines.append(("class:warn", "  ✗ Not logged in"))
            lines.append(("class:dim", " — select 'login' to connect\n"))

        lines.append(("class:dim", "\n  ↑↓ navigate · Enter select · 1-8 jump · Esc exit\n\n"))

        for i, (key, label, desc) in enumerate(menu_items):
            if i == selected[0]:
                lines.append(("class:selected", f"   ▸ {i+1}. {label:<12s}  {desc}\n"))
            else:
                lines.append(("class:num", f"     {i+1}"))
                lines.append(("class:item", f". {label:<12s}  "))
                lines.append(("class:desc", f"{desc}\n"))
        return lines

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        selected[0] = (selected[0] - 1) % len(menu_items)

    @kb.add("down")
    def _down(event):
        selected[0] = (selected[0] + 1) % len(menu_items)

    @kb.add("enter")
    def _enter(event):
        result[0] = menu_items[selected[0]][0]
        event.app.exit()

    @kb.add("c-c")
    @kb.add("escape")
    def _quit(event):
        result[0] = "quit"
        event.app.exit()

    # Number keys
    for idx in range(len(menu_items)):
        @kb.add(str(idx + 1))
        def _num(event, i=idx):
            result[0] = menu_items[i][0]
            event.app.exit()

    style = Style.from_dict({
        "border":   "#299BFF",
        "title":    "bold #F4F0EB",
        "dim":      "#6B6560",
        "selected": "bold #299BFF reverse",
        "item":     "#F4F0EB",
        "desc":     "#C7C2BC",
        "num":      "bold #299BFF",
        "ok":       "bold #10B981",
        "warn":     "bold #F59E0B",
        "model":    "bold #299BFF",
    })

    body = HSplit([
        Window(content=FormattedTextControl(get_menu_text), wrap_lines=False),
    ])

    app = Application(
        layout=Layout(body),
        key_bindings=kb,
        style=style,
        full_screen=False,
        mouse_support=False,
    )

    try:
        app.run()
        return result[0]
    except Exception:
        # Fallback to numbered text menu if console buffer is unavailable
        print("\n  Arena Code — Main Menu\n")
        for i, (key, label, desc) in enumerate(menu_items, 1):
            print(f"  {i}. {label:<12s} — {desc}")
        try:
            c = input("\n  Choice [1-8]> ").strip()
            if c.isdigit() and 1 <= int(c) <= len(menu_items):
                return menu_items[int(c) - 1][0]
        except (EOFError, KeyboardInterrupt):
            pass
        return None
