#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Terminal (TUI) message-count dashboard built on the monitor base.

Renders a live, self-refreshing panel using rich. It is a thin presentation
layer over :class:`MessageStatsCollector`; all statistics come from the base.

Run::

    uv run python scripts/monitor.py tui --interval 5
"""

import time
from collections import deque

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .collector import MessageStatsCollector

_SPARK = " ▁▂▃▄▅▆▇█"


def _fmt_duration(seconds: float | None) -> str:
    """Format a number of seconds as ``H:MM:SS`` (or ``MM:SS``)."""
    if seconds is None:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _sparkline(values: deque[float], width: int = 40) -> str:
    """Render recent values as a unicode sparkline."""
    if not values:
        return ""
    recent = list(values)[-width:]
    lo, hi = min(recent), max(recent)
    span = (hi - lo) or 1.0
    return "".join(
        _SPARK[min(len(_SPARK) - 1, int((v - lo) / span * (len(_SPARK) - 1)))]
        for v in recent
    )


def _label_session(session_id: str) -> str:
    """Turn 'group:12345' / 'private:12345' into a compact label."""
    if session_id.startswith("group:"):
        return f"群 {session_id[6:]}"
    if session_id.startswith("private:"):
        return f"私聊 {session_id[8:]}"
    return session_id


def _render(stats: object, rate_history: deque[float]) -> Panel:
    """Build the rich renderable for one frame from a Stats snapshot."""
    rate_color = "green" if stats.rate_avg > 0 else "yellow"  # type: ignore[attr-defined]

    head = Table.grid(expand=True)
    head.add_column(justify="left")
    head.add_column(justify="right")
    head.add_row(
        Text("QQ Copilot Bot — 消息数量看板", style="bold cyan"),
        Text(time.strftime("%Y-%m-%d %H:%M:%S"), style="dim"),
    )

    body = Table.grid(padding=(0, 2))
    body.add_column(justify="right", style="bold")
    body.add_column(justify="left")
    body.add_row("消息总数", f"[bold white]{stats.total:,}[/]")  # type: ignore[attr-defined]
    body.add_row(
        "用户 / 机器人",
        f"用户 [bold]{stats.total_user:,}[/]  机器人 [bold]{stats.total_assistant:,}[/]",  # type: ignore[attr-defined]
    )
    body.add_row(
        "私聊 / 群聊",
        f"私聊 [bold]{stats.total_private:,}[/]  群聊 [bold]{stats.total_group:,}[/]",  # type: ignore[attr-defined]
    )
    body.add_row("本轮新增", f"+{stats.delta} / {stats.interval_s:.1f}s")  # type: ignore[attr-defined]
    body.add_row(
        "速度 msgs/min",
        f"瞬时 [bold {rate_color}]{stats.rate_instant:.1f}[/]  "  # type: ignore[attr-defined]
        f"平均 [bold]{stats.rate_avg:.1f}[/]  "  # type: ignore[attr-defined]
        f"EMA [bold]{stats.rate_ema:.1f}[/]",  # type: ignore[attr-defined]
    )
    body.add_row("已运行", _fmt_duration(stats.elapsed_s))  # type: ignore[attr-defined]
    body.add_row("速度趋势", Text(_sparkline(rate_history), style=rate_color))

    sessions = Table(title="按会话 Top 12", title_style="dim", expand=True, box=None)
    sessions.add_column("会话", style="cyan")
    sessions.add_column("消息数", justify="right")
    for sid, n in list(stats.per_session.items())[:12]:  # type: ignore[attr-defined]
        sessions.add_row(_label_session(sid), f"{n:,}")

    return Panel(
        Group(head, Text(""), body, Text(""), sessions),
        border_style=rate_color,
        title="[bold]message monitor[/]",
        subtitle=f"[dim]refresh {stats.interval_s:.0f}s · Ctrl-C 退出[/]",  # type: ignore[attr-defined]
    )


def run_tui(interval: float = 5.0, window: int = 12) -> None:
    """Run the live terminal dashboard until interrupted."""
    rate_history: deque[float] = deque(maxlen=60)
    with MessageStatsCollector(window=window) as collector:
        with Live(auto_refresh=False, screen=False) as live:
            try:
                while True:
                    collector.poll()
                    stats = collector.stats()
                    rate_history.append(stats.rate_ema)
                    live.update(_render(stats, rate_history), refresh=True)
                    time.sleep(interval)
            except KeyboardInterrupt:
                pass
