"""
Browser worker: wraps browser-use with the multi-provider LLM pool.
browser-use handles self-healing navigation; we supply the LLM backend.
Workers are short-lived — spawned per task, torn down on completion.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.llm_pool import LLMPool


@dataclass
class BrowserResult:
    task: str
    success: bool
    output: str
    error: str = ""


async def run_browser_task(
    task: str,
    pool: "LLMPool",
    max_steps: int = 20,
) -> BrowserResult:
    """
    Execute a single browser task via browser-use.
    The LLM is provided by our pool so rate limiting applies uniformly.
    """
    try:
        from langchain_openai import ChatOpenAI
        from browser_use import Agent as BrowserAgent

        provider = await pool.acquire()

        # browser-use uses langchain's ChatOpenAI interface;
        # we point it at whichever provider was acquired.
        llm = ChatOpenAI(
            model=provider.model_for("worker"),
            openai_api_key=provider.api_key,
            openai_api_base=provider.base_url,
            temperature=0.3,
        )

        agent = BrowserAgent(task=task, llm=llm)
        result = await agent.run(max_steps=max_steps)

        return BrowserResult(
            task=task,
            success=True,
            output=str(result),
        )
    except Exception as exc:
        return BrowserResult(
            task=task,
            success=False,
            output="",
            error=str(exc),
        )


async def run_browser_tasks_bounded(
    tasks: list[str],
    pool: "LLMPool",
    max_concurrent: int = 3,
    **kwargs,
) -> list[BrowserResult]:
    """
    Run multiple browser tasks with a concurrency cap.
    VPS has limited RAM — 3 concurrent Chromium instances is the safe ceiling on CX22.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _bounded(task: str) -> BrowserResult:
        async with semaphore:
            return await run_browser_task(task, pool, **kwargs)

    return list(await asyncio.gather(*[_bounded(t) for t in tasks]))
