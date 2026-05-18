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
_SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
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


class MediaClient(Protocol):
    async def image_generate(self, *, prompt: str, transparent_bg: bool = False, size: str = "1024x1024") -> dict[str, Any]: ...
    async def tts_generate(self, *, text: str, voice: str = "default", output_path: str) -> dict[str, Any]: ...
    async def screenshot_url(self, *, url: str, output_path: str, viewport: str = "1280x720") -> dict[str, Any]: ...
    async def stitch_audio(self, *, audio_paths: list[str], output_path: str) -> dict[str, Any]: ...
    async def annotate_image(self, *, input_path: str, output_path: str, annotations: list[dict[str, Any]]) -> dict[str, Any]: ...
    async def video_generate(self, *, prompt: str, duration_s: float = 4.0) -> dict[str, Any]: ...
    async def video_subtitle(self, *, video_path: str) -> dict[str, Any]: ...
    async def video_dub(self, *, video_path: str, target_lang: str) -> dict[str, Any]: ...
    async def image_remove_bg(self, *, image_url: str, output_path: str) -> dict[str, Any]: ...
    async def image_upscale(self, *, image_url: str, output_path: str, scale: int = 2) -> dict[str, Any]: ...


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
    media: MediaClient
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


class _NoopMedia:
    async def image_generate(self, *, prompt: str, transparent_bg: bool = False, size: str = "1024x1024") -> dict[str, Any]:
        return {"url": "https://noop/image.png", "prompt": prompt}

    async def tts_generate(self, *, text: str, voice: str = "default", output_path: str) -> dict[str, Any]:
        return {"path": output_path, "duration_s": 0.0}

    async def screenshot_url(self, *, url: str, output_path: str, viewport: str = "1280x720") -> dict[str, Any]:
        return {"path": output_path, "url": url}

    async def stitch_audio(self, *, audio_paths: list[str], output_path: str) -> dict[str, Any]:
        return {"path": output_path, "track_count": len(audio_paths)}

    async def annotate_image(self, *, input_path: str, output_path: str, annotations: list[dict[str, Any]]) -> dict[str, Any]:
        return {"path": output_path, "annotation_count": len(annotations)}

    async def video_generate(self, *, prompt: str, duration_s: float = 4.0) -> dict[str, Any]:
        return {"url": "https://noop/video.mp4", "prompt": prompt, "duration_s": duration_s}

    async def video_subtitle(self, *, video_path: str) -> dict[str, Any]:
        return {"srt": "", "video_path": video_path}

    async def video_dub(self, *, video_path: str, target_lang: str) -> dict[str, Any]:
        return {"url": "https://noop/dubbed.mp4", "target_lang": target_lang}

    async def image_remove_bg(self, *, image_url: str, output_path: str) -> dict[str, Any]:
        return {"path": output_path, "source_url": image_url}

    async def image_upscale(self, *, image_url: str, output_path: str, scale: int = 2) -> dict[str, Any]:
        return {"path": output_path, "scale": scale}


def make_noop_ctx(*, caller_id: str, budget_usd: float) -> SkillCtx:
    return SkillCtx(
        http=_NoopHttp(), sql=_NoopSql(), llm=_NoopLlm(), vector=_NoopVector(),
        secret=_NoopSecret(), fs=_NoopFs(), time=_NoopTime(), operator=_NoopOperator(),
        bus=_NoopBus(), log=_NoopLog(), browser=_NoopBrowser(), payments=_NoopPayments(),
        social=_NoopSocial(), email=_NoopEmail(), search=_NoopSearch(),
        accounts=_NoopAccounts(), media=_NoopMedia(),
        caller_id=caller_id, budget_usd=budget_usd,
    )


# -- Live implementations wired to real services ------------------------------

import asyncio
import os
import logging as _stdlib_logging
from datetime import datetime, UTC
from pathlib import Path

logger = _stdlib_logging.getLogger(__name__)

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


class _LiveAccounts:
    """Orchestrates autonomous account signup → verify → vault storage.

    The signup task is a single browser-use directive rather than a scripted
    DOM walk: browser-use's strength is self-healing across DOM changes, so
    we hand it the goal and let it find the form fields. The verification
    poll runs after browser success and times out into a zombie state if no
    mail arrives — better than blocking forever on a service that silently
    rate-limited us."""

    def __init__(
        self,
        *,
        vault: Any,
        profiles: Any,
        browser: Any,
        email_reader: Any,
        email_domain: str,
        verification_poll_timeout_s: float = 120.0,
        verification_poll_interval_s: float = 5.0,
    ) -> None:
        self._vault = vault
        self._profiles = profiles
        self._browser = browser
        self._email_reader = email_reader
        self._email_domain = email_domain
        self._verify_timeout = verification_poll_timeout_s
        self._verify_interval = verification_poll_interval_s

    async def create_account(
        self, *, service: str, signup_url: str, notes: str = "",
    ) -> dict[str, Any]:
        if not _SERVICE_NAME_RE.match(service):
            raise ValueError(
                f"service {service!r} must match {_SERVICE_NAME_RE.pattern!r}"
            )
        import secrets as _secrets
        import json as _json

        timestamp = int(datetime.now(UTC).timestamp())
        alias = f"{service}-{timestamp}-{_secrets.token_hex(4)}"
        email_addr = f"{alias}@{self._email_domain}"
        password = _secrets.token_hex(16)

        task = (
            f"Sign up for {service} at {signup_url}. "
            f"Use email '{email_addr}' and password '{password}'. "
            f"Complete any inline form fields needed. "
            f"After submitting, wait for the page that says a verification email was sent. "
            f"Then return the page's storage_state as JSON in your output."
        )
        browser_result = await self._browser.run(task=task, max_steps=30)
        if not browser_result.get("success"):
            err = browser_result.get("error", "unknown")
            self._vault.store(
                service=service, email=email_addr, password=password,
                cookies_json="", notes=f"signup failed: {err}",
            )
            self._vault.mark_zombie(
                service=service, email=email_addr,
                reason=f"browser failure: {err}",
            )
            return {"status": "zombie", "service": service, "email": email_addr,
                    "reason": f"browser failure: {err}"}

        verification = await self._poll_verification(alias)
        if verification is None:
            self._vault.store(
                service=service, email=email_addr, password=password,
                cookies_json="", notes="verification timeout",
            )
            self._vault.mark_zombie(
                service=service, email=email_addr,
                reason="verification mail not received in window",
            )
            return {"status": "zombie", "service": service, "email": email_addr,
                    "reason": "verification timeout"}

        # NOTE: verification.url may come from attacker-influenced mail. A
        # caller-side domain allowlist would tighten this, but v1 relies on the
        # alias-isolation in EmailReader plus browser-use's per-task sandbox.
        # TODO(security): allowlist verification.url netloc against signup_url netloc.
        verify_result: dict[str, Any] = {}
        if verification.url:
            verify_result = await self._browser.run(
                task=f"Open URL {verification.url} to complete signup verification. "
                     f"Return resulting storage_state.",
                max_steps=10,
            )
        elif verification.code:
            verify_result = await self._browser.run(
                task=f"On the current page, enter the verification code {verification.code}. "
                     f"Return resulting storage_state.",
                max_steps=10,
            )

        # Prefer storage_state from the post-verification call (real session
        # cookies live here). Fall back to the signup-call output if the
        # verification step didn't emit one.
        storage_state = self._extract_storage_state(verify_result.get("output", ""))
        if storage_state is None:
            storage_state = self._extract_storage_state(browser_result.get("output", ""))
        cookies_json = _json.dumps(storage_state) if storage_state else ""
        if storage_state:
            try:
                self._profiles.save(service, storage_state)
            except ValueError as exc:
                logger.warning(
                    "profile_save_rejected service=%s reason=%s — "
                    "account vaulted but next login will not benefit from saved state",
                    service, exc,
                )

        self._vault.store(
            service=service, email=email_addr, password=password,
            cookies_json=cookies_json, notes=notes,
        )
        return {"status": "live", "service": service, "email": email_addr, "url": signup_url}

    async def get_account(self, *, service: str, email: str) -> dict[str, Any] | None:
        rec = self._vault.get(service=service, email=email)
        if rec is None:
            return None
        return {
            "service": rec.service, "email": rec.email,
            "password": rec.password, "cookies_json": rec.cookies_json,
            "status": rec.status, "last_login_iso": rec.last_login_iso,
            "notes": rec.notes,
        }

    async def list_accounts(self, *, status: str | None = None) -> list[dict[str, Any]]:
        rows = self._vault.list_accounts(status=status)
        return [
            {"service": r.service, "email": r.email, "password": r.password,
             "cookies_json": r.cookies_json, "status": r.status,
             "last_login_iso": r.last_login_iso, "notes": r.notes}
            for r in rows
        ]

    async def mark_zombie(
        self, *, service: str, email: str, reason: str,
    ) -> dict[str, Any]:
        self._vault.mark_zombie(service=service, email=email, reason=reason)
        return {"service": service, "email": email, "status": "zombie", "reason": reason}

    async def _poll_verification(self, alias: str) -> Any:
        import time as _time
        deadline = _time.monotonic() + self._verify_timeout
        while _time.monotonic() < deadline:
            result = await self._email_reader.find_verification(
                alias=alias, since_minutes=10,
            )
            if result is not None:
                return result
            await asyncio.sleep(self._verify_interval)
        return None

    @staticmethod
    def _extract_storage_state(browser_output: str) -> dict[str, Any] | None:
        """browser-use may return free-form text or JSON. Best-effort extract."""
        import json as _json
        try:
            parsed = _json.loads(browser_output)
            if isinstance(parsed, dict) and "storage_state" in parsed:
                state = parsed["storage_state"]
                return state if isinstance(state, dict) else None
            return parsed if isinstance(parsed, dict) and "cookies" in parsed else None
        except _json.JSONDecodeError:
            return None


class _LiveMedia:
    """Media generation surface for skills.

    Each backend is independently optional via its env key; methods with no
    key configured return a no-op-shaped dict so skills compose without
    crashing. Provider request shapes here reflect best knowledge as of
    Jan 2026 — verify the exact endpoint and JSON contract for any provider
    before relying on it in production. Pillow is imported lazily inside
    annotate_image so the rest of the surface works even when Pillow is
    not installed.
    """

    def __init__(
        self,
        *,
        stability_api_key: str = "",
        runway_api_key: str = "",
        elevenlabs_api_key: str = "",
        openai_api_key: str = "",
        removebg_api_key: str = "",
        screenshot_api_key: str = "",
    ) -> None:
        self._stability_key = stability_api_key
        self._runway_key = runway_api_key
        self._elevenlabs_key = elevenlabs_api_key
        self._openai_key = openai_api_key
        self._removebg_key = removebg_api_key
        self._screenshot_key = screenshot_api_key
        self._timeout = 60.0

    async def image_generate(self, *, prompt: str, transparent_bg: bool = False, size: str = "1024x1024") -> dict[str, Any]:
        if not self._stability_key:
            return {"url": "", "prompt": prompt}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                "https://api.stability.ai/v2beta/stable-image/generate/core",
                headers={"Authorization": f"Bearer {self._stability_key}", "Accept": "application/json"},
                files={"prompt": (None, prompt),
                       "output_format": (None, "png"),
                       "size": (None, size)},
            )
            r.raise_for_status()
        payload = r.json()
        return {"url": payload.get("image", ""), "prompt": prompt, "transparent_bg": transparent_bg}

    async def tts_generate(self, *, text: str, voice: str = "default", output_path: str) -> dict[str, Any]:
        if not self._elevenlabs_key:
            return {"path": output_path, "duration_s": 0.0}
        voice_id = voice if voice != "default" else "21m00Tcm4TlvDq8ikWAM"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": self._elevenlabs_key, "accept": "audio/mpeg"},
                json={"text": text, "model_id": "eleven_multilingual_v2"},
            )
            r.raise_for_status()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(r.content)
        return {"path": output_path, "duration_s": float(len(r.content)) / 16000.0}

    async def screenshot_url(self, *, url: str, output_path: str, viewport: str = "1280x720") -> dict[str, Any]:
        if not self._screenshot_key:
            return {"path": output_path, "url": url}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                "https://api.screenshotone.com/take",
                params={"access_key": self._screenshot_key, "url": url,
                        "viewport_width": viewport.split("x")[0],
                        "viewport_height": viewport.split("x")[1],
                        "format": "png"},
            )
            r.raise_for_status()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(r.content)
        return {"path": output_path, "url": url}

    async def stitch_audio(self, *, audio_paths: list[str], output_path: str) -> dict[str, Any]:
        if not audio_paths:
            return {"path": output_path, "track_count": 0}
        import subprocess as _sp  # noqa: S404 — ffmpeg shellout is intentional, args are file paths only
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        list_file = Path(output_path).with_suffix(".concat.txt")
        list_file.write_text(
            "\n".join(f"file '{Path(p).as_posix()}'" for p in audio_paths),
            encoding="utf-8",
        )
        proc = await asyncio.to_thread(
            _sp.run,
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", output_path],
            capture_output=True, text=True, timeout=300,
        )
        list_file.unlink(missing_ok=True)
        return {"path": output_path, "track_count": len(audio_paths),
                "ffmpeg_rc": proc.returncode}

    async def annotate_image(self, *, input_path: str, output_path: str, annotations: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            from PIL import Image, ImageDraw  # type: ignore
        except ImportError:
            return {"path": input_path, "annotation_count": 0, "error": "Pillow not installed"}
        img = Image.open(input_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        for ann in annotations:
            kind = ann.get("type", "box")
            colour = ann.get("colour", "red")
            if kind == "box" and "xyxy" in ann:
                x0, y0, x1, y1 = ann["xyxy"]
                draw.rectangle([x0, y0, x1, y1], outline=colour, width=int(ann.get("width", 3)))
            elif kind == "arrow" and "xyxy" in ann:
                x0, y0, x1, y1 = ann["xyxy"]
                draw.line([x0, y0, x1, y1], fill=colour, width=int(ann.get("width", 3)))
            elif kind == "text" and "xy" in ann and "text" in ann:
                draw.text(ann["xy"], ann["text"], fill=colour)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path)
        return {"path": output_path, "annotation_count": len(annotations)}

    async def video_generate(self, *, prompt: str, duration_s: float = 4.0) -> dict[str, Any]:
        if not self._runway_key:
            return {"url": "", "prompt": prompt, "duration_s": duration_s}
        async with httpx.AsyncClient(timeout=self._timeout * 3) as client:
            r = await client.post(
                "https://api.runwayml.com/v1/text_to_video",
                headers={"Authorization": f"Bearer {self._runway_key}",
                         "X-Runway-Version": "2024-11-06"},
                json={"prompt": prompt, "duration": duration_s, "ratio": "1280:720"},
            )
            r.raise_for_status()
        payload = r.json()
        return {"url": payload.get("output", {}).get("url", ""),
                "prompt": prompt, "duration_s": duration_s}

    async def video_subtitle(self, *, video_path: str) -> dict[str, Any]:
        if not self._openai_key:
            return {"srt": "", "video_path": video_path}
        async with httpx.AsyncClient(timeout=self._timeout * 3) as client:
            with Path(video_path).open("rb") as fh:
                r = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._openai_key}"},
                    data={"model": "whisper-1", "response_format": "srt"},
                    files={"file": (Path(video_path).name, fh, "video/mp4")},
                )
                r.raise_for_status()
        return {"srt": r.text, "video_path": video_path}

    async def video_dub(self, *, video_path: str, target_lang: str) -> dict[str, Any]:
        if not self._elevenlabs_key:
            return {"url": "", "target_lang": target_lang}
        async with httpx.AsyncClient(timeout=self._timeout * 3) as client:
            with Path(video_path).open("rb") as fh:
                r = await client.post(
                    "https://api.elevenlabs.io/v1/dubbing",
                    headers={"xi-api-key": self._elevenlabs_key},
                    data={"target_lang": target_lang, "source_lang": "auto"},
                    files={"file": (Path(video_path).name, fh, "video/mp4")},
                )
                r.raise_for_status()
        payload = r.json()
        return {"url": payload.get("dubbing_id", ""), "target_lang": target_lang}

    async def image_remove_bg(self, *, image_url: str, output_path: str) -> dict[str, Any]:
        if not self._removebg_key:
            return {"path": output_path, "source_url": image_url}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                "https://api.remove.bg/v1.0/removebg",
                headers={"X-Api-Key": self._removebg_key},
                data={"image_url": image_url, "size": "auto"},
            )
            r.raise_for_status()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(r.content)
        return {"path": output_path, "source_url": image_url}

    async def image_upscale(self, *, image_url: str, output_path: str, scale: int = 2) -> dict[str, Any]:
        if not self._stability_key:
            return {"path": output_path, "scale": scale}
        async with httpx.AsyncClient(timeout=self._timeout * 2) as client:
            img = await client.get(image_url)
            img.raise_for_status()
            r = await client.post(
                "https://api.stability.ai/v2beta/stable-image/upscale/fast",
                headers={"Authorization": f"Bearer {self._stability_key}",
                         "Accept": "image/*"},
                files={"image": ("input.png", img.content, "image/png")},
            )
            r.raise_for_status()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(r.content)
        return {"path": output_path, "scale": scale}


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
    accounts_vault_key: str = "",
    accounts_db_path: str = "data/accounts.db",
    imap_host: str = "",
    imap_port: int = 993,
    imap_user: str = "",
    imap_password: str = "",
    email_domain: str = "",
    stability_api_key: str = "",
    runway_api_key: str = "",
    elevenlabs_api_key: str = "",
    openai_api_key: str = "",
    removebg_api_key: str = "",
    screenshot_api_key: str = "",
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

    # Single _LiveBrowser shared by SkillCtx.browser and _LiveAccounts so the
    # CX21's 4GB RAM cap is honoured — two instances would double the concurrent
    # Chromium ceiling (2 each → 4 total) and oom the container.
    browser_client = _LiveBrowser(pool=llm_pool)

    accounts: AccountsClient
    if accounts_vault_key and imap_host and email_domain:
        from clawbot.accounts_store import AccountsStore
        from clawbot.profile_store import ProfileStore
        from clawbot.email_reader import EmailReader
        vault = AccountsStore(db_path=accounts_db_path, encryption_key=accounts_vault_key)
        vault.init_schema()
        profiles = ProfileStore(root="data/profiles")
        email_reader = EmailReader(
            host=imap_host, port=imap_port,
            user=imap_user, password=imap_password,
            domain=email_domain,
        )
        accounts = _LiveAccounts(
            vault=vault, profiles=profiles,
            browser=browser_client, email_reader=email_reader,
            email_domain=email_domain,
        )
    else:
        accounts = _NoopAccounts()

    media: MediaClient = (
        _LiveMedia(
            stability_api_key=stability_api_key, runway_api_key=runway_api_key,
            elevenlabs_api_key=elevenlabs_api_key, openai_api_key=openai_api_key,
            removebg_api_key=removebg_api_key, screenshot_api_key=screenshot_api_key,
        )
        if (stability_api_key or runway_api_key or elevenlabs_api_key
            or openai_api_key or removebg_api_key or screenshot_api_key)
        else _NoopMedia()
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
        browser=browser_client,
        payments=payments,
        social=social,
        email=email,
        search=search,
        accounts=accounts,
        media=media,
        caller_id=caller_id,
        budget_usd=budget_usd,
    )
