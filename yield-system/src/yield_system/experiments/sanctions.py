"""Experiment A — Sanctions batch + delta webhook.

Sources (all public):
- OFAC SDN: https://www.treasury.gov/ofac/downloads/sdn.xml
- UK HMT (OFSI): https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.xml
- EU consolidated: requires registration via webgate.ec.europa.eu/fsd/fsf
"""
import re
import unicodedata
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from yield_system.auth import assert_within_daily_limit, require_api_key
from yield_system.db import connect
from yield_system.log import post_log, pre_log

EXPERIMENT = "sanctions"
router = APIRouter(prefix="/v1/sanctions", tags=[EXPERIMENT])

_NON_ALPHA = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    stripped = unicodedata.normalize("NFKD", name)
    ascii_only = stripped.encode("ascii", "ignore").decode().lower()
    return _NON_ALPHA.sub(" ", ascii_only).strip()


class ScreenRequest(BaseModel):
    names: list[str] = Field(..., min_length=1, max_length=1000)


class ScreenHit(BaseModel):
    input_name: str
    matched_name: str
    source: str
    source_id: str
    program: str | None
    aliases: list[str]


class ScreenResponse(BaseModel):
    requested: int
    matched: int
    hits: list[ScreenHit]


class WatchlistSubscription(BaseModel):
    watchlist_name: str
    name_to_match: str
    webhook_url: str


class WatchlistCreated(BaseModel):
    subscription_id: int
    name_normalized: str


def screen(names: list[str]) -> ScreenResponse:
    hits: list[ScreenHit] = []
    with connect() as c:
        for raw in names:
            normalized = normalize_name(raw)
            if not normalized:
                continue
            rows = c.execute(
                "SELECT name, source, source_id, program, aliases "
                "FROM sanctions_entries WHERE name_normalized = ?",
                (normalized,),
            ).fetchall()
            for row in rows:
                aliases = row["aliases"].split("|") if row["aliases"] else []
                hits.append(
                    ScreenHit(
                        input_name=raw,
                        matched_name=row["name"],
                        source=row["source"],
                        source_id=row["source_id"],
                        program=row["program"],
                        aliases=aliases,
                    )
                )
    return ScreenResponse(requested=len(names), matched=len(hits), hits=hits)


def _auth(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    return require_api_key(EXPERIMENT, x_api_key)


@router.post("/screen", response_model=ScreenResponse)
def post_screen(payload: ScreenRequest, customer: dict = Depends(_auth)) -> ScreenResponse:
    assert_within_daily_limit(customer["customer_id"], customer["plan"])
    call_id = pre_log(
        experiment=f"customer:{customer['customer_id']}",
        action=f"screen:{len(payload.names)}",
        expected_cost_gbp=0.0,
        expected_outcome="200_batch_screened",
    )
    result = screen(payload.names)
    post_log(call_id, f"200_matched_{result.matched}")
    return result


@router.post("/watchlist", response_model=WatchlistCreated)
def subscribe(payload: WatchlistSubscription, customer: dict = Depends(_auth)) -> WatchlistCreated:
    name_normalized = normalize_name(payload.name_to_match)
    if not name_normalized:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "name normalises to empty")
    with connect() as c:
        cur = c.execute(
            "INSERT INTO sanctions_subs(customer_id, watchlist_name, name_normalized, "
            "webhook_url, created_iso) VALUES (?, ?, ?, ?, ?)",
            (
                customer["customer_id"],
                payload.watchlist_name,
                name_normalized,
                payload.webhook_url,
                datetime.now(UTC).isoformat(),
            ),
        )
        sub_id = cur.lastrowid
    assert sub_id is not None
    return WatchlistCreated(subscription_id=sub_id, name_normalized=name_normalized)


def upsert_entry(
    source: str,
    source_id: str,
    name: str,
    aliases: list[str] | None = None,
    program: str | None = None,
) -> bool:
    """Returns True if entry is newly inserted; False if it already existed."""
    aliases_str = "|".join(aliases) if aliases else None
    with connect() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO sanctions_entries(source, source_id, name, "
            "name_normalized, aliases, program, added_iso) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source, source_id, name, normalize_name(name), aliases_str,
                program, datetime.now(UTC).isoformat(),
            ),
        )
        return cur.rowcount > 0


def fire_webhooks_for_new_entries(new_names_normalized: list[str]) -> int:
    fired = 0
    if not new_names_normalized:
        return 0
    with connect() as c:
        for name_norm in new_names_normalized:
            subs = c.execute(
                "SELECT webhook_url, customer_id, watchlist_name "
                "FROM sanctions_subs WHERE name_normalized = ?",
                (name_norm,),
            ).fetchall()
            for sub in subs:
                cid = pre_log(
                    experiment=EXPERIMENT,
                    action=f"webhook_fire:{sub['customer_id']}:{name_norm}",
                    expected_cost_gbp=0.0,
                    expected_outcome="webhook_delivered",
                )
                try:
                    r = httpx.post(
                        sub["webhook_url"],
                        json={
                            "watchlist": sub["watchlist_name"],
                            "matched": name_norm,
                            "id": uuid.uuid4().hex,
                        },
                        timeout=10.0,
                    )
                    post_log(cid, f"webhook_{r.status_code}")
                    if 200 <= r.status_code < 300:
                        fired += 1
                except httpx.HTTPError as e:
                    post_log(cid, f"webhook_error:{type(e).__name__}")
    return fired
