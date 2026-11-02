"""
Arena.ai branded startup banner with pillars motif.
"""

from typing import Optional
from rich.panel import Panel
from rich.text import Text

from arena.ui.theme import ARENA_BLUE, ARENA_TEXT, ARENA_DIM, ARENA_MUTED, ARENA_GREEN
from arena.console import con
from arena.models import MODALITIES


def print_banner(
    model_name: str,
    cwd: str,
    browser: str = "Brave",
    user_email: Optional[str] = None,
    modality: str = "chat",
) -> None:
    """Print startup banner with Arena.ai branding."""
    mod_info = MODALITIES.get(modality, MODALITIES["chat"])
    badge = mod_info["badge"]

    header = Text()

    header.append("\n")
    header.append("   ╻╻╻  ", style=f"bold {ARENA_TEXT}")
    header.append("Arena Code", style=f"bold {ARENA_TEXT}")
    header.append("  ", style="dim")
    header.append(f"{badge}", style=f"bold {ARENA_GREEN}")
    header.append("  ", style="dim")
    header.append("v1.0.0", style=f"dim {ARENA_MUTED}")
    header.append("\n\n")

    header.append("   ", style="")
    header.append("Model   ", style=f"{ARENA_MUTED}")
    header.append(f"{model_name}", style=f"bold {ARENA_BLUE}")
    header.append("\n")

    header.append("   ", style="")
    header.append("Browser ", style=f"{ARENA_MUTED}")
    header.append(f"{browser}", style=f"bold {ARENA_TEXT}")
    if user_email:
        header.append(f"  ·  {user_email}", style=f"{ARENA_MUTED}")
    header.append("\n")

    header.append("   ", style="")
    header.append("Path    ", style=f"{ARENA_MUTED}")
    display_cwd = cwd
    if len(cwd) > 50:
        display_cwd = "..." + cwd[-47:]
    header.append(f"{display_cwd}", style=f"dim {ARENA_DIM}")
    header.append("\n")

    panel = Panel(
        header,
        border_style=ARENA_BLUE,
        title=f"[bold {ARENA_TEXT}] ╻╻╻ Arena AI [/bold {ARENA_TEXT}]",
        subtitle=f"[{ARENA_MUTED}]Unofficial CLI · arena.ai[/{ARENA_MUTED}]",
        title_align="left",
        width=76,
        padding=(0, 1),
    )
    con.print(panel)
    con.print(f"[{ARENA_MUTED}]  /help · /model · /mode · /settings · /login · Esc[/{ARENA_MUTED}]\n")
