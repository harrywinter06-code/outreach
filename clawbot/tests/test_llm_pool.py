import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from clawbot.llm_pool import (
    LLMPool, AllProvidersExhausted, ProviderConfig, RateLimitExceeded,
    _mem_try_consume, _is_5xx_error, _call_with_retry,
)
from clawbot.config import Settings


def _settings_with(**overrides) -> Settings:
    # Explicitly zero every credential field so test results don't depend on
    # whatever's in the developer's local .env (e.g. NIM_API_KEY_2 leaking in).
    defaults = {
        "nim_api_key_1": "",
        "nim_api_key_2": "",
        "nim_api_key_3": "",
        "nim_api_key_4": "",
        "nim_api_key_5": "",
        "groq_api_key": "",
        "gemini_api_key": "",
        "cerebras_api_key": "",
        "gumroad_api_key": "",
        "stripe_secret_key": "",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "ntfy_topic": "",
        "redis_url": "",
        "database_url": "postgresql://test:test@localhost/test",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_pool_raises_when_no_providers_configured():
    pool = LLMPool(settings=_settings_with(), redis_url=None)
    pool._providers = []  # force empty, bypassing connect()
    with pytest.raises(AllProvidersExhausted):
        await pool.acquire()


@pytest.mark.asyncio
async def test_pool_rotates_across_providers():
    s = _settings_with(nim_api_key_1="nim-k", groq_api_key="groq-k")
    pool = LLMPool(settings=s, redis_url=None)
    await pool.connect()

    names_used: list[str] = []
    for _ in range(4):
        p = await pool.acquire()
        names_used.append(p.name)

    assert "nim-1" in names_used
    assert "groq" in names_used


@pytest.mark.asyncio
async def test_pool_exhausts_when_rpm_limit_hit():
    s = _settings_with(nim_api_key_1="nim-k")
    pool = LLMPool(settings=s, redis_url=None)
    await pool.connect()

    provider = pool._providers[0]
    provider.rpm = 1
    provider.rpd = 10_000
    await pool.acquire()  # consumes 1 rpm token

    with pytest.raises(AllProvidersExhausted):
        await pool.acquire()


@pytest.mark.asyncio
async def test_pool_exhausts_when_daily_budget_hit():
    s = _settings_with(nim_api_key_1="nim-k")
    pool = LLMPool(settings=s, redis_url=None)
    await pool.connect()

    provider = pool._providers[0]
    provider.rpm = 10_000
    provider.rpd = 1
    await pool.acquire()  # consumes 1 daily token

    with pytest.raises(AllProvidersExhausted):
        await pool.acquire()


def _provider(**kwargs) -> ProviderConfig:
    defaults = dict(
        name="test", base_url="http://x", api_key="k",
        model_executive="big", model_worker="small",
        rpm=30, rpd=1000,
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)


def test_provider_model_for_tier():
    p = _provider(model_executive="big-model", model_worker="small-model")
    assert p.model_for("executive") == "big-model"
    assert p.model_for("worker") == "small-model"


def test_mem_try_consume_respects_rpm():
    p = _provider(rpm=2, rpd=1000)
    assert _mem_try_consume(p) is True   # 1 of 2
    assert _mem_try_consume(p) is True   # 2 of 2
    assert _mem_try_consume(p) is False  # over rpm limit


def test_mem_try_consume_respects_rpd():
    p = _provider(rpm=1000, rpd=2)
    assert _mem_try_consume(p) is True   # 1 of 2
    assert _mem_try_consume(p) is True   # 2 of 2
    assert _mem_try_consume(p) is False  # over daily limit


@pytest.mark.asyncio
async def test_complete_calls_provider_with_correct_tier():
    s = _settings_with(nim_api_key_1="nim-k")
    pool = LLMPool(settings=s, redis_url=None)
    await pool.connect()

    with patch("clawbot.llm_pool._call_with_retry", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = "response text"
        result = await pool.complete([{"role": "user", "content": "hi"}], tier="executive")

    assert result == "response text"
    mock_call.assert_called_once()
    _, _, tier_arg, _, _ = mock_call.call_args.args
    assert tier_arg == "executive"


@pytest.mark.asyncio
async def test_active_providers_only_includes_configured_keys():
    s = _settings_with(nim_api_key_1="k1", groq_api_key="k2")
    pool = LLMPool(settings=s, redis_url=None)
    await pool.connect()
    assert pool.provider_names == ["nim-1", "groq"]


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    response = MagicMock(spec=httpx.Response)
    response.status_code = code
    return httpx.HTTPStatusError(f"{code}", request=MagicMock(), response=response)


def test_is_5xx_error_true_for_500_and_503():
    assert _is_5xx_error(_http_status_error(500)) is True
    assert _is_5xx_error(_http_status_error(503)) is True


def test_is_5xx_error_false_for_429():
    """429 must NOT be retried — caller should rotate provider instead."""
    assert _is_5xx_error(_http_status_error(429)) is False


def test_is_5xx_error_false_for_4xx_and_non_http_errors():
    assert _is_5xx_error(_http_status_error(401)) is False
    assert _is_5xx_error(ValueError("not an http error")) is False


@pytest.mark.asyncio
async def test_call_with_retry_raises_RateLimitExceeded_on_429_without_retrying():
    """A 429 response should fail fast — no exponential backoff burning the bucket further."""
    provider = ProviderConfig(
        name="test", base_url="http://x", api_key="k",
        model_executive="big", model_worker="small", rpm=30, rpd=1000,
    )
    fake_response = MagicMock()
    fake_response.status_code = 429
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value={})

    post_mock = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.post = post_mock
        with pytest.raises(RateLimitExceeded):
            await _call_with_retry(provider, [{"role": "user", "content": "x"}], "worker", 0.5, 100)

    # No retries — exactly one POST attempt
    assert post_mock.call_count == 1
