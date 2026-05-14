"""Experiment C — Idempotent webhook retry queue."""
import hashlib
import json
import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel

from yield_system.db import connect
from yield_system.log import post_log, pre_log

EXPERIMENT = "webhookq"
router = APIRouter(prefix="/v1/webhookq", tags=[EXPERIMENT])

_RETENTION_DAYS_FREE = 7
_RETENTION_DAYS_PAID = 30


class EventRecord(BaseModel):
    id: int
    body_sha256: str
    idempotency_key: str | None
    received_iso: str
    headers: dict


class EventList(BaseModel):
    token: str
    events: list[EventRecord]
    next_cursor: int | None


class ReplayRequest(BaseModel):
    event_ids: list[int]
    target_url: str


class ReplayResult(BaseModel):
    delivered: int
    failed: int
    details: list[dict]


def generate_token() -> str:
    return f"whq_{secrets.token_urlsafe(20)}"


def _hash_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project() -> dict:
    token = generate_token()
    return {"token": token, "ingress_url": f"/v1/webhookq/ingress/{token}"}


@router.post("/ingress/{token}")
async def ingress(
    token: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    body = await request.body()
    body_hash = _hash_body(body)
    headers = {k.lower(): v for k, v in request.headers.items()}
    idem = idempotency_key or ""
    call_id = pre_log(
        experiment=f"token:{token}",
        action=f"ingress:{body_hash[:12]}",
        expected_cost_gbp=0.0,
        expected_outcome="200_or_409_dedup",
    )
    try:
        with connect() as c:
            c.execute(
                "INSERT INTO webhook_events(token, body_sha256, idempotency_key, "
                "payload, headers, received_iso) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    token,
                    body_hash,
                    idem,
                    body,
                    json.dumps(headers, separators=(",", ":")),
                    datetime.now(UTC).isoformat(),
                ),
            )
        post_log(call_id, "200_stored")
        return Response(
            content=json.dumps({"status": "stored", "body_sha256": body_hash}),
            status_code=200,
            media_type="application/json",
        )
    except Exception as e:
        # The only expected exception here is the UNIQUE-constraint violation
        # from the dedup index — surface it as 409 with the same hash so the
        # sender knows it was already accepted.
        if "UNIQUE" in str(e):
            post_log(call_id, "409_duplicate")
            return Response(
                content=json.dumps({"status": "duplicate", "body_sha256": body_hash}),
                status_code=409,
                media_type="application/json",
            )
        post_log(call_id, f"500_error:{type(e).__name__}")
        raise


@router.get("/events/{token}", response_model=EventList)
def list_events(token: str, cursor: int = 0, limit: int = 50) -> EventList:
    limit = min(max(limit, 1), 200)
    with connect() as c:
        rows = c.execute(
            "SELECT id, body_sha256, idempotency_key, headers, received_iso "
            "FROM webhook_events WHERE token = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (token, cursor, limit),
        ).fetchall()
    events = [
        EventRecord(
            id=int(r["id"]),
            body_sha256=r["body_sha256"],
            idempotency_key=r["idempotency_key"],
            received_iso=r["received_iso"],
            headers=json.loads(r["headers"]),
        )
        for r in rows
    ]
    next_cursor = events[-1].id if len(events) == limit else None
    return EventList(token=token, events=events, next_cursor=next_cursor)


@router.post("/egress/{token}", response_model=ReplayResult)
def replay(token: str, payload: ReplayRequest) -> ReplayResult:
    delivered = 0
    failed = 0
    details: list[dict] = []
    with connect() as c:
        placeholders = ",".join("?" * len(payload.event_ids))
        rows = c.execute(
            "SELECT id, payload, headers FROM webhook_events "  # noqa: S608
            f"WHERE token = ? AND id IN ({placeholders})",
            [token, *payload.event_ids],
        ).fetchall()
    for r in rows:
        cid = pre_log(
            experiment=f"token:{token}",
            action=f"replay:{r['id']}",
            expected_cost_gbp=0.0,
            expected_outcome="replay_delivered",
        )
        try:
            headers = json.loads(r["headers"])
            forward_headers = {
                k: v
                for k, v in headers.items()
                if k not in {"host", "content-length", "connection"}
            }
            resp = httpx.post(
                payload.target_url,
                content=r["payload"],
                headers=forward_headers,
                timeout=15.0,
            )
            ok = 200 <= resp.status_code < 300
            post_log(cid, f"replay_{resp.status_code}")
            if ok:
                delivered += 1
            else:
                failed += 1
            details.append({"id": r["id"], "status": resp.status_code})
        except httpx.HTTPError as e:
            post_log(cid, f"replay_error:{type(e).__name__}")
            failed += 1
            details.append({"id": r["id"], "error": type(e).__name__})
    return ReplayResult(delivered=delivered, failed=failed, details=details)


def purge_expired() -> int:
    """Delete events older than free-tier retention. Returns count deleted."""
    with connect() as c:
        row = c.execute(
            "DELETE FROM webhook_events WHERE received_iso < date('now', ?)",
            (f"-{_RETENTION_DAYS_FREE} days",),
        )
        return row.rowcount or 0


def purge_expired_paid() -> int:
    with connect() as c:
        row = c.execute(
            "DELETE FROM webhook_events WHERE received_iso < date('now', ?)",
            (f"-{_RETENTION_DAYS_PAID} days",),
        )
        return row.rowcount or 0
