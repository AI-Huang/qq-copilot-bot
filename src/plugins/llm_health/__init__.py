"""NoneBot plugin: periodic LLM health checks.

Every 10 minutes, probes all chat-capable models exposed by the Copilot proxy
and records each result in the ``llm_health`` table.
"""

from __future__ import annotations

from nonebot import require
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler  # noqa: E402

from qq_copilot_bot.services.copilot.health import run_health_checks  # noqa: E402

__plugin_meta__ = PluginMetadata(
    name="llm_health",
    description="每 10 分钟检查一次各模型可用性并写入 llm_health 表",
    usage="无需交互，启动后自动按计划运行",
)


@scheduler.scheduled_job("interval", minutes=10, id="llm_health_check")
async def _llm_health_check() -> None:
    try:
        await run_health_checks()
    except Exception:
        logger.exception("Scheduled LLM health check failed")
