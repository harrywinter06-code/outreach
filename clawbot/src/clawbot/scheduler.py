"""
Cadence orchestrator — drives all periodic agent activities.

Loops:
- _executive_loop: CEO + other executives think every 10 min (or 60 min overnight).
- _board_loop: shareholder vote at 03:00 UTC daily, quorum-aware with retry.
- _evolution_loop: meta-evaluator mutates bottom-20% agents every 24h.
- _dynamic_agent_sync_loop: registry → asyncio.Task per worker, started/cancelled
  as the org chart changes. Without this, workers spawned by agent_factory
  register in Redis but never execute — organisational silent paralysis.
- _kill_switch_watchdog: file + Redis kill check every 30s.

Skeleton-crew gate (Charter §Safety): between 23:00–06:00 UTC the executive loop
sleeps for 60 min instead of 10 min and evolution is skipped, preserving NIM
budget for peak hours.
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid as _uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING

from clawbot.agent_registry import AgentRegistry, AgentSpec, EXECUTIVE_IDS
from clawbot.board import (
    BoardVotingSystem, BoardVote, QuorumNotReached, SHAREHOLDERS,
)
from clawbot.bus import MessageBus
from clawbot.chat import OperatorInbox, OPERATOR_MESSAGE_TOPIC, respond_to_operator
from clawbot.coder import CTOCoder, CHANGE_RESULT_TOPIC
from clawbot.company_brain import CompanyBrain
from clawbot.escalation import (
    ESCALATION_TOPIC, REPLY_TOPIC, Escalation, EscalationStore, ReplyStore, escalate,
)
from clawbot.config import settings
from clawbot.fitness import FitnessScore
from clawbot.llm_pool import LLMPool
from clawbot.metrics import MetricsStore
from clawbot.monitor import Monitor
from clawbot.opportunity_scanner import OpportunityScanner, REDDIT_INTERVAL_S

if TYPE_CHECKING:
    from clawbot.causal_store import CausalStore
    from clawbot.homeostasis import Homeostasis
    from clawbot.task_store import TaskStore

from clawbot.plan_store import PlanStore
from clawbot.hypothesis_store import HypothesisStore

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
METRICS_DIR = Path("/metrics")

EXECUTIVE_PEAK_INTERVAL_S = 600
EXECUTIVE_SKELETON_INTERVAL_S = 3600
REGISTRY_SYNC_INTERVAL_S = 60
KILL_WATCHDOG_INTERVAL_S = 30
CAPITAL_CAP_CHECK_INTERVAL_S = 300         # check capital cap proximity every 5 min
EVOLUTION_POLL_INTERVAL_S = 3600           # check every hour whether to fire
EVOLUTION_MAX_INTERVAL_S = 7 * 86_400      # never wait longer than 7 days
EVOLUTION_REVENUE_EPSILON_GBP = 1.0        # ≥£1 7d-revenue delta triggers fire
EVOLUTION_BOOTSTRAP_FLAT_DAYS = 3          # ≥3 days at £0 → fire daily regardless of delta
SHAREHOLDER_VOTE_RETRIES = 2  # collect → retry missing → retry missing → tally
DRIFT_AUDIT_INTERVAL_S = 86_400            # once daily
CANDIDATE_ARBITER_INTERVAL_S = 86_400      # once daily
CANDIDATE_WINDOW_S = 14 * 86_400           # candidate runs for 14 days before promotion check
CANDIDATE_PROMOTION_MARGIN = 1.01          # candidate must beat production by ≥1% to promote
FITNESS_WRITER_INTERVAL_S = 3600           # recompute fitness.json every hour
EXPLORATION_CYCLE_INTERVAL_S = 7 * 86_400  # weekly candidate variant for top performer
OPERATOR_REPLY_POLL_INTERVAL_S = 60        # how often to check escalation_replies.jsonl
OPERATOR_INBOX_POLL_INTERVAL_S = 10        # chat-grade latency for inbound operator messages
BRAIN_RETENTION_INTERVAL_S = 86_400        # daily prune of high-write brain categories
BRAIN_MARKET_SIGNAL_MAX_AGE_DAYS = 14      # market signals decay fast; 14d is more than enough
BRAIN_RECALL_MIN_QUERY_CHARS = 20          # below this, the query is too trivial for similarity to mean anything
LATERAL_THINKER_INTERVAL_S = 7 * 86_400    # weekly

_WAKEUP_FLOOR_S = 60
_WAKEUP_CEILING_S = 1800
_BUDGET_ANTIWINDUP_THRESHOLD = 0.70


def _clamp_wakeup(wakeup_s: int | float, budget_fraction: float = 0.0) -> int:
    """Clamp agent-declared wakeup interval within safe bounds.

    Anti-windup: if daily budget consumption >= 70%, force maximum interval.
    """
    if budget_fraction >= _BUDGET_ANTIWINDUP_THRESHOLD:
        return _WAKEUP_CEILING_S
    return max(_WAKEUP_FLOOR_S, min(_WAKEUP_CEILING_S, int(wakeup_s)))


def _is_skeleton_crew_hour(now: datetime | None = None) -> bool:
    """Charter §Safety: skeleton crew 23:00–06:00 UTC to preserve NIM budget."""
    hour = (now or datetime.now(UTC)).hour
    return hour >= 23 or hour < 6


def _should_diversify_for_hypothesis(
    *,
    age_days: float,
    progress_score: float,
    portfolio_size: int,
    max_active: int,
    kill_max_days: int,
) -> bool:
    """Pure-function diversification trigger.

    Spawn a new hypothesis when:
    - The existing hypothesis is past 50% of its kill window
    - AND progress on it is below 20%
    - AND the portfolio has room (< max_active)

    All three must hold. Each guards against a failure mode:
    - Time-fraction guard: don't spawn for bets that just started
    - Progress guard: don't spawn alongside working bets
    - Capacity guard: don't exceed the substrate's resource floor
    """
    if portfolio_size >= max_active:
        return False
    if kill_max_days <= 0:
        return False
    time_fraction = age_days / kill_max_days
    if time_fraction < 0.5:
        return False
    if progress_score >= 0.20:
        return False
    return True


import re as _re


def _parse_product_reply(reply: str) -> tuple[str | None, str | None]:
    """Extract Gumroad product URL and chain_id from an operator reply string.

    Expected format: PRODUCT_URL:<url> CHAIN:<chain_id>
    Returns (url, chain_id) or (None, None) if format not matched.
    """
    url_match = _re.search(r"PRODUCT_URL:\s*(https?://\S+)", reply)
    chain_match = _re.search(r"CHAIN:\s*(\S+)", reply)
    if not url_match or not chain_match:
        return None, None
    return url_match.group(1).strip(), chain_match.group(1).strip()


def _extract_gumroad_product_id(url: str) -> str | None:
    """Extract Gumroad product ID from a product URL.

    Gumroad URLs: https://gumroad.com/l/<id> or https://<seller>.gumroad.com/l/<id>
    """
    match = _re.search(r"/l/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


def _extract_json(text: str) -> dict:
    """Return the first JSON object in text, stripping markdown fences if present."""
    import re
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    blob = match.group(1) if match else text
    start = blob.find("{")
    end = blob.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return json.loads(blob[start : end + 1])


async def _maybe_escalate(bus: MessageBus, response: str | None, agent_id: str) -> None:
    """Parse an executive JSON response and publish to operator.escalation if requested."""
    if not response:
        return
    try:
        data = _extract_json(response)
    except Exception:
        return
    esc = data.get("escalate")
    if not esc or not isinstance(esc, dict):
        return
    summary = str(esc.get("summary", ""))[:300]
    detail = str(esc.get("detail", summary))[:4000]
    severity = esc.get("severity", "info")
    if severity not in ("info", "request", "warning", "urgent"):
        severity = "info"
    if not summary:
        return
    try:
        await escalate(bus=bus, severity=severity, summary=summary, detail=detail, from_agent=agent_id)
    except Exception as exc:
        logger.warning("_maybe_escalate failed for %s: %s", agent_id, exc)


async def _maybe_widget_update(response: str | None, agent_id: str, metrics_dir: Path) -> None:
    """Parse executive JSON response for dashboard_widget field and upsert it."""
    if not response:
        return
    try:
        data = _extract_json(response)
    except Exception:
        return
    raw = data.get("dashboard_widget")
    if not raw or not isinstance(raw, dict):
        return
    widget_id = raw.get("id")
    if not widget_id:
        return
    from clawbot.metrics import MetricsStore, DashboardWidget
    try:
        widget = DashboardWidget(
            id=str(widget_id),
            type=str(raw.get("type", "text")),
            title=str(raw.get("title", "")),
            agent=agent_id,
            content=str(raw.get("content", "")),
            value=float(raw.get("value", 0.0)),
            unit=str(raw.get("unit", "")),
            max_value=float(raw.get("max_value", 0.0)),
            items=list(raw.get("items", [])),
        )
        MetricsStore(metrics_dir=metrics_dir).upsert_widget(widget)
    except Exception as exc:
        logger.warning("_maybe_widget_update failed for %s: %s", agent_id, exc)


def _load_skill_catalog() -> list:
    """Snapshot of the registered skills as catalog entries. Called per cycle
    so newly-registered skills become available without restarting.

    Returns an empty list if the registry hasn't initialised — the renderer
    handles the empty case gracefully."""
    from clawbot.skill_registry import REGISTRY
    from clawbot.skill_catalog_renderer import SkillCatalogEntry
    if REGISTRY is None:
        return []
    out: list[SkillCatalogEntry] = []
    for name in REGISTRY.list_names():
        meta = REGISTRY.get_meta(name)
        if meta is None:
            continue
        # META may carry a `roles` hint we honour; default to empty (universal).
        roles: list[str] = []
        out.append(SkillCatalogEntry(
            name=meta.name,
            description=meta.description,
            params=meta.params,
            roles=roles,
        ))
    return out


class Scheduler:
    def __init__(
        self,
        pool: LLMPool,
        bus: MessageBus,
        monitor: Monitor,
        registry: AgentRegistry | None = None,
        brain: CompanyBrain | None = None,
        homeostasis: "Homeostasis | None" = None,
        agents_dir: Path = AGENTS_DIR,
        metrics_dir: Path = METRICS_DIR,
        causal_store: "CausalStore | None" = None,
        task_store: "TaskStore | None" = None,
        db_pool=None,  # asyncpg.Pool | None; required for plan injection
    ) -> None:
        self._pool = pool
        self._bus = bus
        self._monitor = monitor
        self._registry = registry
        self._brain = brain
        self._homeostasis = homeostasis
        self._agents_dir = agents_dir
        self._metrics_dir = metrics_dir
        self._causal_store = causal_store
        self._task_store = task_store
        self._db_pool = db_pool
        self._agent_tasks: dict[str, asyncio.Task] = {}
        self._executive_cycle_counter: int = 0
        self._latest_resolution: dict | None = None
        # Serialises every operation that writes to any agent's SOUL.md or
        # SOUL.candidate.md — evolution, exploration, arbiter promotion.
        # Without this, evolution and arbiter can both write production
        # SOUL.md concurrently and lose updates.
        self._soul_write_lock = asyncio.Lock()
        self._next_wakeup_s: dict[str, int] = {}

    async def _get_budget_fraction(self) -> float:
        """Return fraction of daily spend limit consumed. Returns 0.0 on error."""
        try:
            spent = await self._monitor.daily_spend_usd()
            from clawbot.config import settings
            return spent / settings.max_daily_spend_usd
        except Exception:
            return 0.0

    async def run_forever(self) -> None:
        logger.info("Scheduler starting")
        # Subscribe to directive topics before any executive tasks start.
        # Executive loops begin publishing immediately on their first cycle;
        # if the subscription races ahead of the DirectiveRouter consumer-group
        # creation, messages published before subscribe() completes are missed.
        if self._causal_store is not None and self._registry is not None:
            from clawbot.directive_router import DIRECTIVE_TOPICS
            for topic in DIRECTIVE_TOPICS:
                await self._bus.subscribe(topic)
        tasks = [
            asyncio.create_task(self._executive_loop(), name="executive-ceo"),
            asyncio.create_task(self._board_loop(), name="board"),
            asyncio.create_task(self._evolution_loop(), name="evolution"),
            asyncio.create_task(self._kill_switch_watchdog(), name="killswitch"),
            asyncio.create_task(self._dynamic_agent_sync_loop(), name="registry-sync"),
            asyncio.create_task(self._opportunity_scanner_loop(), name="opportunity-scanner"),
            asyncio.create_task(self._coder_loop(), name="cto-coder"),
            asyncio.create_task(self._code_change_watcher(), name="code-change-watcher"),
            asyncio.create_task(self._drift_audit_loop(), name="drift-audit"),
            asyncio.create_task(self._candidate_arbiter_loop(), name="candidate-arbiter"),
            asyncio.create_task(self._fitness_writer_loop(), name="fitness-writer"),
            asyncio.create_task(self._exploration_loop(), name="exploration"),
            asyncio.create_task(self._board_resolution_subscriber(), name="board-subscriber"),
            asyncio.create_task(self._run_auto_diversification_loop(), name="auto-diversification"),
        ]
        # Lieutenants: each non-CEO executive runs its own loop reading its own SOUL.
        # Without these the org chart is structural but only the CEO does any work.
        for lieutenant in ("cfo", "cmo", "coo", "cto"):
            tasks.append(asyncio.create_task(
                self._lieutenant_loop(lieutenant), name=f"executive-{lieutenant}"
            ))
        if self._brain is not None:
            tasks.append(asyncio.create_task(
                self._brain_retention_loop(), name="brain-retention"
            ))
            tasks.append(asyncio.create_task(
                self._lateral_thinker_loop(), name="lateral-thinker"
            ))
        if self._causal_store is not None and self._registry is not None:
            from clawbot.directive_router import DirectiveRouter, DIRECTIVE_TOPICS
            from clawbot.agent_factory import AgentFactory
            from clawbot.task_store import TaskStore
            factory = AgentFactory(registry=self._registry, agents_dir=self._agents_dir)
            factory._pool = self._pool
            _task_store = self._task_store or TaskStore(self._metrics_dir / "tasks")
            router = DirectiveRouter(
                bus=self._bus,
                causal_store=self._causal_store,
                registry=self._registry,
                agent_factory=factory,
                task_store=_task_store,
                metrics_dir=self._metrics_dir,
                brain=self._brain,
                db_pool=self._db_pool,
            )
            tasks.append(asyncio.create_task(router.run(), name="directive-router"))
        # Operator escalation: subscriber persists + pushes; reply poller republishes.
        tasks.append(asyncio.create_task(
            self._escalation_subscriber_loop(), name="escalation-subscriber"
        ))
        tasks.append(asyncio.create_task(
            self._operator_reply_loop(), name="operator-reply"
        ))
        if settings.telegram_bot_token and settings.telegram_chat_id:
            tasks.append(asyncio.create_task(
                self._telegram_receiver_loop(), name="telegram-receiver"
            ))
        # Chat responder runs regardless of channel — operator might also write
        # to the inbox JSONL directly via the CLI for testing.
        tasks.append(asyncio.create_task(
            self._chat_responder_loop(), name="chat-responder"
        ))
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        for task in self._agent_tasks.values():
            task.cancel()
        for task in done:
            if task.exception():
                logger.error("Task %s failed: %s", task.get_name(), task.exception())

    async def _kill_switch_watchdog(self) -> None:
        last_capital_check = 0.0
        while True:
            if await self._monitor.should_halt():
                logger.warning("Kill switch activated — shutting down")
                raise SystemExit(0)
            if await self._monitor.spend_limit_reached():
                logger.warning("Daily spend limit reached — halting")
                raise SystemExit(0)
            # Check capital cap proximity every 5 minutes (less frequent than kill/spend checks)
            import time
            now = time.time()
            if now - last_capital_check >= CAPITAL_CAP_CHECK_INTERVAL_S:
                await self._monitor.check_capital_cap_proximity()
                last_capital_check = now
            await asyncio.sleep(KILL_WATCHDOG_INTERVAL_S)

    # ── Executive loop ──────────────────────────────────────────────────────

    async def _executive_loop(self) -> None:

        """CEO thinks every 10 min (or 60 min overnight 23:00–06:00 UTC)."""
        while True:
            await self._run_executive_cycle()
            budget_frac = await self._get_budget_fraction()
            interval = _clamp_wakeup(
                self._next_wakeup_s.get(
                    "ceo",
                    EXECUTIVE_SKELETON_INTERVAL_S if _is_skeleton_crew_hour() else EXECUTIVE_PEAK_INTERVAL_S,
                ),
                budget_fraction=budget_frac,
            )
            await asyncio.sleep(interval)

    async def _run_executive_cycle(self) -> None:
        from clawbot.fitness_writer import append_observation

        self._executive_cycle_counter += 1
        soul_path, variant = self._pick_variant("ceo")
        if soul_path is None:
            return
        await self._bus.publish("ceo.cycle_start", {"agent": "ceo", "ts": datetime.now(UTC).isoformat()})
        soul = soul_path.read_text(encoding="utf-8")
        metrics = await self._load_metrics()
        recent_decisions = await self._brain_recall(metrics)
        board_directive = self._latest_board_directive()
        active_hyp_block = ""
        try:
            if hasattr(self, "_db_pool") and self._db_pool is not None:
                hyp_store = HypothesisStore(
                    self._db_pool, max_active=settings.max_active_hypotheses,
                )
                portfolio = await hyp_store.get_active_portfolio()
                if portfolio:
                    lines = ["ACTIVE HYPOTHESIS PORTFOLIO (allocate attention by weight):"]
                    for h in portfolio:
                        lines.append(
                            f"- {h['name']} (weight {h['weight']:.2f}, "
                            f"progress {h['progress_score']:.2f}): {h['description']}"
                        )
                        lines.append(f"  Kill criteria: {h['kill_criteria']}")
                    lines.append(
                        "Every decision you make must serve ONE of these bets. "
                        "When proposing actions, name which hypothesis the action targets. "
                        "If any bet's kill criteria are met, escalate to the board for that "
                        "specific hypothesis to be PIVOTed."
                    )
                    active_hyp_block = "\n\n" + "\n".join(lines) + "\n"
        except Exception as exc:
            logger.warning("Active hypothesis portfolio load failed (continuing): %s", exc)
        catalog_block = ""
        try:
            from clawbot.skill_catalog_renderer import render_for_role
            entries = _load_skill_catalog()
            catalog_block = "\n\n" + render_for_role("ceo", entries) + "\n"
        except Exception as exc:
            logger.warning("Skill catalog render failed (continuing without it): %s", exc)

        # Plan state — load current milestone for the CEO. Plans persist across
        # cycles so the CEO doesn't re-decide its strategy every wake.
        plan_block = ""
        try:
            plan_store = PlanStore(self._db_pool) if hasattr(self, "_db_pool") and self._db_pool is not None else None
            current_milestone = None
            if plan_store is not None:
                current_milestone = await plan_store.get_current_milestone(agent_id="ceo")
            if current_milestone is None:
                plan_block = (
                    "\n\nNo active plan. Output "
                    '{"action":"plan_init", "hypothesis":"...", '
                    '"milestones":[{"hypothesis":"...","success_criteria":["..."]}]} '
                    "to commit to one before any other substantive action.\n"
                )
            else:
                plan_block = (
                    f"\n\nCurrent milestone (#{current_milestone.milestone_idx}): "
                    f"{current_milestone.hypothesis}\n"
                    f"Success criteria: {current_milestone.success_criteria}\n"
                    f"Evidence collected so far: {current_milestone.evidence}\n"
                    "When the criteria are met, output {\"action\":\"plan_advance\"}. "
                    "When the hypothesis is invalidated, output "
                    '{"action":"plan_pivot", "reason":"...", "new_hypothesis":"...", '
                    '"new_milestones":[...]}. '
                    "Otherwise pick any action that gathers evidence toward the criteria.\n"
                )
        except Exception as exc:
            logger.warning("plan load for ceo failed (continuing without): %s", exc)

        messages = [
            {"role": "system", "content": soul},
            {
                "role": "user",
                "content": (
                    f"Current metrics:\n{json.dumps(metrics, indent=2)}"
                    f"{board_directive}{active_hyp_block}{recent_decisions}"
                    f"{catalog_block}"
                    f"{plan_block}"
                    "\nWhat is your next action? Output JSON with one of these action schemas:\n"
                    '{"action": "plan_init", "hypothesis": "...", "milestones": [...]} '
                    '| {"action": "plan_advance"} '
                    '| {"action": "plan_pivot", "reason": "...", "new_hypothesis": "...", "new_milestones": [...]} '
                    '| {"action": "hire", "role": "...", "mandate": "...", "supervisor": "..."} '
                    '| {"action": "fire", "agent_id": "..."} '
                    '| {"action": "assign_task", "assigned_to": "<agent_id>", "title": "...", "description": "..."} '
                    '| {"action": "publish_product", "title": "...", "description": "..."} '
                    '| {"action": "message", "target": "<agent_id>", "message": "..."} '
                    '| {"action": "wait", "directive": "reason"} '
                    '| {"action": "<skill_name>", ...params per the skill catalog above}\n'
                    'Add: "priority": "high|medium|low", "next_wakeup_s": <integer 60-1800> '
                    "(how many seconds until your next cycle), "
                    '"escalate": null | {"severity": "info|request|warning|urgent", "summary": "...", "detail": "..."}'
                ),
            },
        ]
        response: str | None = None
        start_ts = datetime.now(UTC).timestamp()
        success = False
        try:
            response = await self._pool.complete(messages, tier="executive")
            chain_id = str(_uuid.uuid4())
            await self._bus.publish(
                "ceo.directive",
                {"response": response, "ts": datetime.now(UTC).isoformat(), "variant": variant, "chain_id": chain_id},
            )
            await _maybe_escalate(self._bus, response, "ceo")
            await _maybe_widget_update(response, "ceo", self._metrics_dir)
            try:
                _data = _extract_json(response)
                _wakeup = int(_data.get("next_wakeup_s", EXECUTIVE_PEAK_INTERVAL_S))
                self._next_wakeup_s["ceo"] = _clamp_wakeup(_wakeup)
            except Exception:
                pass
            success = True
        except Exception as exc:
            logger.error("Executive cycle failed (variant=%s): %s\n%s", variant, exc, traceback.format_exc())
        duration = datetime.now(UTC).timestamp() - start_ts
        append_observation(self._metrics_dir, "ceo", duration, success, kind="executive_cycle")

        await self._brain_remember(response)
        await self._record_variant_observation("ceo", variant)
        # Always refresh metrics after the cycle — even if the LLM call failed,
        # downstream consumers (board, evolution, shareholders) need fresh revenue.
        await self._write_company_metrics()

    def _pick_variant(self, agent_id: str) -> tuple[Path | None, str]:
        """Return (path, variant_label) for any executive. Alternates with candidate
        SOUL if one exists.

        Population-within-role (Evo G6): a candidate SOUL.md runs on alternating
        cycles while production keeps running. After CANDIDATE_WINDOW_S the arbiter
        promotes the winner. Generalised from CEO-only so exploration cycles can
        write a candidate for any executive and the arbiter actually evaluates it.
        """
        base = self._agents_dir / agent_id
        production = base / "SOUL.md"
        candidate = base / "SOUL.candidate.md"
        if not production.exists():
            return None, "production"
        if candidate.exists() and self._executive_cycle_counter % 2 == 1:
            return candidate, "candidate"
        return production, "production"

    async def _record_variant_observation(self, agent_id: str, variant: str) -> None:
        """Append one observation per cycle so the arbiter can compute revenue attribution.

        Per-agent log path so multiple agents' candidate A/B can run independently.
        Rotates after every 500 cycles to entries within 2× the candidate window.
        """
        log_path = self._metrics_dir / agent_id / "variant_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        revenue = (await self._load_metrics()).get("revenue_7d_gbp", 0.0)
        entry = {
            "ts": datetime.now(UTC).timestamp(),
            "variant": variant,
            "revenue_7d_gbp": revenue,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        if self._executive_cycle_counter % 500 == 0:
            self._rotate_variant_log(log_path)

    def _rotate_variant_log(self, log_path: Path) -> None:
        cutoff = datetime.now(UTC).timestamp() - 2 * CANDIDATE_WINDOW_S
        kept: list[str] = []
        try:
            for line in log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    if float(json.loads(line)["ts"]) >= cutoff:
                        kept.append(line)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
            log_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except OSError as exc:
            logger.warning("Variant log rotation failed: %s", exc)

    async def _brain_recall(self, metrics: dict) -> str:
        """Top-3 prior decisions by similarity to current metrics. Returns '' when
        no brain is wired OR when metrics is too trivial to produce a meaningful
        embedding (an empty `{}` query returns noise — three random unrelated
        decisions, which contaminates the prompt rather than helping)."""
        if self._brain is None:
            return ""
        query = json.dumps(metrics)
        if len(query) < BRAIN_RECALL_MIN_QUERY_CHARS:
            return ""
        query = query[:500]
        try:
            entries = await self._brain.search(query=query, k=3, category="decision")
        except Exception as exc:
            logger.warning("Brain read failed (non-fatal): %s", exc)
            return ""
        if not entries:
            return ""
        await self._bus.publish("brain.recall", {
            "node_ids": [e.id for e in entries],
            "query_preview": query[:80],
            "ts": datetime.now(UTC).isoformat(),
        })
        return "\n\nRelevant prior decisions:\n" + "\n".join(
            f"- {e.content[:200]}" for e in entries
        )

    async def _brain_remember(self, response: str | None) -> None:
        """Persist the CEO's response to the brain. Failure must not break the cycle."""
        if self._brain is None or not response:
            return
        try:
            node_id = await self._brain.write(response, category="decision")
            await self._bus.publish("brain.write", {
                "node_id": node_id,
                "category": "decision",
                "ts": datetime.now(UTC).isoformat(),
            })
        except Exception as exc:
            logger.warning("Brain write failed (non-fatal): %s", exc)

    # ── Lieutenant loops (CFO/CMO/COO/CTO) ──────────────────────────────────

    async def _lieutenant_loop(self, agent_id: str) -> None:
        """Run a non-CEO executive on the same cadence as the CEO. Without these,
        only the CEO ever thinks — the org chart is structural but single-handed."""
        while True:
            await self._run_lieutenant_cycle(agent_id)
            budget_frac = await self._get_budget_fraction()
            interval = _clamp_wakeup(
                self._next_wakeup_s.get(
                    agent_id,
                    EXECUTIVE_SKELETON_INTERVAL_S if _is_skeleton_crew_hour() else EXECUTIVE_PEAK_INTERVAL_S,
                ),
                budget_fraction=budget_frac,
            )
            await asyncio.sleep(interval)

    async def _run_lieutenant_cycle(self, agent_id: str) -> None:
        from clawbot.fitness_writer import append_observation

        soul_path, variant = self._pick_variant(agent_id)
        if soul_path is None:
            return
        await self._bus.publish(f"{agent_id}.cycle_start", {"agent": agent_id, "ts": datetime.now(UTC).isoformat()})
        soul = soul_path.read_text(encoding="utf-8")
        metrics = await self._load_metrics()
        catalog_block = ""
        try:
            from clawbot.skill_catalog_renderer import render_for_role
            entries = _load_skill_catalog()
            catalog_block = "\n\n" + render_for_role(agent_id, entries) + "\n"
        except Exception as exc:
            logger.warning("Skill catalog render failed for %s (continuing): %s", agent_id, exc)

        # Plan state — load current milestone for this agent. Plans persist across
        # cycles so the agent doesn't re-decide its strategy every wake.
        plan_block = ""
        try:
            plan_store = PlanStore(self._db_pool) if hasattr(self, "_db_pool") and self._db_pool is not None else None
            current_milestone = None
            if plan_store is not None:
                current_milestone = await plan_store.get_current_milestone(agent_id=agent_id)
            if current_milestone is None:
                plan_block = (
                    "\n\nNo active plan. Output "
                    '{"action":"plan_init", "hypothesis":"...", '
                    '"milestones":[{"hypothesis":"...","success_criteria":["..."]}]} '
                    "to commit to one before any other substantive action.\n"
                )
            else:
                plan_block = (
                    f"\n\nCurrent milestone (#{current_milestone.milestone_idx}): "
                    f"{current_milestone.hypothesis}\n"
                    f"Success criteria: {current_milestone.success_criteria}\n"
                    f"Evidence collected so far: {current_milestone.evidence}\n"
                    "When the criteria are met, output {\"action\":\"plan_advance\"}. "
                    "When the hypothesis is invalidated, output "
                    '{"action":"plan_pivot", "reason":"...", "new_hypothesis":"...", '
                    '"new_milestones":[...]}. '
                    "Otherwise pick any action that gathers evidence toward the criteria.\n"
                )
        except Exception as exc:
            logger.warning("plan load for %s failed (continuing without): %s", agent_id, exc)

        messages = [
            {"role": "system", "content": soul},
            {
                "role": "user",
                "content": (
                    f"Current metrics:\n{json.dumps(metrics, indent=2)}"
                    f"{catalog_block}"
                    f"{plan_block}"
                    "\nWhat is your next action? Output JSON with one of these action schemas:\n"
                    '{"action": "plan_init", "hypothesis": "...", "milestones": [...]} '
                    '| {"action": "plan_advance"} '
                    '| {"action": "plan_pivot", "reason": "...", "new_hypothesis": "...", "new_milestones": [...]} '
                    '| {"action": "hire", "role": "...", "mandate": "...", "supervisor": "..."} '
                    '| {"action": "fire", "agent_id": "..."} '
                    '| {"action": "assign_task", "assigned_to": "<agent_id>", "title": "...", "description": "..."} '
                    '| {"action": "publish_product", "title": "...", "description": "..."} '
                    '| {"action": "message", "target": "<agent_id>", "message": "..."} '
                    '| {"action": "wait", "directive": "reason"} '
                    '| {"action": "<skill_name>", ...params per the skill catalog above}\n'
                    'Add: "priority": "high|medium|low", "next_wakeup_s": <integer 60-1800> '
                    "(how many seconds until your next cycle), "
                    '"escalate": null | {"severity": "info|request|warning|urgent", "summary": "...", "detail": "..."}'
                ),
            },
        ]
        start_ts = datetime.now(UTC).timestamp()
        success = False
        try:
            response = await self._pool.complete(messages, tier="executive")
            chain_id = str(_uuid.uuid4())
            await self._bus.publish(
                f"{agent_id}.directive",
                {"response": response, "ts": datetime.now(UTC).isoformat(), "variant": variant, "chain_id": chain_id},
            )
            await _maybe_escalate(self._bus, response, agent_id)
            await _maybe_widget_update(response, agent_id, self._metrics_dir)
            try:
                _data = _extract_json(response)
                _wakeup = int(_data.get("next_wakeup_s", EXECUTIVE_PEAK_INTERVAL_S))
                self._next_wakeup_s[agent_id] = _clamp_wakeup(_wakeup)
            except Exception:
                pass
            success = True
        except Exception as exc:
            logger.error("Lieutenant cycle failed (agent=%s, variant=%s): %s\n%s", agent_id, variant, exc, traceback.format_exc())
        duration = datetime.now(UTC).timestamp() - start_ts
        append_observation(self._metrics_dir, agent_id, duration, success, kind=f"{agent_id}_cycle")
        await self._record_variant_observation(agent_id, variant)

    # ── Metrics writer (R3) ─────────────────────────────────────────────────

    async def _write_company_metrics(self) -> None:
        """Write /metrics/company_metrics.json so board / evolution / fitness can read it."""
        revenue_7d = await self._read_revenue_7d()
        worker_count = await self._registry.worker_count() if self._registry else 0

        metrics = {
            "revenue_7d_gbp": revenue_7d,
            "worker_count": worker_count,
            "is_skeleton_crew_hour": _is_skeleton_crew_hour(),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        try:
            self._metrics_dir.mkdir(parents=True, exist_ok=True)
            (self._metrics_dir / "company_metrics.json").write_text(
                json.dumps(metrics, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Could not write company_metrics.json: %s", exc)

    async def _read_revenue_7d(self) -> float:
        """Read 7-day revenue from Gumroad. Returns 0.0 on any failure."""
        if not settings.gumroad_api_key:
            return 0.0
        try:
            from clawbot.gumroad import GumroadClient
            client = GumroadClient(api_key=settings.gumroad_api_key)
            return await client.sales_last_7_days_gbp()
        except Exception as exc:
            logger.warning("Gumroad revenue read failed: %s", exc)
            return 0.0

    # ── Board loop with quorum retry ────────────────────────────────────────

    async def _board_loop(self) -> None:
        """Board meeting at 03:00 UTC daily."""
        while True:
            now = datetime.now(UTC)
            if now.hour == 3 and now.minute < 5:
                await self._run_board_meeting()
                await asyncio.sleep(3600)  # avoid re-triggering within same hour
            else:
                await asyncio.sleep(300)

    async def _run_board_meeting(self) -> None:
        board = BoardVotingSystem(settings.redis_url)
        await board.connect()
        try:
            await self._collect_shareholder_votes(board, SHAREHOLDERS)

            # Quorum-aware tally with retry on missing votes.
            resolution = None
            for attempt in range(SHAREHOLDER_VOTE_RETRIES + 1):
                try:
                    resolution = await board.tally_votes(require_quorum=True)
                    break
                except QuorumNotReached as exc:
                    if attempt >= SHAREHOLDER_VOTE_RETRIES:
                        logger.error(
                            "Board meeting abandoned — quorum still not reached "
                            "after %d retries (%d/5 votes cast, missing %s)",
                            SHAREHOLDER_VOTE_RETRIES, exc.cast, exc.missing,
                        )
                        return
                    logger.warning(
                        "Quorum not reached (%d/5); re-collecting %s (attempt %d)",
                        exc.cast, exc.missing, attempt + 1,
                    )
                    await self._collect_shareholder_votes(board, exc.missing)
            if resolution is None:
                return  # defensive; the loop above either sets it or returns
            logger.info("Board resolution: %s", resolution.outcome)
            if resolution.requires_ceo_action:
                await self._bus.publish("board.resolution", {
                    "outcome": resolution.outcome,
                    "action_required": resolution.action_required,
                })
        finally:
            await board.close()

    async def _collect_shareholder_votes(
        self,
        board: BoardVotingSystem,
        shareholder_ids: list[str],
    ) -> None:
        """Ask each shareholder LLM for a vote and submit it. Exceptions are logged, not swallowed silently."""
        metrics = await self._load_metrics()
        for shareholder_id in shareholder_ids:
            soul_path = self._agents_dir / shareholder_id / "SOUL.md"
            if not soul_path.exists():
                logger.warning("Shareholder %s SOUL.md missing; skipping vote", shareholder_id)
                continue
            soul = soul_path.read_text(encoding="utf-8")
            messages = [
                {"role": "system", "content": soul},
                {
                    "role": "user",
                    "content": (
                        f"Metrics:\n{json.dumps(metrics, indent=2)}\n\n"
                        "Cast your vote. Output JSON: "
                        '{"vote": "CONTINUE|PIVOT|RESET", "rationale": "..."}'
                    ),
                },
            ]
            try:
                raw = await self._pool.complete(messages, tier="executive")
                data = json.loads(raw)
                vote = BoardVote(
                    shareholder_id=shareholder_id,
                    vote=data["vote"],
                    rationale=data.get("rationale", ""),
                )
                await board.submit_vote(vote)
            except Exception as exc:
                # Logged loudly — the quorum check above will re-collect on retry.
                logger.warning("Shareholder %s vote failed (%s); will retry if quorum missed", shareholder_id, exc)

    # ── Evolution loop ──────────────────────────────────────────────────────

    async def _evolution_loop(self) -> None:
        """Evaluate and evolve agents when fitness signal warrants it, not on a fixed clock.

        Polls hourly. Fires only when the 7d revenue has changed by ≥ε since the
        last fire (gradient available) OR when ≥7 days have passed (avoid total
        stagnation). Without this gate, the first ~6 mutation cycles after launch
        run against an empty revenue signal — pure noise, wasted variation.
        """
        while True:
            await asyncio.sleep(EVOLUTION_POLL_INTERVAL_S)
            if _is_skeleton_crew_hour():
                continue
            if not await self._evolution_signal_ready():
                continue
            await self._run_evolution()
            self._record_evolution_fire()

    async def _evolution_signal_ready(self) -> bool:
        """True when revenue gives a learnable gradient OR bootstrap mode forces a fire.

        Three trigger paths:
        1. Bootstrap: revenue is £0 AND ≥1 day since last fire — keep gradient flowing
           during the critical pre-revenue period when waiting for delta would mean
           waiting forever.
        2. Signal: 7d revenue delta ≥ £1 since last fire — there's a gradient to follow.
        3. Heartbeat: ≥7 days since last fire — never let the system completely stagnate.
        """
        state = self._load_evolution_state()
        now_ts = datetime.now(UTC).timestamp()
        elapsed = now_ts - state.get("last_fire_ts", 0.0)
        current_revenue = (await self._load_metrics()).get("revenue_7d_gbp", 0.0)

        if current_revenue == 0.0 and elapsed >= 86_400:
            logger.info("Evolution fire: bootstrap mode (revenue £0, %dh elapsed)", int(elapsed / 3600))
            return True
        if elapsed >= EVOLUTION_MAX_INTERVAL_S:
            logger.info("Evolution fire: %d days elapsed since last cycle", int(elapsed / 86_400))
            return True
        delta = abs(current_revenue - state.get("last_fire_revenue", 0.0))
        if delta >= EVOLUTION_REVENUE_EPSILON_GBP:
            logger.info(
                "Evolution fire: 7d revenue delta £%.2f exceeds £%.2f threshold",
                delta, EVOLUTION_REVENUE_EPSILON_GBP,
            )
            return True
        return False

    def _load_evolution_state(self) -> dict:
        path = self._metrics_dir / "evolution_state.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def _record_evolution_fire(self) -> None:
        path = self._metrics_dir / "evolution_state.json"
        revenue = 0.0
        metrics_file = self._metrics_dir / "company_metrics.json"
        if metrics_file.exists():
            try:
                revenue = float(json.loads(metrics_file.read_text()).get("revenue_7d_gbp", 0.0))
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "last_fire_ts": datetime.now(UTC).timestamp(),
            "last_fire_revenue": revenue,
        }), encoding="utf-8")

    async def _run_evolution(self) -> None:
        from clawbot.evolution import run_evolution_cycle, load_environment_from_metrics
        from clawbot.lineage import LineageStore

        scores = self._load_all_fitness()
        if len(scores) < 2:
            return

        env = await self._build_environment_context() or load_environment_from_metrics(self._metrics_dir)
        lineage = LineageStore(self._metrics_dir)
        drift_flags = self._load_drift_flags()

        async with self._soul_write_lock:
            mutated = await run_evolution_cycle(
                self._agents_dir, scores, self._pool,
                environment=env,
                lineage_store=lineage,
                strict_drift_targets=drift_flags,
            )
        logger.info("Evolved %d agents: %s", len(mutated), mutated)
        if self._homeostasis is not None:
            for _ in mutated:
                await self._homeostasis.record_event("mutations")

    async def _build_environment_context(self):
        """Compose env context from opportunity feed + brain market_signals (if brain wired)."""
        from clawbot.evolution import load_environment_from_metrics

        env = load_environment_from_metrics(self._metrics_dir)
        if self._brain is None:
            return env
        try:
            recent = await self._brain.search(
                query="current market opportunity",
                k=5,
                category="market_signal",
            )
            env.market_signals = [e.content[:200] for e in recent]
        except Exception as exc:
            logger.warning("Brain market_signal recall failed: %s", exc)
        return env

    def _load_drift_flags(self) -> set[str]:
        path = self._metrics_dir / "drift_flags.json"
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data.get("flagged_agents", []))
        except (OSError, json.JSONDecodeError):
            return set()

    # ── Dynamic agent sync (R1) ─────────────────────────────────────────────

    async def _dynamic_agent_sync_loop(self) -> None:
        """Every 60s, reconcile asyncio tasks with the active agent registry."""
        if self._registry is None:
            return  # No registry wired — skip silently. Tests run without one.
        while True:
            await self._sync_dynamic_agents()
            await asyncio.sleep(REGISTRY_SYNC_INTERVAL_S)

    async def _sync_dynamic_agents(self) -> None:
        if self._registry is None:
            return
        active = await self._registry.list_active()
        active_worker_ids = {s.agent_id for s in active if not s.is_executive}

        # Start tasks for newly registered workers
        for spec in active:
            if spec.is_executive:
                continue
            if spec.agent_id in self._agent_tasks and not self._agent_tasks[spec.agent_id].done():
                continue
            task = asyncio.create_task(
                self._worker_agent_loop(spec),
                name=f"agent-{spec.agent_id}",
            )
            self._agent_tasks[spec.agent_id] = task
            await self._bus.subscribe(f"inbox.{spec.agent_id}")

        # Cancel tasks for agents that have been fired
        for agent_id in list(self._agent_tasks):
            if agent_id not in active_worker_ids:
                self._agent_tasks.pop(agent_id).cancel()

    async def _worker_agent_loop(self, spec: AgentSpec) -> None:
        """Run a single worker agent on its declared interval."""
        soul_path = self._resolve_soul_path(spec)
        task_store = self._task_store
        while True:
            if not soul_path.exists():
                logger.info("Worker %s SOUL.md missing — loop ending", spec.agent_id)
                return
            soul = soul_path.read_text(encoding="utf-8")
            interval = (
                EXECUTIVE_SKELETON_INTERVAL_S
                if _is_skeleton_crew_hour()
                else spec.call_interval_s
            )

            task_context = ""
            if task_store is not None:
                tasks = task_store.read_tasks(spec.agent_id)
                if tasks:
                    task_lines = "\n".join(
                        f"- [{t['task_id'][:8]}] {t['title']}: {t['description'][:200]}"
                        for t in tasks[:5]
                    )
                    task_context = f"\n\nYour pending tasks:\n{task_lines}"

            inbox_context = ""
            try:
                inbox_msgs = await self._bus.read_and_ack(
                    f"inbox.{spec.agent_id}",
                    f"worker-{spec.agent_id}",
                    count=5,
                    block_ms=100,
                )
                if inbox_msgs:
                    lines = "\n".join(
                        f"- From {m.get('from', 'unknown')}: {m.get('message', '')[:200]}"
                        for m in inbox_msgs
                    )
                    inbox_context = f"\n\nInbox messages:\n{lines}"
            except Exception:
                pass

            try:
                tier = "executive" if spec.agent_id in EXECUTIVE_IDS else "worker"
                response = await self._pool.complete(
                    [
                        {"role": "system", "content": soul},
                        {"role": "user", "content": (
                            f"What is your next action? Report result as JSON.{task_context}{inbox_context}"
                        )},
                    ],
                    tier=tier,
                )
                await self._bus.publish(
                    f"agent.{spec.agent_id}.output",
                    {"result": response, "agent_id": spec.agent_id},
                )
            except Exception as exc:
                logger.warning("Worker %s cycle failed: %s", spec.agent_id, exc)
            await asyncio.sleep(interval)

    def _resolve_soul_path(self, spec: AgentSpec) -> Path:
        """spec.soul_path is stored relative to repo root; resolve under agents_dir's parent."""
        candidate = Path(spec.soul_path)
        if candidate.is_absolute():
            return candidate
        return self._agents_dir.parent / candidate

    # ── Operator escalation channel ─────────────────────────────────────────

    async def _escalation_subscriber_loop(self) -> None:
        """Consume `operator.escalation` bus messages: persist + optional ntfy push
        + optional Telegram push. Persistence-first."""
        telegram_sender = None
        if settings.telegram_bot_token and settings.telegram_chat_id:
            from clawbot.telegram_channel import TelegramSender
            telegram_sender = TelegramSender(
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )
        store = EscalationStore(
            metrics_dir=self._metrics_dir,
            ntfy_topic=settings.ntfy_topic,
            ntfy_base_url=settings.ntfy_base_url,
            telegram_sender=telegram_sender,
        )
        await self._bus.subscribe(ESCALATION_TOPIC)
        while True:
            try:
                messages = await self._bus.read_and_ack(
                    ESCALATION_TOPIC, "scheduler-escalation", count=5, block_ms=10_000,
                )
                for msg in messages:
                    try:
                        esc = Escalation(
                            id=str(msg.get("id", "")),
                            ts=str(msg.get("ts", "")),
                            severity=msg.get("severity", "info"),  # type: ignore[arg-type]
                            from_agent=str(msg.get("from_agent", "unknown")),
                            summary=str(msg.get("summary", "")),
                            detail=str(msg.get("detail", "")),
                            correlation_id=str(msg.get("correlation_id", "")),
                        )
                        store.persist(esc)
                        await store.push_ntfy(esc)
                        await store.push_telegram(esc)
                        logger.info("Escalation %s [%s] from %s: %s",
                                    esc.id, esc.severity, esc.from_agent, esc.summary[:120])
                    except Exception as exc:
                        logger.error("Failed to process escalation: %s", exc)
            except Exception as exc:
                logger.error("Escalation subscriber cycle failed: %s", exc)
                await asyncio.sleep(5)

    async def _telegram_receiver_loop(self) -> None:
        """Long-poll Telegram for operator replies. Only enabled when both
        TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are configured. Failures
        log and retry — never crash the scheduler."""
        if not (settings.telegram_bot_token and settings.telegram_chat_id):
            return
        from clawbot.telegram_channel import TelegramReceiver
        receiver = TelegramReceiver(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            metrics_dir=self._metrics_dir,
        )
        while True:
            try:
                await receiver.poll_forever()
            except Exception as exc:
                logger.error("Telegram receiver crashed (%s) — restarting in 10s", exc)
                await asyncio.sleep(10)

    async def _chat_responder_loop(self) -> None:
        """Drain operator_inbox.jsonl, generate CEO chat responses, send them
        back via the escalation channel (so Telegram delivery is reused).

        Each message also fires `operator.message` so the CEO's normal executive
        cycle picks up the context for longer-horizon decisions."""
        inbox = OperatorInbox(metrics_dir=self._metrics_dir)
        while True:
            await asyncio.sleep(OPERATOR_INBOX_POLL_INTERVAL_S)
            try:
                messages = inbox.drain_new_messages()
                for msg in messages:
                    await self._bus.publish(OPERATOR_MESSAGE_TOPIC, {
                        "ts": msg.ts, "text": msg.text,
                    })
                    response_text = await respond_to_operator(
                        pool=self._pool,
                        agents_dir=self._agents_dir,
                        metrics_dir=self._metrics_dir,
                        message_text=msg.text,
                        brain=self._brain,
                    )
                    if not response_text:
                        continue
                    # Chat responses go out as info-severity escalations so the
                    # existing Telegram delivery path handles formatting + send.
                    await escalate(
                        bus=self._bus,
                        severity="info",
                        summary=response_text[:300],
                        detail=response_text,
                        from_agent="ceo",
                        correlation_id="chat",
                    )
            except Exception as exc:
                logger.error("Chat responder cycle failed: %s", exc)

    async def _operator_reply_loop(self) -> None:
        """Poll /metrics/escalation_replies.jsonl, republish new entries to operator.reply."""
        reply_store = ReplyStore(metrics_dir=self._metrics_dir)
        while True:
            await asyncio.sleep(OPERATOR_REPLY_POLL_INTERVAL_S)
            try:
                replies = reply_store.drain_new_replies()
                for reply in replies:
                    await self._bus.publish(REPLY_TOPIC, {
                        "escalation_id": reply.escalation_id,
                        "ts": reply.ts,
                        "reply": reply.reply,
                    })
                    logger.info("Operator replied to %s: %s", reply.escalation_id, reply.reply[:120])
                    reply_text = reply.reply
                    if "PRODUCT_URL:" in reply_text and self._causal_store is not None:
                        url, chain_id = _parse_product_reply(reply_text)
                        if url and chain_id:
                            product_id = _extract_gumroad_product_id(url)
                            if product_id:
                                try:
                                    await self._causal_store.register_product(
                                        gumroad_product_id=product_id,
                                        chain_id=chain_id,
                                        product_title=url,
                                    )
                                    logger.info("Registered product %s → chain %s", product_id, chain_id)
                                except Exception as exc:
                                    logger.error("Failed to register product: %s", exc)
            except Exception as exc:
                logger.error("Operator reply loop failed: %s", exc)

    # ── Brain retention (H3) ────────────────────────────────────────────────

    async def _brain_retention_loop(self) -> None:
        """Daily prune of high-write brain categories. Prevents the knowledge
        table from growing indefinitely from opportunity scanner output."""
        while True:
            await asyncio.sleep(BRAIN_RETENTION_INTERVAL_S)
            if self._brain is None:
                continue
            try:
                deleted = await self._brain.prune_older_than(
                    "market_signal", BRAIN_MARKET_SIGNAL_MAX_AGE_DAYS,
                )
                if deleted:
                    logger.info("Brain pruned %d stale market_signal entries", deleted)
            except Exception as exc:
                logger.warning("Brain retention cycle failed: %s", exc)

    # ── Lateral thinker (H4) ────────────────────────────────────────────────

    async def _lateral_thinker_loop(self) -> None:
        """Weekly cross-signal synthesis. Skipped if brain not wired."""
        if self._brain is None:
            return
        from clawbot.lateral_thinker import LateralThinker
        thinker = LateralThinker(pool=self._pool, brain=self._brain)
        while True:
            await asyncio.sleep(LATERAL_THINKER_INTERVAL_S)
            try:
                result = await thinker.synthesise()
                if result:
                    logger.info("Lateral thinker synthesis stored (%d chars)", len(result))
            except Exception as exc:
                logger.error("Lateral thinker cycle failed: %s", exc)

    # ── Fitness writer (Polish P1) ──────────────────────────────────────────

    async def _fitness_writer_loop(self) -> None:
        """Recompute per-agent fitness.json hourly from rolling observation log."""
        while True:
            await asyncio.sleep(FITNESS_WRITER_INTERVAL_S)
            try:
                from clawbot.fitness_writer import refresh_all_fitness
                metrics = await self._load_metrics()
                revenue = float(metrics.get("revenue_7d_gbp", 0.0))
                results = await refresh_all_fitness(
                    self._metrics_dir, revenue,
                    causal_store=getattr(self, "_causal_store", None),
                )
                logger.info("Fitness refreshed for %d agents", len(results))
                if self._causal_store is not None:
                    await self._attribute_recent_sales()
            except Exception as exc:
                logger.error("Fitness writer cycle failed: %s", exc)

    async def _attribute_recent_sales(self) -> None:
        """Check Gumroad for recent sales; close chains for registered products."""
        if not settings.gumroad_api_key:
            return
        try:
            from clawbot.gumroad import GumroadClient
            from datetime import timedelta
            client = GumroadClient(api_key=settings.gumroad_api_key)
            # Limit to 8-day window (attribution window + 1 day overlap) so we don't
            # re-sum all-time sales on every hourly cycle. Closed chains are skipped
            # by unattributed_sale_products, but fetching years of sales is wasteful.
            sales = await client.sales(after=datetime.now(UTC) - timedelta(days=8))
            product_ids = list({s.product_id for s in sales if s.product_id})
            if not product_ids:
                return
            pairs = await self._causal_store.unattributed_sale_products(product_ids)
            for product_id, chain_id in pairs:
                sale_total = sum(
                    s.price_gbp for s in sales if s.product_id == product_id
                )
                if sale_total > 0:
                    await self._causal_store.close_chain(chain_id, sale_total)
                    logger.info(
                        "Attributed £%.2f to chain %s (product %s)",
                        sale_total, chain_id, product_id,
                    )
        except Exception as exc:
            logger.warning("Sale attribution failed (non-fatal): %s", exc)

    # ── Exploration cycle (Polish P5) ───────────────────────────────────────

    async def _exploration_loop(self) -> None:
        """Weekly: write a SOUL.candidate.md for the top-fitness agent so the
        candidate arbiter has something to evaluate (otherwise the A/B slot is
        structurally dead)."""
        while True:
            await asyncio.sleep(EXPLORATION_CYCLE_INTERVAL_S)
            if _is_skeleton_crew_hour():
                continue
            try:
                await self._run_exploration()
            except Exception as exc:
                logger.error("Exploration cycle failed: %s", exc)

    async def _run_exploration(self) -> None:
        """Mutate the top-1 fitness agent and write to SOUL.candidate.md instead of SOUL.md.

        Only writes a new candidate if one doesn't already exist for the agent —
        prevents exploration from resetting an in-flight candidate's evaluation
        window every 7 days (the arbiter needs 14 days to accumulate data).
        """
        scores = self._load_all_fitness()
        if not scores:
            return
        ranked = sorted(scores, key=lambda s: s.score, reverse=True)
        from clawbot.evolution import (
            run_evolution_cycle, load_environment_from_metrics, _is_mutable_target,
        )
        candidates = [s for s in ranked if _is_mutable_target(s.agent_id)]
        if not candidates:
            return
        top = candidates[0]

        existing_candidate = self._agents_dir / top.agent_id / "SOUL.candidate.md"
        if existing_candidate.exists():
            logger.info(
                "Exploration skipped — candidate already in-flight for %s (let arbiter judge first)",
                top.agent_id,
            )
            return

        env = await self._build_environment_context() or load_environment_from_metrics(self._metrics_dir)
        async with self._soul_write_lock:
            mutated = await run_evolution_cycle(
                self._agents_dir, [top], self._pool,
                environment=env,
                lineage_store=None,
                candidate_mode=True,
            )
        logger.info("Exploration cycle produced candidate for: %s", mutated)

    # ── Board resolution subscriber (Polish P2) ─────────────────────────────

    async def _board_resolution_subscriber(self) -> None:
        """Cache the latest board resolution so the next CEO cycle can act on it."""
        await self._bus.subscribe("board.resolution")
        while True:
            messages = await self._bus.read_and_ack(
                "board.resolution", "scheduler-board-cache", count=1, block_ms=10_000,
            )
            for msg in messages:
                self._latest_resolution = {
                    "outcome": msg.get("outcome", ""),
                    "action_required": msg.get("action_required", ""),
                    "ts": datetime.now(UTC).isoformat(),
                }
                logger.info("Board resolution cached: %s", self._latest_resolution["outcome"])
                if msg.get("outcome") in ("PIVOT", "RESET"):
                    try:
                        from clawbot.board import generate_hypothesis_for_portfolio
                        if hasattr(self, "_db_pool") and self._db_pool is not None:
                            hyp_store = HypothesisStore(
                                self._db_pool,
                                max_active=settings.max_active_hypotheses,
                            )
                            current = await hyp_store.get_active()
                            prev_name = current["name"] if current else "H1"
                            prev_desc = current["description"] if current else "Initial hypothesis"
                            await generate_hypothesis_for_portfolio(
                                pool=self._pool, store=hyp_store,
                                previous_name=prev_name, previous_description=prev_desc,
                                pivot_rationale=msg.get("action_required", "")[:400],
                                max_active=settings.max_active_hypotheses,
                            )
                    except Exception as exc:
                        logger.error("Hypothesis generation on pivot failed: %s", exc)

    def _latest_board_directive(self) -> str:
        """Render the latest cached resolution into a prompt-friendly block."""
        res = self._latest_resolution
        if not res:
            return ""
        return (
            f"\n\nBOARD RESOLUTION ({res['outcome']}) — you must address this:\n"
            f"{res['action_required']}"
        )

    # ── Drift audit (F2) ────────────────────────────────────────────────────

    async def _drift_audit_loop(self) -> None:
        """Daily independent audit of every SOUL.md for MUTABLE-vs-IMMUTABLE conformance."""
        while True:
            await asyncio.sleep(DRIFT_AUDIT_INTERVAL_S)
            if _is_skeleton_crew_hour():
                continue
            try:
                await self._run_drift_audit()
            except Exception as exc:
                logger.error("Drift audit cycle failed: %s", exc)

    async def _run_drift_audit(self) -> None:
        from clawbot.drift_audit import audit_all, write_drift_flags
        results = await audit_all(self._agents_dir, self._pool)
        write_drift_flags(self._metrics_dir, results)
        flagged = [r.agent_id for r in results if r.contradicts]
        if flagged:
            logger.warning("Drift audit flagged: %s", flagged)

    # ── Candidate arbiter (G6) ──────────────────────────────────────────────

    async def _candidate_arbiter_loop(self) -> None:
        """Daily: if SOUL.candidate.md has existed ≥14 days, promote or remove based on revenue trend."""
        while True:
            await asyncio.sleep(CANDIDATE_ARBITER_INTERVAL_S)
            try:
                await self._arbitrate_candidates()
            except Exception as exc:
                logger.error("Candidate arbiter cycle failed: %s", exc)

    async def _arbitrate_candidates(self) -> None:
        """Evaluate every executive's candidate (if any). Promotes winners,
        removes losers. Each agent is judged independently against its own
        variant log; no cross-agent coupling.
        """
        for agent_id in ("ceo", "cfo", "cmo", "coo", "cto"):
            await self._arbitrate_one(agent_id)

    async def _arbitrate_one(self, agent_id: str) -> None:
        base = self._agents_dir / agent_id
        candidate = base / "SOUL.candidate.md"
        production = base / "SOUL.md"
        if not candidate.exists():
            self._clear_candidate_state(agent_id)
            return

        created_at = self._candidate_created_at(agent_id, candidate)
        age_s = datetime.now(UTC).timestamp() - created_at
        if age_s < CANDIDATE_WINDOW_S:
            return

        decision = self._compare_variants_from_log(agent_id)
        async with self._soul_write_lock:
            if decision == "promote":
                logger.info("Candidate arbiter: promoting %s candidate after %d days",
                            agent_id, int(age_s / 86_400))
                production.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
                candidate.unlink()
            else:
                logger.info("Candidate arbiter: removing %s candidate (verdict=%s)",
                            agent_id, decision)
                candidate.unlink()
        self._clear_candidate_state(agent_id)

    def _candidate_state_path(self) -> Path:
        return self._metrics_dir / "candidate_state.json"

    def _candidate_created_at(self, agent_id: str, candidate_file: Path) -> float:
        """Persistent created-at timestamp; ignores subsequent exploration rewrites."""
        path = self._candidate_state_path()
        state: dict = {}
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
        if agent_id in state:
            return float(state[agent_id])
        # First time we see this candidate — record now and persist.
        created = candidate_file.stat().st_mtime
        state[agent_id] = created
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        return created

    def _clear_candidate_state(self, agent_id: str) -> None:
        path = self._candidate_state_path()
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            state.pop(agent_id, None)
            path.write_text(json.dumps(state), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    def _compare_variants_from_log(self, agent_id: str) -> str:
        """Read /metrics/<agent>/variant_log.jsonl. Return 'promote' iff candidate's
        mean revenue beats production's by ≥ the configured margin (1%, conservative
        to avoid promoting variants that won by noise alone)."""
        log_path = self._metrics_dir / agent_id / "variant_log.jsonl"
        if not log_path.exists():
            return "remove"
        prod_obs, cand_obs = [], []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            (cand_obs if entry.get("variant") == "candidate" else prod_obs).append(
                float(entry.get("revenue_7d_gbp", 0.0))
            )
        if not cand_obs or not prod_obs:
            return "remove"
        prod_mean = sum(prod_obs) / len(prod_obs)
        cand_mean = sum(cand_obs) / len(cand_obs)
        # Require ≥1% lift to promote — revenue is shared across variants on a
        # single Gumroad account, so noise floor is high. Conservative bar prevents
        # promoting on confounders (lucky-week effect).
        return "promote" if cand_mean > prod_mean * CANDIDATE_PROMOTION_MARGIN else "remove"

    # ── CTO Coder ───────────────────────────────────────────────────────────

    async def _coder_loop(self) -> None:
        """Run the CTO self-modification coder loop."""
        coder = CTOCoder(pool=self._pool, bus=self._bus)
        await coder.run_loop()

    async def _code_change_watcher(self) -> None:
        """Restart the container after a successful code commit so new code loads."""
        await self._bus.subscribe(CHANGE_RESULT_TOPIC)
        while True:
            messages = await self._bus.read_and_ack(
                CHANGE_RESULT_TOPIC, "scheduler-watcher", count=1, block_ms=10_000,
            )
            for msg in messages:
                if msg.get("success"):
                    logger.info(
                        "Code change committed (%s) — restarting to load new code",
                        msg.get("description", ""),
                    )
                    raise SystemExit(0)

    # ── Opportunity scanner (R5) ────────────────────────────────────────────

    async def _opportunity_scanner_loop(self) -> None:
        """Scanner runs independently of executive cycles; reports to Opportunist via metrics store.

        Charter §"Structural Diversity" requires that the scanner cannot be reassigned
        by any executive. It is wired directly to the metrics store and only that.

        Skeleton-crew gating: during 23:00–06:00 UTC, scan interval triples to
        preserve NIM/Groq budget for peak hours (Charter §Safety).
        """
        metrics_store = MetricsStore(metrics_dir=self._metrics_dir)
        scanner = OpportunityScanner(pool=self._pool, metrics=metrics_store, brain=self._brain)
        while True:
            try:
                await scanner.scan()
            except Exception as exc:
                logger.error("Opportunity scanner cycle failed: %s", exc)
            interval = REDDIT_INTERVAL_S * 3 if _is_skeleton_crew_hour() else REDDIT_INTERVAL_S
            await asyncio.sleep(interval)

    # ── Auto-diversification (Task 0c) ──────────────────────────────────────

    async def _run_auto_diversification_loop(self) -> None:
        """Every 6 hours, check the portfolio. If any active bet is stagnant
        (past 50% time + low progress), spawn a fresh one via the board's
        existing generator. Cap-respecting; does nothing when portfolio is full."""
        DIVERSIFICATION_INTERVAL_S = 6 * 3600  # 6 hours
        while True:
            await asyncio.sleep(DIVERSIFICATION_INTERVAL_S)
            if not (hasattr(self, "_db_pool") and self._db_pool is not None):
                continue
            try:
                from clawbot.board import generate_hypothesis_for_portfolio

                hyp_store = HypothesisStore(
                    self._db_pool,
                    max_active=settings.max_active_hypotheses,
                )
                portfolio = await hyp_store.get_active_portfolio()
                if len(portfolio) >= settings.max_active_hypotheses:
                    continue  # No room

                now = datetime.now(UTC)
                for h in portfolio:
                    created_iso = h.get("created_at")
                    if not created_iso:
                        continue
                    created = datetime.fromisoformat(created_iso)
                    age_days = (now - created).total_seconds() / 86400.0
                    kill_max_days = int(h["kill_criteria"].get("max_days_without_revenue", 14))
                    progress = float(h.get("progress_score", 0.0))

                    if _should_diversify_for_hypothesis(
                        age_days=age_days, progress_score=progress,
                        portfolio_size=len(portfolio),
                        max_active=settings.max_active_hypotheses,
                        kill_max_days=kill_max_days,
                    ):
                        logger.info(
                            "Auto-diversification trigger: spawning new hypothesis "
                            "alongside stagnant %s (age=%.1fd, progress=%.2f)",
                            h["name"], age_days, progress,
                        )
                        await generate_hypothesis_for_portfolio(
                            pool=self._pool, store=hyp_store,
                            previous_name=h["name"],
                            previous_description=h["description"],
                            pivot_rationale=(
                                f"Auto-diversification: {h['name']} is stagnant "
                                f"(age {age_days:.1f}d, progress {progress:.2f}). "
                                f"Spawning a new bet alongside it to diversify."
                            ),
                            max_active=settings.max_active_hypotheses,
                        )
                        break  # Spawn at most one per cycle
            except Exception as exc:
                logger.error("Auto-diversification loop iteration failed: %s", exc)

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _load_metrics(self) -> dict:
        path = self._metrics_dir / "company_metrics.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def _load_all_fitness(self) -> list[FitnessScore]:
        scores = []
        if not self._metrics_dir.exists():
            return scores
        for agent_dir in self._metrics_dir.iterdir():
            fitness_path = agent_dir / "fitness.json"
            if fitness_path.exists():
                data = json.loads(fitness_path.read_text(encoding="utf-8"))
                scores.append(FitnessScore(**data))
        return scores
