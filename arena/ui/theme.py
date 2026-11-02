"""
Arena.ai brand colors, styles, and animated mascot frames.
Colors sourced from arena.ai: warm dark (#242422), cream text (#F4F0EB), blue accent (#299BFF).
"""

from rich.theme import Theme

# Arena.ai brand palette
ARENA_DARK = "#242422"       # Background
ARENA_SURFACE = "#2C2B28"    # Card/surface
ARENA_TEXT = "#F4F0EB"       # Primary text (warm cream)
ARENA_DIM = "#C7C2BC"        # Secondary text
ARENA_MUTED = "#6B6560"      # Muted text
ARENA_BLUE = "#299BFF"       # Primary accent
ARENA_GREEN = "#10B981"      # Success/connected
ARENA_RED = "#EF4444"        # Error
ARENA_YELLOW = "#F59E0B"     # Warning

THEME = Theme({
    "brand": f"bold {ARENA_BLUE}",
    "brand_dim": "#1E7ACC",
    "text": ARENA_TEXT,
    "dim": ARENA_MUTED,
    "highlight": f"bold {ARENA_BLUE}",
    "success": f"bold {ARENA_GREEN}",
    "warning": f"bold {ARENA_YELLOW}",
    "error": f"bold {ARENA_RED}",
    "cyan": ARENA_BLUE,
    "code": "#A78BFA",
    "tool_name": f"bold {ARENA_BLUE}",
    "prompt": f"bold {ARENA_BLUE}",
})

# CLI mascot — three pillars (matches Arena.ai logo)
MASCOT = [
    " ╻╻╻ ",
    " ┃┃┃ ",
    " ━━━ ",
]

MASCOT_IDLE = MASCOT

MASCOT_THINKING = [
    [" ╻╻╻ ", " ┃┃┃ ", " ◌◌◌ "],
    [" ╻╻╻ ", " ┃┃┃ ", " ·◌· "],
    [" ╻╻╻ ", " ┃┃┃ ", " ◌·◌ "],
    [" ╻╻╻ ", " ┃┃┃ ", " ·◌· "],
]

MASCOT_TYPING = [
    [" ╻╻╻ ", " ┃┃┃ ", " ━▏━ "],
    [" ╻╻╻ ", " ┃┃┃ ", " ━▎━ "],
    [" ╻╻╻ ", " ┃┃┃ ", " ━▍━ "],
    [" ╻╻╻ ", " ┃┃┃ ", " ━▌━ "],
]

MASCOT_SUCCESS = [" ╻╻╻ ", " ┃┃┃ ", " ━✓━ "]
MASCOT_ERROR = [" ╻╻╻ ", " ┃┃┃ ", " ━✗━ "]

# Spinner frames for streaming
SPINNERS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Status indicators
STATUS_CONNECTED = f"[bold {ARENA_GREEN}]●[/bold {ARENA_GREEN}]"
STATUS_DISCONNECTED = f"[dim {ARENA_RED}]○[/dim {ARENA_RED}]"
STATUS_THINKING = f"[bold {ARENA_BLUE}]◌[/bold {ARENA_BLUE}]"
