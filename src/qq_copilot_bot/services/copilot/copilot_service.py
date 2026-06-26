"""Async client for the Copilot chat API backend.

Posts an OpenAI-style ``messages`` list to the configured chat endpoint and
extracts the assistant reply defensively across common response schemas.
"""

from __future__ import annotations

import time
from typing import NamedTuple

import httpx
from nonebot.log import logger

from settings import copilot_settings


class CopilotAPIError(RuntimeError):
    """Raised when the Copilot chat API returns an error or unparsable reply."""


class ChatResult(NamedTuple):
    """Assistant reply paired with the model that actually produced it."""

    reply: str
    model: str


def _from_choices(payload: dict) -> str:
    """Extract reply from an OpenAI-style ``choices`` list."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and message.get("content"):
        return str(message["content"]).strip()
    if first.get("text"):
        return str(first["text"]).strip()
    return ""


def _from_message(payload: dict) -> str:
    """Extract reply from a nested or flat ``message`` field."""
    message = payload.get("message")
    if isinstance(message, dict) and message.get("content"):
        return str(message["content"]).strip()
    if isinstance(message, str):
        return message.strip()
    return ""


def _from_flat_keys(payload: dict) -> str:
    """Extract reply from common flat string keys."""
    for key in ("content", "response", "reply", "answer", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value.strip()
    return ""


def _extract_reply(payload: object) -> str:
    """Extract the assistant text from a variety of response shapes."""
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    for extractor in (_from_choices, _from_message, _from_flat_keys):
        reply = extractor(payload)
        if reply:
            return reply
    return ""


async def chat_completion(
    messages: list[dict],
    model: str | None = None,
) -> ChatResult:
    """Send ``messages`` to the Copilot chat API and return the assistant reply.

    :param messages: list of ``{"role": ..., "content": ...}`` dicts.
    :param model: override model name; defaults to ``COPILOT_MODEL`` setting.
    :return: a :class:`ChatResult` with the reply text and the model that the
        API reports it used (falling back to the requested model name).
    :raises CopilotAPIError: on network errors, non-2xx status, or empty reply.
    """
    model_name = model or copilot_settings.model
    body = {"model": model_name, "messages": messages}

    try:
        async with httpx.AsyncClient(timeout=copilot_settings.timeout) as client:
            resp = await client.post(copilot_settings.api_url, json=body)
    except httpx.HTTPError as exc:
        logger.exception("Copilot chat API request failed")
        msg = f"请求失败: {exc}"
        raise CopilotAPIError(msg) from exc

    if resp.status_code != httpx.codes.OK:
        msg = f"Copilot chat API HTTP {resp.status_code}: {resp.text[:200]}"
        logger.error(msg)
        raise CopilotAPIError(msg)

    try:
        payload = resp.json()
    except ValueError as exc:
        msg = "响应不是合法 JSON"
        raise CopilotAPIError(msg) from exc

    reply = _extract_reply(payload)
    if not reply:
        logger.warning("Copilot chat API returned an empty reply: {}", payload)
        raise CopilotAPIError("模型未返回内容")

    used_model = model_name
    if isinstance(payload, dict):
        reported = payload.get("model")
        if isinstance(reported, str) and reported.strip():
            used_model = reported.strip()
    return ChatResult(reply=reply, model=used_model)


async def _get_json(path: str) -> object:
    """GET ``base_url + path`` from the Copilot proxy and return parsed JSON.

    :param path: leading-slash path such as ``/usage`` or ``/v1/models``.
    :raises CopilotAPIError: on network errors, non-2xx status, or invalid JSON.
    """
    url = f"{copilot_settings.base_url}{path}"

    try:
        async with httpx.AsyncClient(timeout=copilot_settings.timeout) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        logger.exception("Copilot API GET {} failed", path)
        msg = f"请求失败: {exc}"
        raise CopilotAPIError(msg) from exc

    if resp.status_code != httpx.codes.OK:
        msg = f"Copilot API GET {path} HTTP {resp.status_code}: {resp.text[:200]}"
        logger.error(msg)
        raise CopilotAPIError(msg)

    try:
        return resp.json()
    except ValueError as exc:
        msg = f"GET {path} 响应不是合法 JSON"
        raise CopilotAPIError(msg) from exc


async def list_models() -> object:
    """List currently available models via the proxy ``GET /v1/models`` endpoint."""
    return await _get_json("/v1/models")


async def get_token() -> object:
    """Return the current Copilot token via the proxy ``GET /token`` endpoint."""
    return await _get_json("/token")


async def get_usage() -> object:
    """Return Copilot usage and quota stats via the proxy ``GET /usage`` endpoint."""
    return await _get_json("/usage")


async def check_model_health(model: str) -> dict:
    """Probe one model with a minimal chat request.

    :param model: model id to probe (e.g. ``gpt-4o``).
    :return: dict with ``healthy``, ``status_code``, ``latency_ms``, ``error``.
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=copilot_settings.timeout) as client:
            resp = await client.post(copilot_settings.api_url, json=body)
    except httpx.HTTPError as exc:
        return {
            "healthy": False,
            "status_code": None,
            "latency_ms": int((time.monotonic() - start) * 1000),
            "error": f"请求失败: {exc}",
        }

    latency_ms = int((time.monotonic() - start) * 1000)
    healthy = resp.status_code == httpx.codes.OK
    error = None if healthy else resp.text[:500]
    return {
        "healthy": healthy,
        "status_code": resp.status_code,
        "latency_ms": latency_ms,
        "error": error,
    }
