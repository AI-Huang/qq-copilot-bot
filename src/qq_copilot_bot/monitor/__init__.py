"""QQ Copilot Bot — message-count live dashboard (TUI + Web).

Usage (from repo root)::

    uv run python scripts/monitor.py           # TUI (default)
    uv run python scripts/monitor.py tui --interval 5
    uv run python scripts/monitor.py web --port 8787
"""

from .collector import MessageStatsCollector

__all__ = ["MessageStatsCollector"]
