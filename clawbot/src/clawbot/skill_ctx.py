"""Sandboxed execution context for organism-authored skills.

Skills receive ONLY a SkillCtx instance — no module imports, no globals,
no filesystem access outside the sandboxed roots. The reason this is a
hard boundary: an LLM-authored skill that imports `os` and shells out
defeats every other safety mechanism in the system.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED_NAMES = frozenset({"ctx", "run", "META", "self", "cls"})


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    params: dict[str, str]   # param_name -> type-hint string ("str", "int", "float", "bool", "list", "dict")
    returns: dict[str, str]  # field_name -> type-hint string
    cost_estimate_usd: float = 0.0
    requires_approval: bool = False
    timeout_s: float = 30.0
    builtin: bool = False    # True for _builtin/* skills; cannot be overwritten by forge

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(f"skill name {self.name!r} must be lowercase snake_case")
        if self.name in _RESERVED_NAMES:
            raise ValueError(f"skill name {self.name!r} is reserved")


@dataclass(frozen=True)
class SkillCallRecord:
    skill_name: str
    caller_id: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    cost_usd: float
    latency_ms: int
    ok: bool
    error: str | None


from typing import Protocol


class HttpClient(Protocol):
    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]: ...
    async def post(self, url: str, *, json: dict | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]: ...


class SqlClient(Protocol):
    async def query(self, sql: str, *args: Any) -> list[dict[str, Any]]: ...


class LlmClient(Protocol):
    async def complete(self, *, system: str, user: str, tier: str = "worker") -> str: ...


class VectorClient(Protocol):
    async def search(self, query: str, *, k: int = 5) -> list[dict[str, Any]]: ...
    async def write(self, text: str, *, kind: str, metadata: dict[str, Any] | None = None) -> str: ...


class SecretClient(Protocol):
    def get(self, name: str) -> str: ...


class FsClient(Protocol):
    async def read(self, path: str) -> str: ...
    async def write(self, path: str, content: str) -> None: ...
    async def list(self, path: str) -> list[str]: ...


class TimeClient(Protocol):
    def now_iso(self) -> str: ...
    def epoch_s(self) -> float: ...


class OperatorClient(Protocol):
    async def message(self, text: str, *, level: str = "info") -> None: ...
    async def request_approval(self, prompt: str, *, timeout_s: float = 3600) -> bool: ...


class BusClient(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> str: ...


class LogClient(Protocol):
    def info(self, msg: str, **kwargs: Any) -> None: ...
    def warn(self, msg: str, **kwargs: Any) -> None: ...
    def error(self, msg: str, **kwargs: Any) -> None: ...


class BrowserClient(Protocol):
    async def run(self, *, task: str, max_steps: int = 15) -> dict[str, Any]: ...


class PaymentsClient(Protocol):
    async def create_product(self, *, name: str, description: str) -> dict[str, Any]: ...
    async def create_price(self, *, product_id: str, amount_pence: int, currency: str = "gbp", recurring: bool = False) -> dict[str, Any]: ...
    async def create_payment_link(self, *, price_id: str, quantity: int = 1) -> dict[str, Any]: ...
    async def list_charges(self, *, limit: int = 20) -> list[dict[str, Any]]: ...
    async def refund(self, *, charge_id: str, amount_pence: int | None = None) -> dict[str, Any]: ...
    async def issue_card(self, *, cardholder_id: str, daily_limit_usd: int, agent_id: str) -> dict[str, Any]: ...
    async def freeze_card(self, *, card_id: str) -> dict[str, Any]: ...
    async def list_authorizations(self, *, card_id: str, limit: int = 20) -> list[dict[str, Any]]: ...


class SocialClient(Protocol):
    async def x_post(self, text: str, reply_to: str | None = None) -> dict[str, Any]: ...
    async def linkedin_post(self, text: str) -> dict[str, Any]: ...
    async def reddit_submit(self, subreddit: str, title: str, body: str | None = None, url: str | None = None) -> dict[str, Any]: ...
    async def reddit_comment(self, parent_id: str, body: str) -> dict[str, Any]: ...


class EmailClient(Protocol):
    async def send(self, to: str, subject: str, body_text: str, body_html: str | None = None, reply_to: str | None = None) -> dict[str, Any]: ...
    async def verify_address(self, address: str) -> dict[str, Any]: ...


class SearchClient(Protocol):
    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]: ...
    async def extract_url(self, url: str) -> dict[str, Any]: ...


class AccountsClient(Protocol):
    async def create_account(
        self, *, service: str, signup_url: str, notes: str = "",
    ) -> dict[str, Any]: ...
    async def get_account(self, *, service: str, email: str) -> dict[str, Any] | None: ...
    async def list_accounts(self, *, status: str | None = None) -> list[dict[str, Any]]: ...
    async def mark_zombie(self, *, service: str, email: str, reason: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SkillCtx:
    http: HttpClient
    sql: SqlClient
    llm: LlmClient
    vector: VectorClient
    secret: SecretClient
    fs: FsClient
    time: TimeClient
    operator: OperatorClient
    bus: BusClient
    log: LogClient
    browser: BrowserClient
    payments: PaymentsClient
    social: SocialClient
    email: EmailClient
    search: SearchClient
    accounts: AccountsClient
    caller_id: str
    budget_usd: float


# -- No-op stubs used by tests and shadow mode -------------------------------


class _NoopHttp:
    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return {"status": 200, "text": "", "headers": {}}

    async def post(self, url: str, *, json: dict | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        return {"status": 200, "text": "", "headers": {}}


class _NoopSql:
    async def query(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        return []


class _NoopLlm:
    async def complete(self, *, system: str, user: str, tier: str = "worker") -> str:
        return ""


class _NoopVector:
    async def search(self, query: str, *, k: int = 5) -> list[dict[str, Any]]:
        return []

    async def write(self, text: str, *, kind: str, metadata: dict[str, Any] | None = None) -> str:
        return "noop-id"


class _NoopSecret:
    def get(self, name: str) -> str:
        return ""


class _NoopFs:
    async def read(self, path: str) -> str:
        return ""

    async def write(self, path: str, content: str) -> None:
        pass

    async def list(self, path: str) -> list[str]:
        return []


class _NoopTime:
    def now_iso(self) -> str:
        return "1970-01-01T00:00:00+00:00"

    def epoch_s(self) -> float:
        return 0.0


class _NoopOperator:
    async def message(self, text: str, *, level: str = "info") -> None:
        pass

    async def request_approval(self, prompt: str, *, timeout_s: float = 3600) -> bool:
        return False


class _NoopBus:
    async def publish(self, topic: str, payload: dict[str, Any]) -> str:
        return "noop-msg-id"


class _NoopLog:
    def info(self, msg: str, **kwargs: Any) -> None: pass
    def warn(self, msg: str, **kwargs: Any) -> None: pass
    def error(self, msg: str, **kwargs: Any) -> None: pass


class _NoopBrowser:
    async def run(self, *, task: str, max_steps: int = 15) -> dict[str, Any]:
        return {"success": True, "output": "", "error": "", "task": task}


class _NoopPayments:
    async def create_product(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": "prod_noop_abc", **kwargs}

    async def create_price(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": "price_noop_abc", **kwargs}

    async def create_payment_link(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": "plink_noop_abc", "url": "https://buy.stripe.com/noop", **kwargs}

    async def list_charges(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def refund(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": "re_noop_abc", **kwargs}

    async def issue_card(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "id": "ic_noop_abc", "last4": "4242",
            "exp_month": 12, "exp_year": 2030, "status": "active",
            "cardholder": kwargs.get("cardholder_id", ""),
        }

    async def freeze_card(self, *, card_id: str) -> dict[str, Any]:
        return {"id": card_id, "status": "canceled"}

    async def list_authorizations(self, *, card_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return []


class _NoopSocial:
    async def x_post(self, text: str, reply_to: str | None = None) -> dict[str, Any]:
        return {"id": "noop_x_post"}

    async def linkedin_post(self, text: str) -> dict[str, Any]:
        return {"id": "noop_linkedin_post"}

    async def reddit_submit(self, subreddit: str, title: str, body: str | None = None, url: str | None = None) -> dict[str, Any]:
        return {"id": "noop_reddit_submit"}

    async def reddit_comment(self, parent_id: str, body: str) -> dict[str, Any]:
        return {"id": "noop_reddit_comment"}


class _NoopEmail:
    async def send(self, to: str, subject: str, body_text: str, body_html: str | None = None, reply_to: str | None = None) -> dict[str, Any]:
        return {"id": "noop_email", "ok": True}

    async def verify_address(self, address: str) -> dict[str, Any]:
        return {"deliverable": True, "score": 0.5}


class _NoopSearch:
    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        return []

    async def extract_url(self, url: str) -> dict[str, Any]:
        return {"url": url, "title": "", "markdown": ""}


class _NoopAccounts:
    async def create_account(
        self, *, service: str, signup_url: str, notes: str = "",
    ) -> dict[str, Any]:
        return {"status": "noop", "service": service, "email": "", "url": signup_url}

    async def get_account(self, *, service: str, email: str) -> dict[str, Any] | None:
        return None

    async def list_accounts(self, *, status: str | None = None) -> list[dict[str, Any]]:
        return []

    async def mark_zombie(self, *, service: str, email: str, reason: str) -> dict[str, Any]:
        return {"service": service, "email": email, "status": "zombie", "reason": reason}


def make_noop_ctx(*, caller_id: str, budget_usd: float) -> SkillCtx:
    return SkillCtx(
        http=_NoopHttp(), sql=_NoopSql(), llm=_NoopLlm(), vector=_NoopVector(),
        secret=_NoopSecret(), fs=_NoopFs(), time=_NoopTime(), operator=_NoopOperator(),
        bus=_NoopBus(), log=_NoopLog(), browser=_NoopBrowser(), payments=_NoopPayments(),
        social=_NoopSocial(), email=_NoopEmail(), search=_NoopSearch(),
        accounts=_NoopAccounts(),
        caller_id=caller_id, budget_usd=budget_usd,
    )


# -- Live implementations wired to real services ------------------------------

import asyncio
import os
import logging as _stdlib_logging
from datetime import datetime, UTC
from pathlib import Path

import httpx

try:
    import stripe  # type: ignore
except ImportError:
    stripe = None  # type: ignore


_PROTECTED_TOPICS = frozenset({
    "code.change_request",   # only CTOCoder consumes this; agents must use skill_request
    "operator.escalation",   # use operator.message skill
    "board.resolution",      # only board emits
})


class _LiveHttp:
    """HTTP client with timeout and response truncation to prevent prompt injection."""

    def __init__(self) -> None:
        self._timeout = 15.0
        self._max_chars = 8000

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            r = await client.get(url, headers=headers or {})
        return {"status": r.status_code, "text": r.text[: self._max_chars], "headers": dict(r.headers)}

    async def post(self, url: str, *, json: dict | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            r = await client.post(url, json=json, headers=headers or {})
        return {"status": r.status_code, "text": r.text[: self._max_chars], "headers": dict(r.headers)}


class _LiveSql:
    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool

    async def query(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        # Reject DDL at this layer — safety surface.
        # NOTE: only matches DDL at line start; multi-line DDL (DROP\nTABLE) passes.
        upper = sql.strip().upper()
        for forbidden in ("DROP ", "TRUNCATE ", "ALTER ", "CREATE "):
            if upper.startswith(forbidden):
                raise PermissionError(f"DDL not allowed via skill: {forbidden.strip()}")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]


class _LiveLlm:
    def __init__(self, pool: Any, caller_id: str) -> None:
        self._pool = pool
        self._caller = caller_id

    async def complete(self, *, system: str, user: str, tier: str = "worker") -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return await self._pool.complete(messages, tier=tier)  # type: ignore[no-any-return]


class _LiveVector:
    """Wraps CompanyBrain. Real method is search(query, k) not recall(query, k=k)."""

    def __init__(self, brain: Any, caller_id: str) -> None:
        self._brain = brain
        self._caller = caller_id

    async def search(self, query: str, *, k: int = 5) -> list[dict[str, Any]]:
        # CompanyBrain.search(query, k, category=None) → list[BrainEntry]
        results = await self._brain.search(query, k)
        return [r if isinstance(r, dict) else vars(r) for r in results]

    async def write(self, text: str, *, kind: str, metadata: dict[str, Any] | None = None) -> str:
        # CompanyBrain.write(content, category, metadata) → int (row id)
        row_id = await self._brain.write(text, kind, metadata or {"author": self._caller})
        return str(row_id)


class _LiveSecret:
    def __init__(self, allowlist: list[str]) -> None:
        self._allowlist = frozenset(allowlist)

    def get(self, name: str) -> str:
        if name not in self._allowlist:
            raise PermissionError(f"secret {name} not allowlisted for skills")
        return os.environ.get(name, "")


class _LiveFs:
    """Filesystem access scoped to workspace_root; defeats path-traversal via Path.resolve()."""

    def __init__(self, workspace_root: str, allowed_roots: list[str]) -> None:
        self._roots = [Path(workspace_root).resolve()] + [Path(r).resolve() for r in allowed_roots]

    def _check(self, path: str) -> Path:
        p = Path(path).resolve()
        if not any(str(p).startswith(str(r)) for r in self._roots):
            raise PermissionError(f"fs path outside allowed roots: {path}")
        return p

    async def read(self, path: str) -> str:
        return self._check(path).read_text(encoding="utf-8")

    async def write(self, path: str, content: str) -> None:
        p = self._check(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    async def list(self, path: str) -> list[str]:
        p = self._check(path)
        return [str(c) for c in p.iterdir()] if p.is_dir() else []


class _LiveTime:
    def now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def epoch_s(self) -> float:
        return datetime.now(UTC).timestamp()


class _LiveOperator:
    def __init__(self, escalation: Any, bus: Any, caller_id: str) -> None:
        self._esc = escalation
        self._bus = bus
        self._caller = caller_id

    async def message(self, text: str, *, level: str = "info") -> None:
        await self._esc.notify(text, level=level, source=self._caller)

    async def request_approval(self, prompt: str, *, timeout_s: float = 3600) -> bool:
        import uuid as _uuid
        request_id = _uuid.uuid4().hex
        await self._bus.publish("operator.approval_request", {
            "request_id": request_id, "prompt": prompt, "source": self._caller,
        })
        # Simple poll for reply on operator.approval_reply with matching request_id.
        # NOTE: uses MessageBus.read(topic, consumer_id, count, block_ms) — MVP approach.
        deadline = datetime.now(UTC).timestamp() + timeout_s
        while datetime.now(UTC).timestamp() < deadline:
            await asyncio.sleep(2)
            replies = await self._bus.read(
                "operator.approval_reply",
                consumer_id=f"approval-{request_id}",
                count=10,
                block_ms=1000,
            )
            for r in replies:
                if r.get("request_id") == request_id:
                    return bool(r.get("approved", False))
        return False


class _LiveBus:
    def __init__(self, bus: Any, caller_id: str) -> None:
        self._bus = bus
        self._caller = caller_id

    async def publish(self, topic: str, payload: dict[str, Any]) -> str:
        if topic in _PROTECTED_TOPICS:
            raise PermissionError(f"bus topic {topic} reserved")
        enriched = {**payload, "_published_by_skill": self._caller}
        return await self._bus.publish(topic, enriched)


class _LiveLog:
    def __init__(self, caller_id: str) -> None:
        self._logger = _stdlib_logging.getLogger(f"skill.{caller_id}")

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info("%s %s", msg, kwargs or "")

    def warn(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning("%s %s", msg, kwargs or "")

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error("%s %s", msg, kwargs or "")


class _LiveBrowser:
    """Per-skill browser handle. Caps concurrent Chromium instances at max_concurrent
    because the Hetzner CX21 only has 4GB RAM — three concurrent Chromiums + the
    container + redis + postgres + fastembed eats it.
    """

    def __init__(self, pool: Any, max_steps: int = 15, max_concurrent: int = 2) -> None:
        self._pool = pool
        self._max_steps = max_steps
        self._sem = asyncio.Semaphore(max_concurrent)

    async def run(self, *, task: str, max_steps: int = 15) -> dict[str, Any]:
        from clawbot.browser_worker import run_browser_task
        async with self._sem:
            result = await run_browser_task(task=task, pool=self._pool, max_steps=max_steps)
        return {
            "success": result.success, "output": result.output,
            "error": result.error, "task": task,
        }


class _LivePayments:
    """Stripe wrapper. Synchronous SDK calls are run on the default executor
    via asyncio.to_thread to avoid blocking the event loop."""

    def __init__(self, secret_key: str) -> None:
        if not secret_key:
            raise ValueError("STRIPE_SECRET_KEY not set — _LivePayments cannot operate")
        if stripe is None:
            raise RuntimeError("stripe SDK not installed")
        stripe.api_key = secret_key

    async def create_product(self, *, name: str, description: str) -> dict[str, Any]:
        prod = await asyncio.to_thread(stripe.Product.create, name=name, description=description)
        return prod.to_dict()

    async def create_price(self, *, product_id: str, amount_pence: int, currency: str = "gbp", recurring: bool = False) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"product": product_id, "unit_amount": amount_pence, "currency": currency}
        if recurring:
            kwargs["recurring"] = {"interval": "month"}
        price = await asyncio.to_thread(stripe.Price.create, **kwargs)
        return price.to_dict()

    async def create_payment_link(self, *, price_id: str, quantity: int = 1) -> dict[str, Any]:
        link = await asyncio.to_thread(
            stripe.PaymentLink.create,
            line_items=[{"price": price_id, "quantity": quantity}],
        )
        return link.to_dict()

    async def list_charges(self, *, limit: int = 20) -> list[dict[str, Any]]:
        charges = await asyncio.to_thread(stripe.Charge.list, limit=limit)
        return [c.to_dict() for c in charges.auto_paging_iter()][:limit]

    async def refund(self, *, charge_id: str, amount_pence: int | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"charge": charge_id}
        if amount_pence is not None:
            kwargs["amount"] = amount_pence
        ref = await asyncio.to_thread(stripe.Refund.create, **kwargs)
        return ref.to_dict()

    async def issue_card(
        self, *, cardholder_id: str, daily_limit_usd: int, agent_id: str,
    ) -> dict[str, Any]:
        amount_cents = daily_limit_usd * 100
        card = await asyncio.to_thread(
            stripe.issuing.Card.create,  # type: ignore[union-attr]
            cardholder=cardholder_id,
            currency="usd",
            type="virtual",
            spending_controls={
                "spending_limits": [
                    {"amount": amount_cents, "interval": "daily"},
                ],
            },
            metadata={"agent_id": agent_id},
        )
        result = card.to_dict()
        # Defensive: strip full PAN/CVC fields in case a future caller adds
        # ?expand=number,cvc. Last4 / expiry are safe to return.
        for sensitive in ("number", "cvc"):
            result.pop(sensitive, None)
        return result

    async def freeze_card(self, *, card_id: str) -> dict[str, Any]:
        card = await asyncio.to_thread(
            stripe.issuing.Card.modify, card_id, status="canceled",  # type: ignore[union-attr]
        )
        return card.to_dict()

    async def list_authorizations(self, *, card_id: str, limit: int = 20) -> list[dict[str, Any]]:
        # Use .data (first page) rather than auto_paging_iter — the iterator
        # would call Stripe repeatedly even though we slice to `limit` at the
        # end. limit is also passed to the API so the page size matches.
        auths = await asyncio.to_thread(
            stripe.issuing.Authorization.list, card=card_id, limit=limit,  # type: ignore[union-attr]
        )
        return [a.to_dict() for a in auths.data]


class _LiveSocial:
    """Social posting via X v2, LinkedIn UGC, and Reddit OAuth APIs."""

    def __init__(
        self,
        x_bearer: str,
        linkedin_token: str,
        reddit_creds: dict[str, str] | None,
    ) -> None:
        self._x_bearer = x_bearer
        self._linkedin_token = linkedin_token
        self._reddit_creds = reddit_creds
        self._timeout = 15.0

    async def x_post(self, text: str, reply_to: str | None = None) -> dict[str, Any]:
        if not self._x_bearer:
            raise ValueError("X_BEARER_TOKEN not set")
        body: dict[str, Any] = {"text": text[:280]}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                "https://api.twitter.com/2/tweets",
                json=body,
                headers={"Authorization": f"Bearer {self._x_bearer}"},
            )
            r.raise_for_status()
        return {"id": r.json()["data"]["id"]}

    async def linkedin_post(self, text: str) -> dict[str, Any]:
        if not self._linkedin_token:
            raise ValueError("LINKEDIN_ACCESS_TOKEN not set")
        headers = {
            "Authorization": f"Bearer {self._linkedin_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            me = await client.get("https://api.linkedin.com/v2/me", headers=headers)
            me.raise_for_status()
            person_urn = f"urn:li:person:{me.json()['id']}"
            payload = {
                "author": person_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": text},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            }
            r = await client.post("https://api.linkedin.com/v2/ugcPosts", json=payload, headers=headers)
            r.raise_for_status()
        return {"id": r.headers.get("x-restli-id", "")}

    async def _reddit_token(self, creds: dict[str, str]) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "password", "username": creds["username"], "password": creds["password"]},
                auth=(creds["client_id"], creds["client_secret"]),
                headers={"User-Agent": creds["user_agent"]},
            )
            r.raise_for_status()
        return r.json()["access_token"]  # type: ignore[no-any-return]

    async def reddit_submit(self, subreddit: str, title: str, body: str | None = None, url: str | None = None) -> dict[str, Any]:
        if not self._reddit_creds:
            raise ValueError("REDDIT_CREDS not set")
        token = await self._reddit_token(self._reddit_creds)
        kind = "link" if url else "self"
        post_data: dict[str, Any] = {"sr": subreddit, "title": title, "kind": kind}
        if url:
            post_data["url"] = url
        if body:
            post_data["text"] = body
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                "https://oauth.reddit.com/api/submit",
                data=post_data,
                headers={
                    "Authorization": f"bearer {token}",
                    "User-Agent": self._reddit_creds["user_agent"],
                },
            )
            r.raise_for_status()
        return {"id": r.json()["json"]["data"]["id"]}

    async def reddit_comment(self, parent_id: str, body: str) -> dict[str, Any]:
        if not self._reddit_creds:
            raise ValueError("REDDIT_CREDS not set")
        token = await self._reddit_token(self._reddit_creds)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                "https://oauth.reddit.com/api/comment",
                data={"thing_id": parent_id, "text": body},
                headers={
                    "Authorization": f"bearer {token}",
                    "User-Agent": self._reddit_creds["user_agent"],
                },
            )
            r.raise_for_status()
        return {"id": r.json()["json"]["data"]["things"][0]["data"]["id"]}


class _LiveEmail:
    """Resend outbound email + optional Bouncer address verification."""

    _EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

    def __init__(self, resend_key: str, from_address: str, bouncer_key: str = "") -> None:
        self._resend_key = resend_key
        self._from = from_address
        self._bouncer_key = bouncer_key
        self._timeout = 15.0

    async def send(self, to: str, subject: str, body_text: str, body_html: str | None = None, reply_to: str | None = None) -> dict[str, Any]:
        if not self._resend_key:
            raise ValueError("RESEND_API_KEY not set")
        body: dict[str, Any] = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "text": body_text,
        }
        if body_html:
            body["html"] = body_html
        if reply_to:
            body["reply_to"] = reply_to
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                json=body,
                headers={"Authorization": f"Bearer {self._resend_key}"},
            )
            r.raise_for_status()
        return {"id": r.json()["id"]}

    async def verify_address(self, address: str) -> dict[str, Any]:
        if self._bouncer_key:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(
                    f"https://api.usebouncer.com/v1.1/email/verify?email={address}",
                    headers={"x-api-key": self._bouncer_key},
                )
                r.raise_for_status()
            return r.json()  # type: ignore[no-any-return]
        deliverable = bool(self._EMAIL_RE.match(address))
        return {"deliverable": deliverable, "score": 0.5 if deliverable else 0.0}


class _LiveSearch:
    """Tavily-backed search + Firecrawl-backed URL extraction.

    Each method is independently optional: if only TAVILY_API_KEY is set,
    `search` works but `extract_url` returns an empty payload. Falling back
    to httpx for extract here is deliberately *not* done — the agent should
    use the existing http client for raw fetches and this client for
    LLM-clean output, so the two paths stay distinguishable in CAG logs."""

    def __init__(self, tavily_api_key: str, firecrawl_api_key: str) -> None:
        self._tavily_key = tavily_api_key
        self._firecrawl_key = firecrawl_api_key

    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
        from clawbot.tools import tavily
        if not self._tavily_key:
            return []
        return await tavily.search(
            api_key=self._tavily_key,
            query=query,
            max_results=max_results,
        )

    async def extract_url(self, url: str) -> dict[str, Any]:
        from clawbot.tools import firecrawl
        if not self._firecrawl_key:
            return {"url": url, "title": "", "markdown": ""}
        return await firecrawl.extract(api_key=self._firecrawl_key, url=url)


def make_live_ctx(
    *,
    caller_id: str,
    budget_usd: float,
    llm_pool: Any,
    bus: Any,
    brain: Any,
    db_pool: Any,
    escalation: Any,
    secret_allowlist: list[str],
    workspace_root: str,
    fs_allowed_roots: list[str] | None = None,
    stripe_secret_key: str = "",
    x_bearer: str = "",
    linkedin_token: str = "",
    reddit_creds: dict[str, str] | None = None,
    resend_api_key: str = "",
    email_from_address: str = "",
    bouncer_api_key: str = "",
    tavily_api_key: str = "",
    firecrawl_api_key: str = "",
) -> SkillCtx:
    """Build a SkillCtx wired to live services.

    fs_allowed_roots defaults to workspace_root plus the organism-writable
    directories (agents/skills, agents/workers, data). Skills CANNOT touch
    src/clawbot/ via fs — those edits go through coder.py.
    """
    extra_roots = fs_allowed_roots or []
    payments: PaymentsClient = (
        _LivePayments(stripe_secret_key) if stripe_secret_key else _NoopPayments()
    )
    social: SocialClient = (
        _LiveSocial(x_bearer, linkedin_token, reddit_creds)
        if (x_bearer or linkedin_token or reddit_creds)
        else _NoopSocial()
    )
    email: EmailClient = (
        _LiveEmail(resend_api_key, email_from_address, bouncer_api_key)
        if resend_api_key
        else _NoopEmail()
    )
    search: SearchClient = (
        _LiveSearch(tavily_api_key, firecrawl_api_key)
        if (tavily_api_key or firecrawl_api_key)
        else _NoopSearch()
    )
    return SkillCtx(
        http=_LiveHttp(),
        sql=_LiveSql(db_pool),
        llm=_LiveLlm(llm_pool, caller_id),
        vector=_LiveVector(brain, caller_id),
        secret=_LiveSecret(secret_allowlist),
        fs=_LiveFs(workspace_root, extra_roots),
        time=_LiveTime(),
        operator=_LiveOperator(escalation, bus, caller_id),
        bus=_LiveBus(bus, caller_id),
        log=_LiveLog(caller_id),
        browser=_LiveBrowser(pool=llm_pool),
        payments=payments,
        social=social,
        email=email,
        search=search,
        accounts=_NoopAccounts(),
        caller_id=caller_id,
        budget_usd=budget_usd,
    )
