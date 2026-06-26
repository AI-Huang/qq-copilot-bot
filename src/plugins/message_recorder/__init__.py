"""NoneBot plugin: record QQ messages into local MySQL.

Listens to private and group message events and persists each message via the
MySQL storage service. Outgoing messages sent by the bot account are also
recorded via the ``on_called_api`` hook. Recording failures never block other
plugins.
"""

from __future__ import annotations

from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.plugin import PluginMetadata

from qq_copilot_bot.services.mysql.mysql_service import save_message

__plugin_meta__ = PluginMetadata(
    name="message_recorder",
    description="将 QQ 私聊与群聊消息（含机器人发送）记录到本地 MySQL",
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


# APIs that send a message out as the bot account.
_SEND_APIS = {"send_msg", "send_private_msg", "send_group_msg"}


@Bot.on_called_api
async def _record_sent(
    bot: Bot,
    exception: Exception | None,
    api: str,
    data: dict[str, Any],
    result: Any,
) -> None:
    """Persist messages sent by the bot account (role="assistant")."""
    if exception is not None or api not in _SEND_APIS:
        return

    group_id = data.get("group_id")
    user_id = data.get("user_id")
    is_group = api == "send_group_msg" or (
        api == "send_msg"
        and (data.get("message_type") == "group" or group_id is not None)
    )
    if is_group:
        message_type = "group"
        session_id = f"group:{group_id}"
    else:
        message_type = "private"
        session_id = f"private:{user_id}"

    raw_message = data.get("message")
    content = (
        Message(raw_message).extract_plain_text() if raw_message is not None else ""
    )

    self_id = int(bot.self_id)
    message_id = result.get("message_id") if isinstance(result, dict) else None

    save_message(
        user_id=self_id,
        session_id=session_id,
        role="assistant",
        content=content,
        message_type=message_type,
        message_id=str(message_id) if message_id is not None else None,
        self_id=self_id,
        group_id=int(group_id) if group_id is not None else None,
        sender_nickname=None,
        raw_message=str(raw_message) if raw_message is not None else None,
    )
