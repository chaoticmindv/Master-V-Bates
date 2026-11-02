#!/usr/bin/env python
"""
Arena CLI - Free AI Coding Assistant modeled after Claude Code.
100+ models (GPT-5, Claude Sonnet, Grok, DeepSeek) — all free via arena.ai.
"""

import sys
import os
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure package root is in sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

def main():
    if "--cli" in sys.argv:
        from arena.cli import main as cli_main
        cli_main()
    else:
        from arena.desktop import main as desktop_main
        desktop_main()

if __name__ == "__main__":
    main()
