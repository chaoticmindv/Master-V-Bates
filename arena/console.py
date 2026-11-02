"""
Shared Rich Console instance with Windows UTF-8 safety.
"""

import sys
import os
from rich.console import Console

# Ensure UTF-8 streams
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

con = Console(legacy_windows=False, force_terminal=True)

