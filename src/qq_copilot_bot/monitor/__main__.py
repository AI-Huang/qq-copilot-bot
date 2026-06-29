#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI entry for the message-count dashboard.

Usage::

    uv run python scripts/monitor.py            # TUI (default)
    uv run python scripts/monitor.py tui --interval 5
    uv run python scripts/monitor.py web --port 8787
"""

import argparse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="QQ Copilot Bot — 消息数量看板",
    )
    sub = parser.add_subparsers(dest="cmd")

    # -- tui ------------------------------------------------------------------
    tui_p = sub.add_parser("tui", help="终端实时看板 (默认)")
    tui_p.add_argument(
        "--interval", type=float, default=5.0, help="刷新间隔秒数 (默认 5)"
    )
    tui_p.add_argument(
        "--window", type=int, default=12, help="滚动平均采样数 (默认 12)"
    )

    # -- web ------------------------------------------------------------------
    web_p = sub.add_parser("web", help="Web 看板 (浏览器打开)")
    web_p.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    web_p.add_argument("--port", type=int, default=8787, help="监听端口 (默认 8787)")
    web_p.add_argument(
        "--interval", type=float, default=5.0, help="采样间隔秒数 (默认 5)"
    )
    web_p.add_argument(
        "--window", type=int, default=12, help="滚动平均采样数 (默认 12)"
    )
    web_p.add_argument(
        "--history", type=int, default=600, help="图表保留的实时采样点数 (默认 600)"
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "web":
        from qq_copilot_bot.monitor.web import run_web

        run_web(
            host=args.host,
            port=args.port,
            interval=args.interval,
            window=args.window,
            history=args.history,
        )
    else:
        # Default: TUI (also handles explicit "tui" subcommand)
        from qq_copilot_bot.monitor.tui import run_tui

        interval = getattr(args, "interval", 5.0)
        window = getattr(args, "window", 12)
        run_tui(interval=interval, window=window)


if __name__ == "__main__":
    main()
