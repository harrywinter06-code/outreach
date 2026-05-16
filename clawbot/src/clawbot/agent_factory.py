"""
Agent factory — CEO calls spawn() to hire, evolution calls fire() to let go.

spawn(): generates a SOUL.md for the new role via LLM, writes it to disk,
         registers in the AgentRegistry. Scheduler picks it up on next poll.

fire():  marks agent as fired in registry, archives its SOUL.md.
         The evolution cycle decides *who* to fire; this executes the decision.

Budget guard: each new worker agent costs ~144 LLM calls/day (10-min loop).
The factory checks remaining daily budget before spawning.
"""
import re
from datetime import datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING

from clawbot.agent_registry import AgentRegistry, AgentSpec

if TYPE_CHECKING:
    from clawbot.llm_pool import LLMPool


AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"

# Approximate LLM calls per day per worker at default 600s interval
CALLS_PER_WORKER_PER_DAY = 144

SPAWN_PROMPT = """\
You are writing a SOUL.md genome for a new employee at an autonomous AI company.

Role title: {role}
Reports to: {supervisor}
Mandate: {mandate}
{template_block}

Write a SOUL.md with exactly two sections:

## IMMUTABLE
(Permanent identity, mandate, hard rules — 150-250 words)

## MUTABLE
(Initial state, current priorities — keep these sections:
### current_focus
### active_tasks
### recent_outcomes)

The agent must be laser-focused on generating revenue. Every task it takes
must have a measurable outcome traceable to money.

Output ONLY the SOUL.md content — no preamble, no explanation.
"""

_TEMPLATE_BLOCK = """
Differential reproduction — the agent below is the highest-fitness peer in this
role. Inherit its proven tactics in your MUTABLE section, but do NOT copy
verbatim — adapt them to your specific mandate above. The MUTABLE section to
draw from:

---
{template_mutable}
---
"""


class AgentFactory:
    def __init__(
        self,
        registry: AgentRegistry,
        agents_dir: Path = AGENTS_DIR,
        max_workers: int = 20,
    ) -> None:
        self._registry = registry
        self._agents_dir = agents_dir
        self._max_workers = max_workers

    async def spawn(
        self,
        role: str,
        supervisor: str,
        mandate: str,
        pool: "LLMPool",
        call_interval_s: int = 600,
        template_from: AgentSpec | None = None,
    ) -> AgentSpec:
        """
        Create a new worker agent. Returns the AgentSpec on success.
        Raises RuntimeError if worker cap or daily budget would be exceeded.

        `template_from`: if provided, the high-fitness agent whose MUTABLE section
        seeds the new agent's strategy (differential reproduction — winners
        propagate their proven tactics to offspring rather than just surviving).
        """
        current_count = await self._registry.worker_count()
        if current_count >= self._max_workers:
            raise RuntimeError(
                f"Worker cap reached ({self._max_workers}). "
                "Fire underperforming agents before hiring."
            )

        agent_id = _make_id(role, current_count + 1)
        soul_path = self._agents_dir / agent_id / "SOUL.md"

        template_block = ""
        if template_from is not None:
            template_block = _build_template_block(template_from, self._agents_dir.parent)

        messages = [
            {"role": "system", "content": "You write SOUL.md agent genomes. Be concise and revenue-focused."},
            {"role": "user", "content": SPAWN_PROMPT.format(
                role=role, supervisor=supervisor, mandate=mandate,
                template_block=template_block,
            )},
        ]
        soul_content = await pool.complete(messages, tier="executive", temperature=0.7)

        soul_path.parent.mkdir(parents=True, exist_ok=True)
        soul_path.write_text(soul_content, encoding="utf-8")

        spec = AgentSpec(
            agent_id=agent_id,
            role=role,
            supervisor=supervisor,
            soul_path=str(soul_path.relative_to(self._agents_dir.parent)),
            status="active",
            created_at=datetime.now(UTC).isoformat(),
            call_interval_s=call_interval_s,
        )
        await self._registry.register(spec)
        return spec

    async def fire(self, agent_id: str) -> None:
        """
        Deregister an agent. Archives its SOUL.md with a .fired suffix so the
        mutation history is preserved for future evolution prompts.
        """
        spec = await self._registry.get(agent_id)
        if spec is None:
            return

        soul_path = Path(spec.soul_path)
        if soul_path.exists():
            archive = soul_path.with_suffix(f".fired-{datetime.now(UTC).strftime('%Y%m%d')}.md")
            soul_path.rename(archive)

        await self._registry.deregister(agent_id)

    def daily_budget_for_n_workers(self, n: int) -> int:
        """How many LLM calls per day n additional workers would consume."""
        return n * CALLS_PER_WORKER_PER_DAY


def _make_id(role: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")
    return f"{slug}-{index:03d}"


def _build_template_block(template_from: AgentSpec, repo_root: Path) -> str:
    """Read the high-fitness peer's MUTABLE section and wrap in the template prompt."""
    from clawbot.genome import read_soul, extract_mutable

    soul_path = Path(template_from.soul_path)
    if not soul_path.is_absolute():
        soul_path = repo_root / soul_path
    if not soul_path.exists():
        return ""
    try:
        mutable = extract_mutable(read_soul(soul_path))
    except ValueError:
        return ""
    return _TEMPLATE_BLOCK.format(template_mutable=mutable.strip())
