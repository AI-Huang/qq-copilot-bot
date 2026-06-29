#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @Date    : 2019/02/19
# @Author  : Kelly Hwong
# @Desc    : NoneBot2 project with OneBot V11 adapter

import argparse
import os


def _resolve_environment() -> str:
    """Resolve the runtime environment from the ``--env`` CLI flag.

    ``--env prod`` loads ``.env + .env.prod``; ``--env dev`` loads ``.env +
    .env.dev``; omitting ``--env`` loads only ``.env``.
    """
    parser = argparse.ArgumentParser(description="QQ Copilot Bot")
    parser.add_argument(
        "--env",
        metavar="NAME",
        default="",
        help="环境名，载入 .env + .env.<NAME>，留空仅载入 .env",
    )
    args, _ = parser.parse_known_args()
    return args.env


# Resolve and export the environment before any settings/plugins are imported,
# so both NoneBot and MySQLSettings load the matching ``.env.<environment>``.
os.environ["ENVIRONMENT"] = _resolve_environment()

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
