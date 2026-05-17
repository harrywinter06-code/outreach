"""Quick liveness check for Gumroad credentials. Run after setting GUMROAD_API_KEY.

  uv run python scripts/smoke_gumroad.py

Verifies: the token works, list_products responds, sales_last_7_days_gbp returns a number.
Does not write anything — read-only API calls.
"""
import asyncio
import sys

from clawbot.config import settings
from clawbot.gumroad import GumroadClient, GumroadAPIError


async def main() -> int:
    if not settings.gumroad_api_key:
        print("FAIL: GUMROAD_API_KEY not set in .env")
        return 1

    client = GumroadClient(api_key=settings.gumroad_api_key)
    try:
        products = await client.list_products()
    except GumroadAPIError as exc:
        print(f"FAIL: Gumroad rejected the token — {exc}")
        return 1
    except Exception as exc:
        print(f"FAIL: list_products raised {type(exc).__name__}: {exc}")
        return 1

    print(f"Products on this account ({len(products)}):")
    for p in products[:5]:
        print(f"  - {p.id}: {p.name} (£{p.price_gbp:.2f})")
    if not products:
        print("  (none — that's expected before you create the IR35 listing manually)")

    try:
        revenue = await client.sales_last_7_days_gbp()
    except Exception as exc:
        print(f"FAIL: sales_last_7_days_gbp raised {type(exc).__name__}: {exc}")
        return 1
    print(f"7-day revenue: £{revenue:.2f}")
    print("PASS — Gumroad is reachable, token valid")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
