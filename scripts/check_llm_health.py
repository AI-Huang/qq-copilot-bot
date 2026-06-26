"""Probe every available model from the Copilot proxy and record results.

Run from the repo root with:

    uv run python scripts/check_llm_health.py

It lists models via ``GET /v1/models``, skips embedding/non-chat models,
sends a minimal chat request to each, and writes one ``llm_health`` row per
model with status, latency, and any error. This is a one-off runner; the
``llm_health`` plugin performs the same checks automatically every 10 minutes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure ``src`` is importable when run as a plain script.
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from settings import copilot_settings  # noqa: E402
from qq_copilot_bot.services.copilot.health import run_health_checks  # noqa: E402
from qq_copilot_bot.services.mysql.mysql_service import init_db  # noqa: E402


async def main() -> None:
    init_db()
    print(f"Probing models against {copilot_settings.api_url}")
    results = await run_health_checks()
    for result in results:
        flag = "OK " if result["healthy"] else "ERR"
        print(
            f"[{flag}] {result['model']:<28} "
            f"status={result['status_code']} "
            f"latency={result['latency_ms']}ms"
        )
    healthy = sum(1 for r in results if r["healthy"])
    print(f"Done: {healthy}/{len(results)} healthy")


if __name__ == "__main__":
    asyncio.run(main())
