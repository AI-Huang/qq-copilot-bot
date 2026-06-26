"""Reusable LLM health-check orchestration.

Lists models from the Copilot proxy, probes each chat-capable model with a
minimal request, and persists one ``llm_health`` row per model. Shared by the
scheduled plugin and the standalone ``scripts/check_llm_health.py`` runner.
"""

from __future__ import annotations

from nonebot.log import logger

from qq_copilot_bot.services.copilot.copilot_service import (
    check_model_health,
    list_models,
)
from qq_copilot_bot.services.mysql.mysql_service import save_llm_health
from settings import copilot_settings


def chat_model_ids(payload: object) -> list[str]:
    """Extract chat-capable model ids from a ``/v1/models`` payload.

    Embedding models are skipped since they cannot serve chat completions.
    """
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if not model_id or "embedding" in model_id.lower():
            continue
        ids.append(model_id)
    return ids


async def run_health_checks() -> list[dict]:
    """Probe every chat-capable model and store each result.

    :return: list of per-model result dicts (``model`` plus probe fields).
    """
    payload = await list_models()
    model_ids = chat_model_ids(payload)
    results: list[dict] = []
    for model_id in model_ids:
        result = await check_model_health(model_id)
        save_llm_health(
            model=model_id,
            endpoint=copilot_settings.api_url,
            healthy=result["healthy"],
            status_code=result["status_code"],
            latency_ms=result["latency_ms"],
            error=result["error"],
        )
        results.append({"model": model_id, **result})

    healthy = sum(1 for r in results if r["healthy"])
    logger.info(
        "LLM health check done: {}/{} healthy",
        healthy,
        len(results),
    )
    return results
