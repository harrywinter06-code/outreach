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

    browser-use 0.x switched from accepting langchain's ChatOpenAI to
    requiring its own BaseChatModel Protocol (needs `.provider`, `.name`,
    `.model_name`, `.ainvoke`). We adapt our pooled provider to that
    interface via _PoolBackedChatModel below.
    """
    try:
        from browser_use import Agent as BrowserAgent

        provider = await pool.acquire()
        llm = _PoolBackedChatModel(provider=provider)
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


class _PoolBackedChatModel:
    """Adapter so browser-use's BaseChatModel protocol can use our pooled
    OpenAI-compatible providers (NIM, Groq, Gemini, Cerebras).

    browser-use 0.x expects: .provider (str), .name (str), .model_name (str),
    .model (str), async .ainvoke(messages, output_format=None) returning
    ChatInvokeCompletion. We make all of those readable, then translate
    browser-use's UserMessage/SystemMessage/AssistantMessage into the
    OpenAI Chat Completions payload our providers already accept."""

    def __init__(self, provider) -> None:
        self._provider = provider
        # browser-use reads `model` as a public attribute (not property)
        self.model = provider.model_for("worker")

    @property
    def provider(self) -> str:
        # browser-use uses this to pick output-parsing rules. "openai" works
        # for any OpenAI-compatible endpoint (which is what NIM/Groq/etc are).
        return "openai"

    @property
    def name(self) -> str:
        return f"clawbot-pool/{self._provider.name}"

    @property
    def model_name(self) -> str:
        return self.model

    async def ainvoke(self, messages, output_format=None, **kwargs):
        from browser_use.llm.views import ChatInvokeCompletion
        import httpx

        # Translate browser-use message objects to OpenAI Chat Completions
        openai_messages = []
        for m in messages:
            content = m.content
            # browser-use ContentPart objects → join their text representations
            if isinstance(content, list):
                parts = []
                for cp in content:
                    text = getattr(cp, "text", None)
                    if text is not None:
                        parts.append(text)
                content = "\n".join(parts)
            openai_messages.append({"role": m.role, "content": str(content)})

        payload = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        # output_format is a Pydantic model (browser-use uses JSON Schema)
        if output_format is not None:
            try:
                schema = output_format.model_json_schema()
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": output_format.__name__, "schema": schema, "strict": False},
                }
            except Exception:
                pass

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._provider.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._provider.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["choices"][0]["message"]["content"]
        result: Any
        if output_format is not None:
            import json as _json
            try:
                result = output_format.model_validate_json(text)
            except Exception:
                # Best-effort: try to extract a JSON object from the text
                try:
                    parsed = _json.loads(text)
                    result = output_format.model_validate(parsed)
                except Exception:
                    result = text  # fall back to raw string
        else:
            result = text

        # browser-use parses .usage if present; we don't expose token counts
        # because NIM/Gemini/etc surface different fields. None is allowed.
        return ChatInvokeCompletion(completion=result, usage=None)


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
