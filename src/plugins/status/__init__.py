"""NoneBot plugin: ``/status`` command.

Reports whether the bot is connected to the OneBot implementation (e.g. napcat)
and basic runtime info (QQ account, nickname, online count, uptime).
"""

from __future__ import annotations

import time

import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="status",
    description="查询机器人与 OneBot (napcat) 的连接状态",
    usage="/status",
)

# Process start time, used to compute uptime.
_START_TIME = time.time()


def _format_uptime(seconds: float) -> str:
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分")
    parts.append(f"{secs}秒")
    return "".join(parts)


_status = on_command("status", aliases={"状态"}, priority=5, block=True)


@_status.handle()
async def _(bot: Bot, event: MessageEvent) -> None:
    bots = nonebot.get_bots()
    uptime = _format_uptime(time.time() - _START_TIME)

    try:
        login = await bot.get_login_info()
        account = f"{login.get('nickname', '?')} ({login.get('user_id', bot.self_id)})"
        connected = "✅ 已连接"
    except Exception:
        account = str(bot.self_id)
        connected = "⚠️ 已握手但 API 调用失败"

    lines = [
        "🤖 机器人状态",
        f"连接: {connected}",
        f"账号: {account}",
        f"在线 Bot 数: {len(bots)}",
        f"运行时长: {uptime}",
    ]
    await _status.finish("\n".join(lines))
