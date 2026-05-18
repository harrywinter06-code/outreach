"""Entry point: wires up all services and starts the scheduler."""
import asyncio
import logging
import sys

from datetime import datetime, UTC
from pathlib import Path

from clawbot.agent_registry import AgentRegistry, AgentSpec, EXECUTIVE_IDS
from clawbot.bus import MessageBus
from clawbot.company_brain import CompanyBrain
from clawbot.config import settings
from clawbot.db import Database
from clawbot.homeostasis import Homeostasis
from clawbot.llm_pool import LLMPool
from clawbot.monitor import Monitor
from clawbot.dashboard.server import start_dashboard
from clawbot.causal_store import CausalStore
from clawbot.task_store import TaskStore
from clawbot.scheduler import AGENTS_DIR, METRICS_DIR, Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def maybe_seed_initial_hypothesis(store) -> bool:
    """Insert the initial hypothesis if none is active. Returns True if seeded."""
    current = await store.get_active()
    if current is not None:
        return False
    await store.set_active(
        name="H2",
        description=(
            "Autonomous UK micro-tool funnel. Agents pick a UK-niche question "
            "with measurable search demand (council tax band, IR35 status, "
            "mortgage affordability, student loan plan), generate an LLM-backed "
            "free assessment + paid £3-5 personalised report, fulfilled-on-demand "
            "via email after Stripe payment-link checkout. Distribution via "
            "Dev.to + Medium + Bluesky + Mastodon (no operator account dependency). "
            "Agent owns the full loop end-to-end: niche selection, copy, "
            "publishing, Stripe payment link, fulfilment. Operator's only role "
            "is the one-time Stripe live-mode KYB + domain purchase already "
            "documented in operating_facts.md."
        ),
        kill_criteria={
            "max_days_without_revenue": 21,
            "min_unique_visitors_by_day": [7, 50],
            "min_email_captures_by_day": [14, 5],
        },
    )
    return True


def _startup_checklist() -> None:
    """Fail loudly with specific instructions if revenue infrastructure is missing.

    Note: STRIPE_SECRET_KEY is accepted but no Stripe-specific code path exists
    yet — only Gumroad is wired end-to-end via gumroad.GumroadClient. If you
    set STRIPE_SECRET_KEY, revenue capture will silently report £0. We require
    GUMROAD_API_KEY specifically so the gumroad_revenue path can actually fire.
    """
    errors = []
    warnings_ = []
    if not settings.active_provider_names:
        errors.append(
            "No LLM providers configured. Set at least one of: "
            "NIM_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, CEREBRAS_API_KEY"
        )
    if not settings.gumroad_api_key:
        errors.append(
            "No GUMROAD_API_KEY set. The Gumroad client is the only revenue "
            "capture path currently wired — set GUMROAD_API_KEY (create account "
            "at gumroad.com → Settings → Advanced → Generate access token) "
            "before the system can observe revenue. Stripe integration is not "
            "yet implemented."
        )
    if settings.stripe_secret_key:
        warnings_.append(
            "STRIPE_SECRET_KEY is set but there is no Stripe-specific code path. "
            "Revenue capture is Gumroad-only; Stripe webhooks are not yet wired."
        )
    if errors:
        for msg in errors:
            logger.error("STARTUP BLOCKED: %s", msg)
        sys.exit(1)
    for msg in warnings_:
        logger.warning("STARTUP WARNING: %s", msg)


async def main() -> None:
    _startup_checklist()
    logger.info("Active providers: %s", settings.active_provider_names)

    pool = LLMPool(settings=settings)
    bus = MessageBus(redis_url=settings.redis_url)
    monitor = Monitor(
        redis_url=settings.redis_url,
        max_daily_spend_usd=settings.max_daily_spend_usd,
        kill_file=settings.kill_file_path,
        capital_weekly_cap_gbp=settings.capital_weekly_cap_gbp,
        db_pool=None,  # Set after db.connect() below
    )
    registry = AgentRegistry(redis_url=settings.redis_url)
    db = Database(database_url=settings.database_url)
    homeostasis = Homeostasis(redis_url=settings.redis_url)

    await asyncio.gather(
        pool.connect(), bus.connect(), monitor.connect(),
        registry.connect(), db.connect(), homeostasis.connect(),
    )
    monitor._db_pool = db.pool
    monitor.set_bus(bus)
    await db.init_schema()

    from clawbot.hypothesis_store import HypothesisStore
    hyp_store = HypothesisStore(db.pool, max_active=settings.max_active_hypotheses)
    await hyp_store.init_schema()
    if await maybe_seed_initial_hypothesis(hyp_store):
        logger.info("Seeded initial hypothesis")

    # Swarm Phase Z1 — `business` as first-class unit of selection.
    # The store is wired here so future loops (Z2 spawn/cull, Z3 capital
    # allocator, Z4 template inheritance) have a single owner.
    from clawbot.business_store import BusinessStore
    business_store = BusinessStore(
        db.pool, max_active=settings.max_active_businesses,
    )
    initial_active = await business_store.count_active()
    logger.info(
        "Swarm initialised: %d active businesses (cap=%d)",
        initial_active, settings.max_active_businesses,
    )

    # Swarm Phase Z2 — SwarmController spawns / culls / graduates businesses
    # against the £-fitness signal. Loops are wired into the scheduler.
    from clawbot.swarm_controller import SwarmController, SwarmPolicy
    from clawbot.swarm_seeds import get_seed_genomes
    swarm_policy = SwarmPolicy(
        max_active=settings.max_active_businesses,
        seed_budget_gbp=settings.business_seed_budget_gbp,
        graduation_revenue_gbp=settings.business_template_graduation_gbp,
        probation_days=settings.swarm_probation_days,
        hard_kill_days=settings.swarm_hard_kill_days,
        template_sample_weight=settings.swarm_template_sample_weight,
    )
    swarm_controller = SwarmController(
        store=business_store, seeds=get_seed_genomes(), policy=swarm_policy,
    )

    causal_store = CausalStore(pool=db.pool)
    task_store = TaskStore(tasks_dir=METRICS_DIR / "tasks")
    await _register_executives(registry)

    brain = CompanyBrain(pool=db.pool)

    from clawbot.skill_registry import init_skill_system
    from clawbot.skill_forge import SkillForge
    from clawbot.agent_lifecycle import AgentLifecycle
    from clawbot.skill_catalog_writer import SkillCatalogWriter

    SKILLS_DIR = Path(__file__).parent.parent.parent / "agents" / "skills"
    WORKERS_DIR = Path(__file__).parent.parent.parent / "agents" / "workers"
    ARCHIVE_DIR = Path(__file__).parent.parent.parent / "agents" / "skills_archive"
    WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    skill_registry = init_skill_system(skills_dir=SKILLS_DIR)
    skill_registry.set_stats_db(db.pool)
    logger.info("Loaded %d skills: %s", len(skill_registry.list_names()), skill_registry.list_names())

    catalog_writer = SkillCatalogWriter(registry=skill_registry, brain=brain)

    forge = SkillForge(
        llm_pool=pool, bus=bus, registry=skill_registry,
        skills_dir=SKILLS_DIR, archive_dir=ARCHIVE_DIR,
        brain=brain, db_pool=db.pool, escalation=None,
    )
    lifecycle = AgentLifecycle(registry=registry, bus=bus, workers_dir=WORKERS_DIR)

    topics = [
        "ceo.directive", "cfo.directive", "cmo.directive",
        "coo.directive", "cto.directive",
        "board.resolution", "coo.task", "cmo.campaign",
        "code.change_request", "operator.escalation", "operator.reply",
        "operator.message",
        "ceo.cycle_start", "cfo.cycle_start", "cmo.cycle_start",
        "coo.cycle_start", "cto.cycle_start",
        "brain.recall", "brain.write",
    ]
    for topic in topics:
        await bus.subscribe(topic)

    scheduler = Scheduler(
        pool=pool, bus=bus, monitor=monitor,
        registry=registry, brain=brain, homeostasis=homeostasis,
        causal_store=causal_store, task_store=task_store,
        db_pool=db.pool,
        swarm_controller=swarm_controller,
    )
    try:
        await asyncio.gather(
            scheduler.run_forever(),
            start_dashboard(db_pool=db.pool, redis_url=settings.redis_url),
            skill_registry.run_watcher(),
            forge.run_loop(),
            lifecycle.run_loop(),
            catalog_writer.run_loop(),
        )
    finally:
        await asyncio.gather(
            pool.close(), bus.close(), monitor.close(),
            registry.close(), db.close(), homeostasis.close(),
        )


async def _register_executives(registry: AgentRegistry) -> None:
    """Idempotently register the six executive agents. Without this, AgentRegistry
    starts empty and `worker_count` / `agents_by_supervisor` return nothing useful."""
    supervisors = {
        "ceo": "board", "cfo": "ceo", "cmo": "ceo",
        "cto": "ceo", "coo": "ceo", "meta": "board",
    }
    now = datetime.now(UTC).isoformat()
    for agent_id in EXECUTIVE_IDS:
        if await registry.get(agent_id) is not None:
            continue
        spec = AgentSpec(
            agent_id=agent_id,
            role=agent_id.upper(),
            supervisor=supervisors.get(agent_id, "board"),
            soul_path=str(Path("agents") / agent_id / "SOUL.md"),
            status="active",
            created_at=now,
            call_interval_s=600,
        )
        await registry.register(spec)
        logger.info("Registered executive: %s", agent_id)


if __name__ == "__main__":
    asyncio.run(main())
