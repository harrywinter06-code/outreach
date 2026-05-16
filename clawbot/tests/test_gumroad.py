import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from datetime import datetime, UTC, timedelta

from clawbot.gumroad import (
    GumroadClient,
    GumroadProductCreationUnsupported,
    GumroadAPIError,
    GumroadSale,
    _parse_product,
    _parse_sale,
    _pence_to_gbp,
    _group_sales_by_day,
)


def _mock_response(json_body: dict, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json = MagicMock(return_value=json_body)
    response.raise_for_status = MagicMock()
    return response


@pytest.mark.asyncio
async def test_list_products_parses_response():
    client = GumroadClient(api_key="test")
    body = {
        "success": True,
        "products": [
            {"id": "abc", "name": "IR35 Tool", "price": 900, "currency": "gbp", "short_url": "https://gumroad.com/l/ir35"},
        ],
    }
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.get = AsyncMock(return_value=_mock_response(body))
        products = await client.list_products()
    assert len(products) == 1
    assert products[0].id == "abc"
    assert products[0].price_gbp == 9.00
    assert products[0].url.endswith("/ir35")


@pytest.mark.asyncio
async def test_list_products_raises_on_unsuccessful_response():
    client = GumroadClient(api_key="test")
    body = {"success": False, "message": "bad token"}
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.get = AsyncMock(return_value=_mock_response(body))
        with pytest.raises(GumroadAPIError):
            await client.list_products()


@pytest.mark.asyncio
async def test_sales_paginates_until_empty_page():
    client = GumroadClient(api_key="test")
    pages = [
        _mock_response({"success": True, "sales": [
            {"id": "s1", "product_id": "abc", "price": 900, "created_at": "2026-05-10T10:00:00Z"},
            {"id": "s2", "product_id": "abc", "price": 900, "created_at": "2026-05-11T11:00:00Z"},
        ]}),
        _mock_response({"success": True, "sales": []}),
    ]
    get_mock = AsyncMock(side_effect=pages)
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.get = get_mock
        sales = await client.sales()
    assert len(sales) == 2
    assert get_mock.call_count == 2


@pytest.mark.asyncio
async def test_sales_last_7_days_gbp_sums_prices():
    client = GumroadClient(api_key="test")
    body = {"success": True, "sales": [
        {"id": "s1", "product_id": "abc", "price": 900, "created_at": "2026-05-10T10:00:00Z"},
        {"id": "s2", "product_id": "abc", "price": 1900, "created_at": "2026-05-11T11:00:00Z"},
    ]}
    pages = [_mock_response(body), _mock_response({"success": True, "sales": []})]
    with patch("httpx.AsyncClient") as ctx:
        ctx.return_value.__aenter__.return_value.get = AsyncMock(side_effect=pages)
        total = await client.sales_last_7_days_gbp()
    assert total == pytest.approx(28.00)


@pytest.mark.asyncio
async def test_create_product_raises_unsupported():
    """Gumroad POST /v2/products returns 404 — endpoint not implemented."""
    client = GumroadClient(api_key="test")
    with pytest.raises(GumroadProductCreationUnsupported) as excinfo:
        await client.create_product(name="X", price_gbp=9.0, description="...")
    assert "dashboard" in str(excinfo.value).lower()


def test_empty_api_key_rejected():
    with pytest.raises(ValueError):
        GumroadClient(api_key="")


def test_parse_product_handles_missing_fields():
    p = _parse_product({})
    assert p.id == ""
    assert p.price_gbp == 0.0


def test_parse_sale_falls_back_when_timestamp_invalid():
    s = _parse_sale({"id": "x", "price": 500, "created_at": "not-a-date"})
    assert s.price_gbp == 5.00
    assert s.created_at.tzinfo is not None  # fallback uses UTC


def test_pence_to_gbp_converts_int():
    assert _pence_to_gbp(900) == 9.00


def test_pence_to_gbp_handles_garbage():
    assert _pence_to_gbp("not-a-number") == 0.0


def _sale(price: float, days_ago: float = 0) -> GumroadSale:
    return GumroadSale("s1", "p1", price, datetime.now(UTC) - timedelta(days=days_ago))


class TestGroupSalesByDay:
    def test_empty_fills_zeros(self):
        result = _group_sales_by_day([], days=7)
        assert len(result) == 7
        assert all(v == 0.0 for v in result.values())

    def test_sums_same_day_sales(self):
        sales = [_sale(9.99), _sale(4.99)]
        result = _group_sales_by_day(sales, days=7)
        today = datetime.now(UTC).date().isoformat()
        assert abs(result[today] - 14.98) < 0.01

    def test_groups_different_days(self):
        sales = [_sale(9.99, days_ago=0), _sale(4.99, days_ago=1)]
        result = _group_sales_by_day(sales, days=7)
        today = datetime.now(UTC).date().isoformat()
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
        assert abs(result[today] - 9.99) < 0.01
        assert abs(result[yesterday] - 4.99) < 0.01

    def test_excludes_out_of_range_sales(self):
        sales = [_sale(99.0, days_ago=30)]
        result = _group_sales_by_day(sales, days=7)
        assert all(v == 0.0 for v in result.values())

    def test_returns_14_days_when_requested(self):
        result = _group_sales_by_day([], days=14)
        assert len(result) == 14
