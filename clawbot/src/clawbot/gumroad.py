"""
Gumroad API v2 client.

Scope of this client:
- list_products() — GET /v2/products (works)
- sales_last_7_days_gbp() — GET /v2/sales with `after` date filter, paginated (works)
- create_product() — raises NotImplementedError; Gumroad's POST /v2/products returns
  404. Products must be created via the dashboard. The CTO agent must escalate
  product creation to the human operator via `ceo.directive` rather than attempting
  it autonomously.

Auth: query-string `access_token=<key>`. (Bearer headers also work; query string is
simpler and is what the Gumroad docs example uses.)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC

import httpx


GUMROAD_API = "https://api.gumroad.com/v2"
HTTP_TIMEOUT_S = 30.0


class GumroadAPIError(RuntimeError):
    pass


class GumroadProductCreationUnsupported(NotImplementedError):
    """Raised when an agent attempts to create a product via API.

    Gumroad's POST /v2/products endpoint is not implemented and returns 404.
    The operator must create products via the dashboard at gumroad.com.
    """


@dataclass(frozen=True)
class GumroadProduct:
    id: str
    name: str
    price_gbp: float
    url: str = ""
    currency: str = "gbp"


@dataclass(frozen=True)
class GumroadSale:
    sale_id: str
    product_id: str
    price_gbp: float
    created_at: datetime


class GumroadClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Gumroad access token required")
        self._key = api_key

    async def list_products(self) -> list[GumroadProduct]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            response = await client.get(
                f"{GUMROAD_API}/products",
                params={"access_token": self._key},
            )
            response.raise_for_status()
            body = response.json()
        if not body.get("success", False):
            raise GumroadAPIError(f"list_products failed: {body}")
        return [_parse_product(p) for p in body.get("products", [])]

    async def sales_last_7_days_gbp(self, now: datetime | None = None) -> float:
        """Sum of GBP sales over the last 7 days. Paginates until empty page."""
        sales = await self.sales(after=(now or datetime.now(UTC)) - timedelta(days=7))
        return sum(s.price_gbp for s in sales if s.price_gbp > 0)

    async def sales_by_day_gbp(self, days: int = 14) -> dict[str, float]:
        """GBP sales grouped by UTC date for the last `days` days."""
        after = datetime.now(UTC) - timedelta(days=days)
        sales = await self.sales(after=after)
        return _group_sales_by_day(sales, days)

    async def sales(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
        max_pages: int = 50,
    ) -> list[GumroadSale]:
        """Paginated GET /v2/sales. `after`/`before` are ISO date strings (YYYY-MM-DD)."""
        out: list[GumroadSale] = []
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            for page in range(1, max_pages + 1):
                params: dict[str, str | int] = {"access_token": self._key, "page": page}
                if after is not None:
                    params["after"] = after.strftime("%Y-%m-%d")
                if before is not None:
                    params["before"] = before.strftime("%Y-%m-%d")

                response = await client.get(f"{GUMROAD_API}/sales", params=params)
                response.raise_for_status()
                body = response.json()
                if not body.get("success", False):
                    raise GumroadAPIError(f"sales fetch failed page {page}: {body}")
                items = body.get("sales", [])
                if not items:
                    break
                out.extend(_parse_sale(s) for s in items)
        return out

    async def create_product(self, *_, **__) -> GumroadProduct:
        raise GumroadProductCreationUnsupported(
            "Gumroad's POST /v2/products endpoint returns 404. "
            "Products must be created via the Gumroad dashboard at gumroad.com. "
            "Escalate product creation to the human operator via ceo.directive."
        )


def _parse_product(p: dict) -> GumroadProduct:
    raw_price = p.get("price", 0)
    return GumroadProduct(
        id=str(p.get("id", "")),
        name=str(p.get("name", "")),
        price_gbp=_pence_to_gbp(raw_price),
        url=str(p.get("short_url") or p.get("url", "")),
        currency=str(p.get("currency", "gbp")),
    )


def _parse_sale(s: dict) -> GumroadSale:
    # Gumroad returns price in cents (smallest currency unit). For GBP, that is pence.
    raw_price = s.get("price", s.get("amount_refundable_in_currency", 0)) or 0
    created = s.get("created_at") or s.get("timestamp") or ""
    try:
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        created_dt = datetime.now(UTC)
    return GumroadSale(
        sale_id=str(s.get("id") or s.get("sale_id", "")),
        product_id=str(s.get("product_id", "")),
        price_gbp=_pence_to_gbp(raw_price),
        created_at=created_dt,
    )


def _pence_to_gbp(raw: float | int | str | None) -> float:
    """Gumroad returns prices as integer pence/cents. Convert to pounds."""
    if raw is None:
        return 0.0
    try:
        return float(raw) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _group_sales_by_day(sales: list[GumroadSale], days: int = 14) -> dict[str, float]:
    """Group sales amounts by UTC date for the last `days` days.

    Dates with no sales are included with 0.0 so callers get a complete sequence.
    """
    from datetime import timedelta as td
    today = datetime.now(UTC).date()
    result: dict[str, float] = {
        (today - td(days=i)).isoformat(): 0.0
        for i in range(days - 1, -1, -1)
    }
    for sale in sales:
        day = sale.created_at.date().isoformat()
        if day in result:
            result[day] = result[day] + sale.price_gbp
    return result
