"""NoneBot plugin: chat with the Copilot API backend.

Replies to private messages and group @mentions by forwarding the conversation
(recent history loaded from MySQL plus the current message) to the Copilot chat
API, then sending the model's reply back to the user.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime

import httpx
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me
from PIL import Image as PILImage

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

# Per-session on/off switch. True (enabled) by default.
# Persists in memory only; resets to True on bot restart.
_session_enabled: dict[str, bool] = {}


def _current_model(session_id: str) -> str:
    """Return the session's selected model, or the configured default."""
    return _session_models.get(session_id, copilot_settings.model)


def _is_enabled(session_id: str) -> bool:
    """Return whether Copilot auto-reply is enabled for this session."""
    return _session_enabled.get(session_id, True)


# MIME types accepted by the Copilot / OpenAI vision API.
_VISION_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Map Pillow format names to their MIME types for the supported set.
_PILLOW_MIME: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG":  "image/png",
    "GIF":  "image/gif",
    "WEBP": "image/webp",
}


async def _url_to_data_url(url: str) -> str | None:
    """Download an image URL and return a base64 data URL.

    Uses Pillow to detect the real format regardless of the Content-Type header,
    and converts unsupported formats (BMP, TIFF, AVIF, …) to JPEG so the
    Copilot vision API never rejects the media type.

    Returns None on any download or conversion failure.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
        data = resp.content

        with PILImage.open(io.BytesIO(data)) as img:
            pillow_fmt = (img.format or "").upper()
            mime = _PILLOW_MIME.get(pillow_fmt)

            if mime is None:
                # Format not in the supported set — convert to JPEG.
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=85)
                data = buf.getvalue()
                mime = "image/jpeg"
                logger.debug(
                    "Converted image from {} to JPEG for vision API (url={})",
                    pillow_fmt or "unknown",
                    url,
                )

        b64 = base64.b64encode(data).decode()
        return f"data:{mime};base64,{b64}"
    except Exception:
        logger.warning("Failed to download/convert image for vision API: {}", url)
        return None


async def _extract_user_content(event: MessageEvent) -> str | list:
    """Extract user content from a message event.

    Returns a plain string when the message contains only text.
    Returns an OpenAI vision content array when the message contains images,
    downloading each image and encoding it as a base64 data URL (external URLs
    are not supported by the Copilot proxy).
    """
    text = event.get_plaintext().strip()
    image_urls = [
        seg.data["url"]
        for seg in event.message
        if seg.type == "image" and seg.data.get("url")
    ]
    if not image_urls:
        return text
    parts: list[dict] = []
    if text:
        parts.append({"type": "text", "text": text})
    for url in image_urls:
        data_url = await _url_to_data_url(url)
        if data_url:
            parts.append({"type": "image_url", "image_url": {"url": data_url}})
        else:
            parts.append({"type": "text", "text": "[图片下载失败]"})
    return parts if parts else text


def _build_messages(session_id: str, user_content: str | list) -> list[dict]:
    """Assemble the API message list: system + recent history + current turn."""
    messages: list[dict] = []
    if copilot_settings.system_prompt:
        messages.append({"role": "system", "content": copilot_settings.system_prompt})
    messages.extend(load_recent_history(session_id, copilot_settings.max_turns))
    messages.append({"role": "user", "content": user_content})
    return messages


def _sign(reply: str, model: str) -> str:
    """Append a ``——{model}，{time}`` signature to the reply."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"{reply}\n\n——{model}，{timestamp}"


async def _handle_chat(matcher: Matcher, event: MessageEvent) -> None:
    session_id = _session_id(event)
    if not _is_enabled(session_id):
        return

    user_content = await _extract_user_content(event)
    if not user_content:
        await matcher.finish("请在消息中附上要对话的内容~")

    messages = _build_messages(session_id, user_content)
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
    default = copilot_settings.model or "（未设置，请在 .env 配置 COPILOT_MODEL）"
    lines.append(f"\n当前默认：{default}")
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


_HELP_TEXT = """🤖 QQ Copilot Bot 使用说明

━━━━━━ 对话 ━━━━━━
直接发消息        → 私聊直接说，群内需 @机器人
/chat <内容>      → 显式发起对话
/问 /ai <内容>    → 同上

━━━━━━ 模型 ━━━━━━
/models           → 查看可用模型列表
/model            → 查看当前会话使用的模型
/model <名称>     → 切换当前会话的模型

━━━━━━ 开关 ━━━━━━
/copilot on       → 开启本会话自动回复
/copilot off      → 关闭本会话自动回复
/copilot          → 查看当前状态

━━━━━━ 其他 ━━━━━━
/status           → 查看 Bot 运行状态
/help             → 显示本帮助

💡 图片消息支持 vision 模型（如 gpt-4o）
💡 模型切换 / 开关仅对当前会话生效，重启后恢复默认""".strip()


# Explicit command entry: /help
_help_cmd = on_command(
    "help",
    aliases={"帮助", "使用说明"},
    priority=5,   # higher than chat (10) so it's never forwarded to the LLM
    block=True,
)


@_help_cmd.handle()
async def _(matcher: Matcher) -> None:
    await matcher.finish(_HELP_TEXT)


# /copilot [on|off] — enable or disable auto-reply for the current session.
_copilot_cmd = on_command(
    "copilot",
    priority=5,
    block=True,
)


@_copilot_cmd.handle()
async def _(
    matcher: Matcher,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    session_id = _session_id(event)
    arg = args.extract_plain_text().strip().lower()
    if arg == "on":
        _session_enabled[session_id] = True
        await matcher.finish("✅ Copilot 已开启，开始自动回复~")
    elif arg == "off":
        _session_enabled[session_id] = False
        await matcher.finish("🔕 Copilot 已关闭，不再自动回复（/copilot on 可重新开启）")
    else:
        status = "✅ 开启" if _is_enabled(session_id) else "🔕 关闭"
        await matcher.finish(
            f"当前状态：{status}\n"
            "「/copilot on」开启  「/copilot off」关闭"
        )


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
