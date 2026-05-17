"""
Multi-provider LLM pool. Routes calls across NIM, Groq, Gemini, and Cerebras.
All four expose OpenAI-compatible /chat/completions — single httpx client handles all.
Rate limiting uses Redis per-minute counters (atomic INCR, multi-container safe).
Falls back to in-memory counters when redis_url=None (tests).
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception

from clawbot.config import Settings

logger = logging.getLogger(__name__)

Tier = Literal["executive", "worker"]


class RateLimitExceeded(Exception):
    pass


class AllProvidersExhausted(Exception):
    pass


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model_executive: str
    model_worker: str
    rpm: int
    rpd: int  # requests per day — daily budget, not just burst rate
    # in-memory fallback counters (tests only)
    _mem_count: int = field(default=0, repr=False)
    _mem_minute: int = field(default=-1, repr=False)
    _mem_day_count: int = field(default=0, repr=False)
    _mem_day: int = field(default=-1, repr=False)

    def model_for(self, tier: Tier) -> str:
        return self.model_executive if tier == "executive" else self.model_worker


class LLMPool:
    def __init__(self, settings: Settings, redis_url: str | None = None) -> None:
        self._settings = settings
        self._redis_url = redis_url
        self._redis: Any = None
        self._providers: list[ProviderConfig] = []
        self._index: int = 0

    async def connect(self) -> None:
        self._providers = _build_providers(self._settings)
        if not self._providers:
            raise RuntimeError(
                "No LLM providers configured — set at least one of: "
                "NIM_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, CEREBRAS_API_KEY"
            )
        url = self._redis_url or self._settings.redis_url
        if url:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def acquire(self) -> ProviderConfig:
        """
        Return the next available provider (round-robin).
        Raises AllProvidersExhausted if every provider is rate-limited this minute.
        """
        n = len(self._providers)
        for _ in range(n):
            provider = self._providers[self._index % n]
            self._index += 1
            if await self._try_consume(provider):
                return provider
        raise AllProvidersExhausted(
            f"All {n} providers rate-limited. Retry in ~60s."
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        tier: Tier = "worker",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Send chat completion request; rotates to the next provider on 4xx failures."""
        n = len(self._providers)
        last_exc: Exception | None = None
        for _ in range(n):
            provider = await self.acquire()
            try:
                return await _call_with_retry(provider, messages, tier, temperature, max_tokens)
            except (RateLimitExceeded, AllProvidersExhausted):
                raise
            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    logger.warning(
                        "Provider %s returned %s (%s) — skipping to next",
                        provider.name, exc.response.status_code,
                        exc.response.text[:120],
                    )
                    last_exc = exc
                    continue
                raise
        raise AllProvidersExhausted(
            f"All {n} providers failed with 4xx errors"
        ) from last_exc

    async def _try_consume(self, provider: ProviderConfig) -> bool:
        if self._redis is not None:
            return await _redis_try_consume(self._redis, provider)
        return _mem_try_consume(provider)

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]


# ── helpers ──────────────────────────────────────────────────────────────────

def _build_providers(s: Settings) -> list[ProviderConfig]:
    providers = []
    # One ProviderConfig per NIM key — each gets its own rate limit bucket.
    # If a key gets banned, that bucket exhausts; the others continue.
    for i, key in enumerate(s.nim_api_keys, start=1):
        providers.append(ProviderConfig(
            name=f"nim-{i}", base_url=s.nim_base_url, api_key=key,
            model_executive=s.nim_model_executive, model_worker=s.nim_model_worker,
            rpm=s.nim_rpm, rpd=s.nim_rpd,
        ))
    if s.groq_api_key:
        providers.append(ProviderConfig(
            name="groq", base_url=s.groq_base_url, api_key=s.groq_api_key,
            model_executive=s.groq_model_executive, model_worker=s.groq_model_worker,
            rpm=s.groq_rpm, rpd=s.groq_rpd,
        ))
    if s.gemini_api_key:
        providers.append(ProviderConfig(
            name="gemini", base_url=s.gemini_base_url, api_key=s.gemini_api_key,
            model_executive=s.gemini_model_executive, model_worker=s.gemini_model_worker,
            rpm=s.gemini_rpm, rpd=s.gemini_rpd,
        ))
    if s.cerebras_api_key:
        providers.append(ProviderConfig(
            name="cerebras", base_url=s.cerebras_base_url, api_key=s.cerebras_api_key,
            model_executive=s.cerebras_model_executive, model_worker=s.cerebras_model_worker,
            rpm=s.cerebras_rpm, rpd=s.cerebras_rpd,
        ))
    return providers


async def _redis_try_consume(redis: Any, provider: ProviderConfig) -> bool:
    now = time.time()
    minute = int(now) // 60
    day = int(now) // 86400

    rpm_key = f"clawbot:ratelimit:{provider.name}:{minute}"
    rpd_key = f"clawbot:ratelimit:{provider.name}:day:{day}"

    # Check and increment both counters atomically enough for our purposes
    rpm_count = await redis.incr(rpm_key)
    if rpm_count == 1:
        await redis.expire(rpm_key, 120)

    rpd_count = await redis.incr(rpd_key)
    if rpd_count == 1:
        await redis.expire(rpd_key, 90_000)  # 25h TTL to survive day boundary

    if rpm_count > provider.rpm or rpd_count > provider.rpd:
        # Roll back both counters — we pre-incremented before checking
        await redis.decr(rpm_key)
        await redis.decr(rpd_key)
        return False
    return True


def _mem_try_consume(provider: ProviderConfig) -> bool:
    """In-memory fallback used only in tests (no Redis)."""
    now = time.time()
    minute = int(now) // 60
    day = int(now) // 86400

    if provider._mem_minute != minute:
        provider._mem_minute = minute
        provider._mem_count = 0
    if provider._mem_day != day:
        provider._mem_day = day
        provider._mem_day_count = 0

    provider._mem_count += 1
    provider._mem_day_count += 1
    return provider._mem_count <= provider.rpm and provider._mem_day_count <= provider.rpd


def _is_5xx_error(exc: BaseException) -> bool:
    """Retry only on 5xx (server errors). 429s should fail fast so the caller can rotate provider."""
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and 500 <= exc.response.status_code < 600
    )


async def _call_with_retry(
    provider: ProviderConfig,
    messages: list[dict[str, str]],
    tier: Tier,
    temperature: float,
    max_tokens: int,
) -> str:
    async for attempt in AsyncRetrying(
        retry=retry_if_exception(_is_5xx_error),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    ):
        with attempt:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{provider.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": provider.model_for(tier),
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                if response.status_code == 429:
                    # Fail fast — do NOT retry. The caller (acquire()) should
                    # rotate to a different provider rather than burning 4 attempts
                    # × wait_exponential(2-30s) into the same exhausted bucket.
                    raise RateLimitExceeded(
                        f"{provider.name} returned 429; rotate to a different provider"
                    )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
    raise RuntimeError("unreachable")
