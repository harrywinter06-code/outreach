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
    async def respond_to_dispute(self, *, dispute_id: str, evidence: dict[str, Any]) -> dict[str, Any]: ...


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


class RevenueClient(Protocol):
    """Multi-provider revenue surface: Gumroad reads, PayPal orders+transactions,
    Coinbase Commerce charges, Stripe subscriptions.

    Each provider section degrades to stub data when its credentials are absent —
    skills can call methods without first probing for config, and a missing key
    surfaces as a clearly-stubbed return rather than a raised exception."""

    # Gumroad
    async def gumroad_list_products(self) -> list[dict[str, Any]]: ...
    async def gumroad_sales_last_7d_gbp(self) -> float: ...
    async def gumroad_sales_today_gbp(self) -> float: ...
    async def gumroad_get_sale(self, *, sale_id: str) -> dict[str, Any]: ...
    # PayPal
    async def paypal_create_order(
        self, *, amount_gbp: float, return_url: str, cancel_url: str,
    ) -> dict[str, Any]: ...
    async def paypal_capture_order(self, *, order_id: str) -> dict[str, Any]: ...
    async def paypal_list_transactions(
        self, *, start_date: str, end_date: str,
    ) -> list[dict[str, Any]]: ...
    async def paypal_today_gbp(self) -> float: ...
    # Crypto via Coinbase Commerce
    async def crypto_generate_receive_address(
        self, *, amount_gbp: float, description: str,
    ) -> dict[str, Any]: ...
    async def crypto_check_balance(self, *, charge_id: str) -> dict[str, Any]: ...
    # Stripe subscriptions
    async def subscription_create(
        self, *, customer_id: str, price_id: str,
    ) -> dict[str, Any]: ...
    async def subscription_cancel(self, *, subscription_id: str) -> dict[str, Any]: ...


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


class DevClient(Protocol):
    async def exec_allowed_command(
        self, *, cmd_name: str, args: list[str], cwd: str,
    ) -> dict[str, Any]: ...


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
    revenue: RevenueClient
    media: MediaClient
    dev: DevClient
    caller_id: str
    budget_usd: float
    # Swarm Phase Z2.5 — attribution. When a skill call originates from a
    # business cycle, this carries the business_id; downstream code (the
    # skill_calls INSERT, the stripe payment-link metadata) reads it to
    # attribute work + revenue. NULL for executive / ad-hoc cycles.
    business_id: str | None = None


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

    async def respond_to_dispute(self, *, dispute_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        return {"id": dispute_id, "status": "noop", "evidence_submitted": True}


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


class _NoopRevenue:
    async def gumroad_list_products(self) -> list[dict[str, Any]]:
        return []

    async def gumroad_sales_last_7d_gbp(self) -> float:
        return 0.0

    async def gumroad_sales_today_gbp(self) -> float:
        return 0.0

    async def gumroad_get_sale(self, *, sale_id: str) -> dict[str, Any]:
        return {"sale_id": sale_id, "found": False}

    async def paypal_create_order(
        self, *, amount_gbp: float, return_url: str, cancel_url: str,
    ) -> dict[str, Any]:
        return {"id": "ORDER_NOOP", "status": "CREATED", "amount_gbp": amount_gbp,
                "approve_url": ""}

    async def paypal_capture_order(self, *, order_id: str) -> dict[str, Any]:
        return {"id": order_id, "status": "COMPLETED", "amount_gbp": 0.0}

    async def paypal_list_transactions(
        self, *, start_date: str, end_date: str,
    ) -> list[dict[str, Any]]:
        return []

    async def paypal_today_gbp(self) -> float:
        return 0.0

    async def crypto_generate_receive_address(
        self, *, amount_gbp: float, description: str,
    ) -> dict[str, Any]:
        return {"charge_id": "NOOP", "address": "", "currency": "BTC",
                "amount_gbp": amount_gbp, "hosted_url": ""}

    async def crypto_check_balance(self, *, charge_id: str) -> dict[str, Any]:
        return {"charge_id": charge_id, "status": "NEW", "paid_amount_gbp": 0.0}

    async def subscription_create(
        self, *, customer_id: str, price_id: str,
    ) -> dict[str, Any]:
        return {"id": "sub_noop_abc", "customer": customer_id,
                "status": "active", "price_id": price_id}

    async def subscription_cancel(self, *, subscription_id: str) -> dict[str, Any]:
        return {"id": subscription_id, "status": "canceled"}


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


class _NoopDev:
    async def exec_allowed_command(
        self, *, cmd_name: str, args: list[str], cwd: str,
    ) -> dict[str, Any]:
        return {"stdout": "", "stderr": "", "returncode": 0,
                "cmd_name": cmd_name, "args": args, "cwd": cwd}


def make_noop_ctx(
    *, caller_id: str, budget_usd: float, business_id: str | None = None,
) -> SkillCtx:
    return SkillCtx(
        http=_NoopHttp(), sql=_NoopSql(), llm=_NoopLlm(), vector=_NoopVector(),
        secret=_NoopSecret(), fs=_NoopFs(), time=_NoopTime(), operator=_NoopOperator(),
        bus=_NoopBus(), log=_NoopLog(), browser=_NoopBrowser(), payments=_NoopPayments(),
        social=_NoopSocial(), email=_NoopEmail(), search=_NoopSearch(),
        accounts=_NoopAccounts(),
        revenue=_NoopRevenue(),
        media=_NoopMedia(),
        dev=_NoopDev(),
        caller_id=caller_id, budget_usd=budget_usd, business_id=business_id,
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
        # escalation kept for backwards-compat with constructors that still
        # pass it; the message path always goes through the bus so the
        # EscalationStore subscriber persists + pushes uniformly.
        self._esc = escalation
        self._bus = bus
        self._caller = caller_id

    async def message(self, text: str, *, level: str = "info") -> None:
        # Bus-publish via escalate() — same path the scheduler's escalation
        # subscriber consumes. Decouples skills from any in-process escalation
        # object (router constructs make_live_ctx with escalation=None).
        from clawbot.escalation import escalate
        severity = level if level in ("info", "request", "warning", "urgent") else "info"
        await escalate(
            bus=self._bus, severity=severity,
            summary=text[:300], detail=text, from_agent=self._caller,
        )

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

    def __init__(
        self, secret_key: str,
        *,
        capital_ledger: Any = None,
        live_mode_enabled: bool = False,
        capital_daily_cap_gbp: Any = None,
        capital_weekly_cap_gbp: Any = None,
        capital_freeze: bool = False,
    ) -> None:
        from decimal import Decimal
        if not secret_key:
            raise ValueError("STRIPE_SECRET_KEY not set — _LivePayments cannot operate")
        if not secret_key.startswith(("sk_", "rk_")):
            raise ValueError(
                f"STRIPE_SECRET_KEY has unexpected prefix — got {secret_key[:8]!r}. "
                "Expected sk_live_, sk_test_, rk_live_, or rk_test_."
            )
        if stripe is None:
            raise RuntimeError("stripe SDK not installed")
        # Do NOT set stripe.api_key globally — concurrent instances would race.
        # Pass api_key= per-call instead (see every stripe.* call below).
        self._api_key = secret_key
        # Live-mode detection: positive identification of any production key prefix
        # (sk_live_, rk_live_, plus future variants Stripe may add).
        # Conservative: any key NOT containing "_test_" in the first 20 chars is live.
        self._is_live_key = "_test_" not in secret_key[:20]
        self._capital_ledger = capital_ledger
        self._live_mode_enabled = live_mode_enabled
        self._capital_daily_cap_gbp = Decimal(str(capital_daily_cap_gbp or 0))
        self._capital_weekly_cap_gbp = Decimal(str(capital_weekly_cap_gbp or 0))
        self._capital_freeze = capital_freeze

    async def _enforce_capital_gates(
        self, *, prospective_amount_gbp: "Decimal", agent_id: str,
    ) -> bool:
        """Returns True if the prospective spend is allowed. Raises RuntimeError
        with a specific cap-name on refusal. Returns True for test-mode (sk_test_)
        keys regardless of gates — test mode is a free playground."""
        from decimal import Decimal
        # Freeze is checked FIRST so operator's emergency-stop halts everything,
        # including test-mode probes that consume Stripe API quota.
        if self._capital_freeze:
            raise RuntimeError("capital_freeze_active — operator has halted all spending")
        # Test-mode keys bypass remaining gates (caps, live-mode checks).
        if not self._is_live_key:
            return True
        if not self._live_mode_enabled:
            raise RuntimeError("live_mode_not_enabled — operator has not graduated to live")
        if self._capital_daily_cap_gbp <= 0 or self._capital_weekly_cap_gbp <= 0:
            raise RuntimeError("capital_caps_not_set — daily and weekly caps must both be > 0 for live spend")
        if self._capital_ledger is None:
            raise RuntimeError("capital_ledger_not_wired — live mode requires ledger for cap enforcement")
        daily_spent = await self._capital_ledger.current_period_total_gbp(
            period_hours=24, live_only=True,
        )
        if daily_spent + prospective_amount_gbp > self._capital_daily_cap_gbp:
            raise RuntimeError(
                f"capital_cap_exceeded — daily: {daily_spent} + {prospective_amount_gbp} "
                f"> {self._capital_daily_cap_gbp}"
            )
        weekly_spent = await self._capital_ledger.current_period_total_gbp(
            period_hours=168, live_only=True,
        )
        if weekly_spent + prospective_amount_gbp > self._capital_weekly_cap_gbp:
            raise RuntimeError(
                f"capital_cap_exceeded — weekly: {weekly_spent} + {prospective_amount_gbp} "
                f"> {self._capital_weekly_cap_gbp}"
            )
        return True

    async def create_product(self, *, name: str, description: str) -> dict[str, Any]:
        prod = await asyncio.to_thread(
            stripe.Product.create, name=name, description=description, api_key=self._api_key,
        )
        return prod.to_dict()

    async def create_price(self, *, product_id: str, amount_pence: int, currency: str = "gbp", recurring: bool = False) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "product": product_id, "unit_amount": amount_pence,
            "currency": currency, "api_key": self._api_key,
        }
        if recurring:
            kwargs["recurring"] = {"interval": "month"}
        price = await asyncio.to_thread(stripe.Price.create, **kwargs)
        return price.to_dict()

    async def create_payment_link(self, *, price_id: str, quantity: int = 1) -> dict[str, Any]:
        from decimal import Decimal
        await self._enforce_capital_gates(
            prospective_amount_gbp=Decimal("0"), agent_id="system",
        )
        link = await asyncio.to_thread(
            stripe.PaymentLink.create,
            line_items=[{"price": price_id, "quantity": quantity}],
            api_key=self._api_key,
        )
        result = link.to_dict()
        # Record to ledger as a payment_link_created event (zero amount).
        if self._capital_ledger is not None:
            try:
                await self._capital_ledger.record(
                    agent_id="system",
                    action_type="payment_link_created",
                    amount_gbp=Decimal("0"),
                    is_live_mode=self._is_live_key,
                    stripe_object_id=result.get("id"),
                    metadata={"price_id": price_id, "quantity": quantity},
                )
            except Exception as exc:
                logger.warning("payment_link ledger record failed: %s", exc)
        return result

    async def list_charges(self, *, limit: int = 20) -> list[dict[str, Any]]:
        charges = await asyncio.to_thread(stripe.Charge.list, limit=limit, api_key=self._api_key)
        return [c.to_dict() for c in charges.auto_paging_iter()][:limit]

    async def refund(self, *, charge_id: str, amount_pence: int | None = None) -> dict[str, Any]:
        from decimal import Decimal
        kwargs: dict[str, Any] = {"charge": charge_id, "api_key": self._api_key}
        if amount_pence is not None:
            kwargs["amount"] = amount_pence
        ref = await asyncio.to_thread(stripe.Refund.create, **kwargs)
        result = ref.to_dict()
        # Record as a negative entry so the running total reflects net spend.
        if self._capital_ledger is not None:
            try:
                refund_gbp = Decimal(str(result.get("amount", 0))) / Decimal("100")
                if refund_gbp > 0:
                    await self._capital_ledger.record(
                        agent_id="system",
                        action_type="refund_processed",
                        amount_gbp=-refund_gbp,
                        is_live_mode=self._is_live_key,
                        stripe_object_id=result.get("id"),
                        metadata={"charge_id": charge_id},
                    )
            except Exception as exc:
                logger.warning("refund ledger record failed: %s", exc)
        return result

    async def issue_card(
        self, *, cardholder_id: str, daily_limit_usd: int, agent_id: str,
    ) -> dict[str, Any]:
        from decimal import Decimal
        # Validate before any side effects.
        if not isinstance(daily_limit_usd, int) or daily_limit_usd <= 0:
            raise ValueError(
                f"daily_limit_usd must be a positive integer, got {daily_limit_usd!r}"
            )
        prospective_gbp = Decimal(str(daily_limit_usd))
        await self._enforce_capital_gates(
            prospective_amount_gbp=prospective_gbp, agent_id=agent_id,
        )
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
            api_key=self._api_key,
        )
        result = card.to_dict()
        for sensitive in ("number", "cvc"):
            result.pop(sensitive, None)

        # Log to ledger AFTER Stripe success. If this fails, the card EXISTS
        # but is unaccounted — the next cap check would see a stale total and
        # allow further issuance. Freeze the card immediately and raise.
        if self._capital_ledger is not None:
            try:
                await self._capital_ledger.record(
                    agent_id=agent_id,
                    action_type="card_issued",
                    amount_gbp=prospective_gbp,
                    is_live_mode=self._is_live_key,
                    stripe_object_id=result.get("id"),
                    metadata={"cardholder_id": cardholder_id, "daily_limit_usd": daily_limit_usd},
                )
            except Exception as exc:
                # Critical: card minted, ledger missed it. Cancel the card
                # before returning so the cap isn't bypassed.
                try:
                    if stripe is not None:
                        await asyncio.to_thread(
                            stripe.issuing.Card.modify,  # type: ignore[union-attr]
                            result["id"], status="canceled",
                            api_key=self._api_key,
                        )
                except Exception:
                    pass  # already in a bad state — at least log it
                raise RuntimeError(
                    f"ledger_write_failed_after_stripe — card {result.get('id')} "
                    f"was canceled to maintain cap integrity. Original error: {exc}"
                ) from exc
        return result

    async def freeze_card(self, *, card_id: str) -> dict[str, Any]:
        card = await asyncio.to_thread(
            stripe.issuing.Card.modify, card_id, status="canceled",  # type: ignore[union-attr]
            api_key=self._api_key,
        )
        return card.to_dict()

    async def list_authorizations(self, *, card_id: str, limit: int = 20) -> list[dict[str, Any]]:
        # Use .data (first page) rather than auto_paging_iter — the iterator
        # would call Stripe repeatedly even though we slice to `limit` at the
        # end. limit is also passed to the API so the page size matches.
        auths = await asyncio.to_thread(
            stripe.issuing.Authorization.list, card=card_id, limit=limit,  # type: ignore[union-attr]
            api_key=self._api_key,
        )
        return [a.to_dict() for a in auths.data]

    async def respond_to_dispute(
        self, *, dispute_id: str, evidence: dict[str, Any],
    ) -> dict[str, Any]:
        dispute = await asyncio.to_thread(
            stripe.Dispute.modify, dispute_id, evidence=evidence,  # type: ignore[union-attr]
            api_key=self._api_key,
        )
        return dispute.to_dict()


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


class _LiveRevenue:
    """Multi-provider revenue surface backing _NoopRevenue's stub methods.

    Each provider is independently optional. If only GUMROAD_API_KEY is set,
    Gumroad methods work and the rest return stub data. The aggregate-today
    skill composes both ctx.payments (for Stripe charges) and ctx.revenue
    (for Gumroad+PayPal), so partial config still yields useful totals."""

    PAYPAL_LIVE = "https://api-m.paypal.com"
    PAYPAL_SANDBOX = "https://api-m.sandbox.paypal.com"
    COINBASE_API = "https://api.commerce.coinbase.com"
    COINBASE_API_VERSION = "2018-03-22"

    def __init__(
        self,
        *,
        gumroad_api_key: str = "",
        paypal_client_id: str = "",
        paypal_client_secret: str = "",
        paypal_environment: str = "live",
        coinbase_commerce_api_key: str = "",
        stripe_secret_key: str = "",
    ) -> None:
        self._gumroad_key = gumroad_api_key
        self._paypal_id = paypal_client_id
        self._paypal_secret = paypal_client_secret
        self._paypal_base = (
            self.PAYPAL_SANDBOX if paypal_environment == "sandbox" else self.PAYPAL_LIVE
        )
        self._coinbase_key = coinbase_commerce_api_key
        self._stripe_key = stripe_secret_key
        self._timeout = 20.0
        self._paypal_token: str = ""
        self._paypal_token_expiry: float = 0.0
        if stripe_secret_key and stripe is not None:
            stripe.api_key = stripe_secret_key

    # -- Gumroad ---------------------------------------------------------------

    def _gumroad(self) -> Any:
        from clawbot.gumroad import GumroadClient
        return GumroadClient(self._gumroad_key)

    async def gumroad_list_products(self) -> list[dict[str, Any]]:
        if not self._gumroad_key:
            return []
        products = await self._gumroad().list_products()
        return [
            {"id": p.id, "name": p.name, "price_gbp": p.price_gbp,
             "url": p.url, "currency": p.currency}
            for p in products
        ]

    async def gumroad_sales_last_7d_gbp(self) -> float:
        if not self._gumroad_key:
            return 0.0
        return await self._gumroad().sales_last_7_days_gbp()

    async def gumroad_sales_today_gbp(self) -> float:
        if not self._gumroad_key:
            return 0.0
        from datetime import datetime, timedelta, UTC
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        # sales(after=...) filters by YYYY-MM-DD — pass yesterday so today's
        # sales are returned (boundary inclusivity differs by Gumroad endpoint).
        sales = await self._gumroad().sales(after=today_start - timedelta(days=1))
        return sum(s.price_gbp for s in sales if s.created_at >= today_start)

    async def gumroad_get_sale(self, *, sale_id: str) -> dict[str, Any]:
        if not self._gumroad_key:
            return {"sale_id": sale_id, "found": False}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                f"https://api.gumroad.com/v2/sales/{sale_id}",
                params={"access_token": self._gumroad_key},
            )
        if r.status_code != 200:
            return {"sale_id": sale_id, "found": False, "status": r.status_code}
        body = r.json()
        sale = body.get("sale", {})
        return {
            "sale_id": sale_id, "found": bool(sale),
            "product_id": sale.get("product_id", ""),
            "price_gbp": float(sale.get("price", 0)) / 100.0,
            "email": sale.get("email", ""),
            "created_at": sale.get("created_at", ""),
        }

    # -- PayPal ----------------------------------------------------------------

    async def _paypal_oauth_token(self) -> str:
        from datetime import datetime, UTC
        now = datetime.now(UTC).timestamp()
        if self._paypal_token and now < self._paypal_token_expiry - 30:
            return self._paypal_token
        if not (self._paypal_id and self._paypal_secret):
            return ""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._paypal_base}/v1/oauth2/token",
                auth=(self._paypal_id, self._paypal_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
        body = r.json()
        self._paypal_token = body.get("access_token", "")
        self._paypal_token_expiry = now + float(body.get("expires_in", 0))
        return self._paypal_token

    async def paypal_create_order(
        self, *, amount_gbp: float, return_url: str, cancel_url: str,
    ) -> dict[str, Any]:
        token = await self._paypal_oauth_token()
        if not token:
            return {"id": "", "status": "no_creds", "amount_gbp": amount_gbp,
                    "approve_url": ""}
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {"currency_code": "GBP", "value": f"{amount_gbp:.2f}"},
            }],
            "application_context": {
                "return_url": return_url, "cancel_url": cancel_url,
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._paypal_base}/v2/checkout/orders",
                json=payload,
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
            )
            r.raise_for_status()
        body = r.json()
        approve_url = ""
        for link in body.get("links", []):
            if link.get("rel") == "approve":
                approve_url = link.get("href", "")
                break
        return {"id": body.get("id", ""), "status": body.get("status", ""),
                "amount_gbp": amount_gbp, "approve_url": approve_url}

    async def paypal_capture_order(self, *, order_id: str) -> dict[str, Any]:
        token = await self._paypal_oauth_token()
        if not token:
            return {"id": order_id, "status": "no_creds", "amount_gbp": 0.0}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._paypal_base}/v2/checkout/orders/{order_id}/capture",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
            )
            r.raise_for_status()
        body = r.json()
        captures = (
            body.get("purchase_units", [{}])[0]
                .get("payments", {}).get("captures", [{}])
        )
        first = captures[0] if captures else {}
        amount_str = first.get("amount", {}).get("value", "0")
        try:
            amount_gbp = float(amount_str)
        except (TypeError, ValueError):
            amount_gbp = 0.0
        return {"id": body.get("id", order_id), "status": body.get("status", ""),
                "amount_gbp": amount_gbp}

    async def paypal_list_transactions(
        self, *, start_date: str, end_date: str,
    ) -> list[dict[str, Any]]:
        token = await self._paypal_oauth_token()
        if not token:
            return []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                f"{self._paypal_base}/v1/reporting/transactions",
                params={"start_date": start_date, "end_date": end_date,
                        "fields": "transaction_info", "page_size": 100},
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
        body = r.json()
        out: list[dict[str, Any]] = []
        for entry in body.get("transaction_details", []):
            info = entry.get("transaction_info", {})
            amount = info.get("transaction_amount", {})
            try:
                value = float(amount.get("value", 0))
            except (TypeError, ValueError):
                value = 0.0
            out.append({
                "id": info.get("transaction_id", ""),
                "amount": value,
                "currency": amount.get("currency_code", ""),
                "status": info.get("transaction_status", ""),
                "date": info.get("transaction_initiation_date", ""),
            })
        return out

    async def paypal_today_gbp(self) -> float:
        from datetime import datetime, timedelta, UTC
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # PayPal API requires ISO 8601 with timezone; end_date inclusive.
        txns = await self.paypal_list_transactions(
            start_date=start.strftime("%Y-%m-%dT%H:%M:%S-0000"),
            end_date=(now + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S-0000"),
        )
        return sum(
            t["amount"] for t in txns
            if t.get("currency") == "GBP" and t.get("amount", 0) > 0
        )

    # -- Crypto (Coinbase Commerce) -------------------------------------------

    async def crypto_generate_receive_address(
        self, *, amount_gbp: float, description: str,
    ) -> dict[str, Any]:
        if not self._coinbase_key:
            return {"charge_id": "", "address": "", "currency": "BTC",
                    "amount_gbp": amount_gbp, "hosted_url": ""}
        payload = {
            "name": description[:100] or "Payment",
            "description": description[:200],
            "pricing_type": "fixed_price",
            "local_price": {"amount": f"{amount_gbp:.2f}", "currency": "GBP"},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.COINBASE_API}/charges",
                json=payload,
                headers={
                    "X-CC-Api-Key": self._coinbase_key,
                    "X-CC-Version": self.COINBASE_API_VERSION,
                    "Content-Type": "application/json",
                },
            )
            r.raise_for_status()
        body = r.json().get("data", {})
        addresses = body.get("addresses", {})
        btc_addr = addresses.get("bitcoin") or next(iter(addresses.values()), "")
        return {
            "charge_id": body.get("code", ""),
            "address": btc_addr,
            "currency": "BTC",
            "amount_gbp": amount_gbp,
            "hosted_url": body.get("hosted_url", ""),
        }

    async def crypto_check_balance(self, *, charge_id: str) -> dict[str, Any]:
        if not self._coinbase_key:
            return {"charge_id": charge_id, "status": "no_creds", "paid_amount_gbp": 0.0}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                f"{self.COINBASE_API}/charges/{charge_id}",
                headers={
                    "X-CC-Api-Key": self._coinbase_key,
                    "X-CC-Version": self.COINBASE_API_VERSION,
                },
            )
        if r.status_code != 200:
            return {"charge_id": charge_id, "status": "not_found",
                    "paid_amount_gbp": 0.0}
        body = r.json().get("data", {})
        payments = body.get("payments", [])
        paid_gbp = 0.0
        for p in payments:
            local = p.get("value", {}).get("local", {})
            try:
                paid_gbp += float(local.get("amount", 0))
            except (TypeError, ValueError):
                pass
        timeline = body.get("timeline", [])
        status = timeline[-1].get("status", "NEW") if timeline else "NEW"
        return {"charge_id": charge_id, "status": status, "paid_amount_gbp": paid_gbp}

    # -- Stripe subscriptions --------------------------------------------------

    async def subscription_create(
        self, *, customer_id: str, price_id: str,
    ) -> dict[str, Any]:
        if not self._stripe_key or stripe is None:
            return {"id": "", "customer": customer_id, "status": "no_creds",
                    "price_id": price_id}
        sub = await asyncio.to_thread(
            stripe.Subscription.create,  # type: ignore[union-attr]
            customer=customer_id,
            items=[{"price": price_id}],
        )
        d = sub.to_dict()
        return {"id": d.get("id", ""), "customer": d.get("customer", customer_id),
                "status": d.get("status", ""), "price_id": price_id}

    async def subscription_cancel(self, *, subscription_id: str) -> dict[str, Any]:
        if not self._stripe_key or stripe is None:
            return {"id": subscription_id, "status": "no_creds"}
        sub = await asyncio.to_thread(
            stripe.Subscription.cancel,  # type: ignore[union-attr]
            subscription_id,
        )
        d = sub.to_dict()
        return {"id": d.get("id", subscription_id), "status": d.get("status", "")}


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


_DEV_ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "npm_publish", "pip_wheel", "twine_upload",
    "docker_build", "docker_push", "docker_tag",
    "git_push", "git_clone",
})

_DEV_COMMAND_TEMPLATES: dict[str, list[str]] = {
    "npm_publish": ["npm", "publish"],
    "pip_wheel": ["python", "-m", "pip", "wheel", "."],
    "twine_upload": ["twine", "upload", "dist/*"],
    "docker_build": ["docker", "build"],
    "docker_push": ["docker", "push"],
    "docker_tag": ["docker", "tag"],
    "git_push": ["git", "push", "origin"],
    "git_clone": ["git", "clone", "--depth=1"],
}


class _LiveDev:
    """Allowlisted command execution for build/publish skills.

    The allowlist + path-traversal check on cwd is the trust boundary — even a
    compromised skill can only invoke commands in _DEV_ALLOWED_COMMANDS, and
    only within allowed_root. Arguments are passed as a list (no shell
    interpolation) so an attacker-controlled string can't break out via $().
    """

    def __init__(self, *, allowed_root: str) -> None:
        self._root = Path(allowed_root).resolve()

    async def exec_allowed_command(
        self, *, cmd_name: str, args: list[str], cwd: str,
    ) -> dict[str, Any]:
        if cmd_name not in _DEV_ALLOWED_COMMANDS:
            raise PermissionError(f"command {cmd_name!r} not in allowlist")
        p = Path(cwd).resolve()
        if not str(p).startswith(str(self._root)):
            raise PermissionError(f"cwd outside allowed root: {cwd}")
        import subprocess as _sp
        base = _DEV_COMMAND_TEMPLATES[cmd_name]
        full = base + list(args)
        proc = await asyncio.to_thread(
            _sp.run, full, cwd=str(p),
            capture_output=True, text=True, timeout=300, check=False,
        )
        return {
            "stdout": proc.stdout[-4000:] if proc.stdout else "",
            "stderr": proc.stderr[-4000:] if proc.stderr else "",
            "returncode": proc.returncode,
        }


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
    stripe_live_mode_enabled: bool = False,
    capital_daily_cap_gbp: float = 0.0,
    capital_weekly_cap_gbp: float = 0.0,
    capital_freeze: bool = False,
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
    gumroad_api_key: str = "",
    paypal_client_id: str = "",
    paypal_client_secret: str = "",
    paypal_environment: str = "live",
    coinbase_commerce_api_key: str = "",
    stability_api_key: str = "",
    runway_api_key: str = "",
    elevenlabs_api_key: str = "",
    openai_api_key: str = "",
    removebg_api_key: str = "",
    screenshot_api_key: str = "",
    dev_allowed_root: str = "",
    business_id: str | None = None,
) -> SkillCtx:
    """Build a SkillCtx wired to live services.

    fs_allowed_roots defaults to workspace_root plus the organism-writable
    directories (agents/skills, agents/workers, data). Skills CANNOT touch
    src/clawbot/ via fs — those edits go through coder.py.
    """
    extra_roots = fs_allowed_roots or []
    capital_ledger = None
    if db_pool is not None:
        try:
            from clawbot.capital_ledger import CapitalLedger
            capital_ledger = CapitalLedger(db_pool)
        except Exception:
            capital_ledger = None

    payments: PaymentsClient = (
        _LivePayments(
            stripe_secret_key,
            capital_ledger=capital_ledger,
            live_mode_enabled=stripe_live_mode_enabled,
            capital_daily_cap_gbp=capital_daily_cap_gbp,
            capital_weekly_cap_gbp=capital_weekly_cap_gbp,
            capital_freeze=capital_freeze,
        ) if stripe_secret_key else _NoopPayments()
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

    revenue: RevenueClient
    if (gumroad_api_key or paypal_client_id or coinbase_commerce_api_key
            or stripe_secret_key):
        revenue = _LiveRevenue(
            gumroad_api_key=gumroad_api_key,
            paypal_client_id=paypal_client_id,
            paypal_client_secret=paypal_client_secret,
            paypal_environment=paypal_environment,
            coinbase_commerce_api_key=coinbase_commerce_api_key,
            stripe_secret_key=stripe_secret_key,
        )
    else:
        revenue = _NoopRevenue()

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

    dev: DevClient = (
        _LiveDev(allowed_root=dev_allowed_root)
        if dev_allowed_root else _NoopDev()
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
        revenue=revenue,
        media=media,
        dev=dev,
        caller_id=caller_id,
        budget_usd=budget_usd,
        business_id=business_id,
    )
