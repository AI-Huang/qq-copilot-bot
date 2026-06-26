"""NoneBot plugin: record QQ messages into local MySQL.

Listens to private and group message events and persists each message via the
MySQL storage service. Recording failures never block other plugins.
"""

from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.plugin import PluginMetadata

from qq_copilot_bot.services.mysql.mysql_service import save_message

__plugin_meta__ = PluginMetadata(
    name="message_recorder",
    description="将 QQ 私聊与群聊消息记录到本地 MySQL",
    usage="自动监听消息事件，无需手动触发",
)

# Low priority and non-blocking so business plugins are not interrupted.
_recorder = on_message(priority=99, block=False)


@_recorder.handle()
async def _(event: MessageEvent) -> None:
    if isinstance(event, GroupMessageEvent):
        message_type = "group"
        group_id = event.group_id
        session_id = f"group:{event.group_id}"
    elif isinstance(event, PrivateMessageEvent):
        message_type = "private"
        group_id = None
        session_id = f"private:{event.user_id}"
    else:
        return

    sender_nickname = event.sender.nickname if event.sender else None

    save_message(
        user_id=event.user_id,
        session_id=session_id,
        role="user",
        content=event.get_plaintext(),
        message_type=message_type,
        message_id=str(event.message_id),
        self_id=event.self_id,
        group_id=group_id,
        sender_nickname=sender_nickname,
        raw_message=event.raw_message,
    )
