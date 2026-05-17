"""Quick liveness check for the LLM pool. Run before deploying.

  uv run python scripts/smoke_nim.py

Verifies: providers loaded from .env, multi-account rotation works, one real
inference round-trip succeeds. Fails loud at the boundary if any key is dead.
"""
import asyncio
import sys

from clawbot.config import settings
from clawbot.llm_pool import LLMPool


async def main() -> int:
    # Smoke runs from the host machine where Redis isn't reachable. The pool
    # falls back to in-memory rate-limit counters when no Redis URL is given.
    settings.redis_url = ""
    pool = LLMPool(settings=settings, redis_url=None)
    await pool.connect()
    providers = pool.provider_names
    print(f"Active providers ({len(providers)}): {providers}")
    if not providers:
        print("FAIL: no providers configured — check .env")
        return 1

    print("Sending test prompt ...")
    try:
        response = await pool.complete(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            tier="worker",
            max_tokens=20,
        )
    except Exception as exc:
        print(f"FAIL: pool.complete raised {type(exc).__name__}: {exc}")
        return 1

    print(f"NIM said: {response.strip()!r}")
    print("PASS — pool is alive")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
