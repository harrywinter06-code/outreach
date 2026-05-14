"""API-key auth and plan enforcement."""
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import Header, HTTPException, status

from yield_system.db import connect

PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {"per_day": 100},
    "paid": {"per_day": 1_000_000},
}


def generate_api_key() -> str:
    return f"ys_{secrets.token_urlsafe(32)}"


def create_customer(experiment: str, email: str | None = None, plan: str = "free") -> dict:
    cid = uuid.uuid4().hex
    api_key = generate_api_key()
    with connect() as c:
        c.execute(
            "INSERT INTO customers(id, experiment, email, api_key, created_iso, plan) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, experiment, email, api_key, datetime.now(UTC).isoformat(), plan),
        )
    return {"customer_id": cid, "api_key": api_key, "plan": plan, "experiment": experiment}


def require_api_key(
    experiment: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-API-Key")
    with connect() as c:
        row = c.execute(
            "SELECT id, experiment, plan FROM customers WHERE api_key = ?",
            (x_api_key,),
        ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid X-API-Key")
    if row["experiment"] != experiment:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"key not valid for {experiment}")
    return {"customer_id": row["id"], "plan": row["plan"]}


def assert_within_daily_limit(customer_id: str, plan: str) -> None:
    limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["per_day"]
    today = datetime.now(UTC).date().isoformat()
    with connect() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM ledger "
            "WHERE experiment LIKE 'customer:' || ? AND ts_iso LIKE ?",
            (customer_id, f"{today}%"),
        ).fetchone()
    if int(row["n"]) >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"plan {plan} daily limit {limit} reached",
        )


def upgrade_customer(stripe_customer_id: str, internal_customer_id: str) -> None:
    with connect() as c:
        c.execute(
            "UPDATE customers SET plan = 'paid', stripe_customer_id = ? WHERE id = ?",
            (stripe_customer_id, internal_customer_id),
        )


def downgrade_customer(stripe_customer_id: str) -> None:
    with connect() as c:
        c.execute(
            "UPDATE customers SET plan = 'free' WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        )


def lookup_customer_by_email(email: str) -> str | None:
    with connect() as c:
        row = c.execute(
            "SELECT id FROM customers WHERE email = ? ORDER BY created_iso DESC LIMIT 1",
            (email,),
        ).fetchone()
    return row["id"] if row else None


def create_paid_customer(experiment: str, email: str, stripe_customer_id: str) -> str:
    """Create a customer record for someone who paid via a payment link (no prior signup)."""
    cid = uuid.uuid4().hex
    api_key = generate_api_key()
    with connect() as c:
        c.execute(
            "INSERT INTO customers(id, experiment, email, api_key, created_iso, plan, stripe_customer_id) "
            "VALUES (?, ?, ?, ?, ?, 'paid', ?)",
            (cid, experiment, email, api_key, datetime.now(UTC).isoformat(), stripe_customer_id),
        )
    return cid
