"""NoneBot plugin: chat with the Copilot API backend.

Replies to private messages and group @mentions by forwarding the conversation
(recent history loaded from MySQL plus the current message) to the Copilot chat
API, then sending the model's reply back to the user.
"""

from __future__ import annotations

from datetime import datetime

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me

from qq_copilot_bot.services.copilot.copilot_service import (
    CopilotAPIError,
    chat_completion,
    check_model_health,
    list_models,
)
from qq_copilot_bot.services.mysql.mysql_service import load_recent_history
from settings import copilot_settings

__plugin_meta__ = PluginMetadata(
    name="copilot_chat",
    description="通过 Copilot API 与机器人对话，自动带入历史上下文",
    usage="私聊直接发送消息，或在群内 @机器人 / 使用 /chat <内容>",
)


def _session_id(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}"
    return f"private:{event.user_id}"


# Per-session model overrides, keyed by session id. In-memory only: selections
# reset to the default model (``COPILOT_MODEL``) when the bot restarts.
_session_models: dict[str, str] = {}


def _current_model(session_id: str) -> str:
    """Return the session's selected model, or the configured default."""
    return _session_models.get(session_id, copilot_settings.model)


def _build_messages(session_id: str, user_text: str) -> list[dict]:
    """Assemble the API message list: system + recent history + current turn."""
    messages: list[dict] = []
    if copilot_settings.system_prompt:
        messages.append({"role": "system", "content": copilot_settings.system_prompt})
    messages.extend(load_recent_history(session_id, copilot_settings.max_turns))
    messages.append({"role": "user", "content": user_text})
    return messages


def _sign(reply: str, model: str) -> str:
    """Append a ``——{model}，{time}`` signature to the reply."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"{reply}\n\n——{model}，{timestamp}"


async def _handle_chat(matcher: Matcher, event: MessageEvent) -> None:
    user_text = event.get_plaintext().strip()
    if not user_text:
        await matcher.finish("请在消息中附上要对话的内容~")

    session_id = _session_id(event)
    messages = _build_messages(session_id, user_text)
    try:
        result = await chat_completion(messages, model=_current_model(session_id))
    except CopilotAPIError as exc:
        await matcher.finish(f"⚠️ 对话失败：{exc}")

    await matcher.finish(_sign(result.reply, result.model))


def _format_models(payload: object) -> str:
    """Format a ``/v1/models`` response into a readable model list."""
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list) or not data:
        return "未获取到可用模型。"
    lines = ["📋 可用模型："]
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if not model_id:
            continue
        display = str(item.get("display_name", "")).strip()
        owner = str(item.get("owned_by", "")).strip()
        suffix = f"（{display}·{owner}）" if display or owner else ""
        lines.append(f"• {model_id}{suffix}")
    lines.append(f"\n当前默认：{copilot_settings.model}")
    return "\n".join(lines)


def _model_ids(payload: object) -> list[str]:
    """Extract the list of model ids from a ``/v1/models`` payload."""
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = str(item.get("id", "")).strip()
            if model_id:
                ids.append(model_id)
    return ids


# Explicit command entry: /models
_models_cmd = on_command(
    "models",
    aliases={"模型", "模型列表"},
    priority=10,
    block=True,
)


@_models_cmd.handle()
async def _(matcher: Matcher) -> None:
    try:
        payload = await list_models()
    except CopilotAPIError as exc:
        await matcher.finish(f"⚠️ 获取模型列表失败：{exc}")
    await matcher.finish(_format_models(payload))


# Explicit command entry: /model <名称>  (select model for this session)
_model_cmd = on_command(
    "model",
    aliases={"选模型", "切换模型", "用模型"},
    priority=10,
    block=True,
)


@_model_cmd.handle()
async def _(
    matcher: Matcher,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    session_id = _session_id(event)
    target = args.extract_plain_text().strip()
    if not target:
        await matcher.finish(
            f"当前模型：{_current_model(session_id)}\n"
            f"默认模型：{copilot_settings.model}\n"
            "用「/model <名称>」切换，「/models」查看全部",
        )
    try:
        payload = await list_models()
    except CopilotAPIError as exc:
        await matcher.finish(f"⚠️ 获取模型列表失败：{exc}")
    if target not in _model_ids(payload):
        await matcher.finish(
            f"⚠️ 未知模型：{target}\n用「/models」查看可用模型",
        )
    # Existence is not enough: some models (e.g. gpt-5.x) are listed but cannot
    # serve /chat/completions. Probe once so we reject before the user chats.
    health = await check_model_health(target)
    if not health["healthy"]:
        await matcher.finish(
            f"⚠️ 模型「{target}」不可用于对话（HTTP {health['status_code']}）\n"
            "该模型不支持 /chat/completions，请换一个（如 gpt-4o）",
        )
    _session_models[session_id] = target
    await matcher.finish(f"✅ 已切换为：{target}")


# Explicit command entry: /chat <内容>
_chat_cmd = on_command(
    "chat",
    aliases={"问", "ai"},
    priority=10,
    block=True,
)


@_chat_cmd.handle()
async def _(matcher: Matcher, event: MessageEvent) -> None:
    await _handle_chat(matcher, event)


# Implicit entry: private messages and group @mentions.
_chat_mention = on_message(rule=to_me(), priority=15, block=True)


@_chat_mention.handle()
async def _(matcher: Matcher, event: MessageEvent) -> None:
    # Avoid double-handling command-style inputs already covered above.
    if isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        await _handle_chat(matcher, event)
