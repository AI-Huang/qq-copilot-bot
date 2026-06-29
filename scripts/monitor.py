#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry-point script for the message-count dashboard.

Run from the repo root::

    uv run python scripts/monitor.py            # TUI (default)
    uv run python scripts/monitor.py tui --interval 5
    uv run python scripts/monitor.py web --port 8787
    uv run python scripts/monitor.py web --host 0.0.0.0 --port 8787
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure ``src/`` is importable when run as a plain script from the repo root.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from qq_copilot_bot.monitor.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
