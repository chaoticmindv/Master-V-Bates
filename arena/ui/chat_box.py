"""
Interactive prompt_toolkit chat box with history and autocompletion.
"""

from typing import Optional
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style

from arena.config import HIST_FILE, UserAbort

COMMANDS = [
    "/help",
    "/model",
    "/models",
    "/mode",
    "/settings",
    "/persona",
    "/router",
    "/new",
    "/clear",
    "/tools",
    "/login",
    "/cd",
    "/debug",
    "/quit",
    "/exit",
]

completer = WordCompleter(COMMANDS, ignore_case=True)

pt_style = Style.from_dict({
    "prompt": "bold #299BFF",
    "command": "bold #299BFF",
})


def get_chat_input(prompt_label: str = "❯ ") -> str:
    """Prompt user for interactive chat input with history and safe fallback."""
    try:
        hist = FileHistory(str(HIST_FILE))
    except Exception:
        hist = None

    try:
        text = pt_prompt(
            [("class:prompt", prompt_label)],
            history=hist,
            completer=completer,
            multiline=False,
            style=pt_style,
        )
        if text is None:
            raise UserAbort()
        return text.strip()
    except (EOFError, KeyboardInterrupt):
        raise UserAbort()
    except Exception:
        # Fallback for piped or non-standard console environments
        try:
            return input(prompt_label).strip()
        except (EOFError, KeyboardInterrupt):
            raise UserAbort()
