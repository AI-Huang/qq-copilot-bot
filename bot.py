#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @Date    : 2019/02/19
# @Author  : Kelly Hwong
# @Desc    : NoneBot2 project with OneBot V11 adapter

import argparse
import os
import sys
from pathlib import Path


def _resolve_environment() -> str:
    """Resolve the runtime environment from CLI flags and .env file.

    Priority: CLI flags > .env ENVIRONMENT > existing ENVIRONMENT env var > dev
    ``--prod`` / ``--dev`` select a preset; ``--env NAME`` allows a custom
    overlay file ``.env.NAME``.
    """
    env_file = Path(__file__).resolve().parent / ".env"
    env_from_file = None
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ENVIRONMENT="):
                    env_from_file = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    parser = argparse.ArgumentParser(description="QQ Copilot Bot")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--prod",
        action="store_true",
        help="使用生产环境配置 (.env + .env.prod)",
    )
    group.add_argument(
        "--dev",
        action="store_true",
        help="使用开发环境配置 (.env + .env.dev)",
    )
    parser.add_argument(
        "--env",
        metavar="NAME",
        help="自定义环境名，载入 .env + .env.<NAME>",
    )
    args, _ = parser.parse_known_args()
    if args.env:
        return args.env
    if args.prod:
        return "prod"
    if args.dev:
        return "dev"
    if env_from_file:
        return env_from_file
    return os.environ.get("ENVIRONMENT", "dev")


# Resolve and export the environment before any settings/plugins are imported,
# so both NoneBot and MySQLSettings load the matching ``.env.<environment>``.
os.environ["ENVIRONMENT"] = _resolve_environment()

# Make the ``src`` layout importable (settings, qq_copilot_bot, plugins).
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from qq_copilot_bot.services.mysql.mysql_service import init_db

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)


@driver.on_startup
async def _init_database() -> None:
    init_db()


# 加载内置插件
nonebot.load_builtin_plugins("echo")
# 加载自定义插件
nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()
