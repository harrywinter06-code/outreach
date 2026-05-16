"""
Agent registry — the company's live org chart, stored in Redis.
Executives (ceo, cfo, cmo, cto, coo) are always present.
Worker agents are created by the CEO and removed by the evolution cycle.
"""
import json
from dataclasses import dataclass, asdict
from typing import Any, Literal

AgentStatus = Literal["active", "suspended", "fired"]

EXECUTIVE_IDS = {"ceo", "cfo", "cmo", "cto", "coo", "meta"}
REGISTRY_PREFIX = "clawbot:agents"


@dataclass
class AgentSpec:
    agent_id: str        # e.g. "content-writer-001"
    role: str            # human-readable role name
    supervisor: str      # which executive this reports to
    soul_path: str       # path to SOUL.md relative to repo root
    status: AgentStatus
    created_at: str
    call_interval_s: int = 600  # how often the agent runs its loop

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "AgentSpec":
        return cls(**json.loads(raw))

    @property
    def is_executive(self) -> bool:
        return self.agent_id in EXECUTIVE_IDS


class AgentRegistry:
    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._redis: Any = None

    async def connect(self) -> None:
        import redis.asyncio as aioredis
        self._redis = await aioredis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    @property
    def _r(self) -> Any:
        assert self._redis is not None, "call connect() first"
        return self._redis

    def _key(self, agent_id: str) -> str:
        return f"{REGISTRY_PREFIX}:{agent_id}"

    async def register(self, spec: AgentSpec) -> None:
        await self._r.set(self._key(spec.agent_id), spec.to_json())
        await self._r.sadd(f"{REGISTRY_PREFIX}:index", spec.agent_id)

    async def get(self, agent_id: str) -> AgentSpec | None:
        raw = await self._r.get(self._key(agent_id))
        return AgentSpec.from_json(raw) if raw else None

    async def list_active(self) -> list[AgentSpec]:
        ids: set[str] = await self._r.smembers(f"{REGISTRY_PREFIX}:index")
        specs = []
        for agent_id in ids:
            spec = await self.get(agent_id)
            if spec and spec.status == "active":
                specs.append(spec)
        return specs

    async def set_status(self, agent_id: str, status: AgentStatus) -> None:
        spec = await self.get(agent_id)
        if spec:
            spec.status = status
            await self._r.set(self._key(agent_id), spec.to_json())

    async def deregister(self, agent_id: str) -> None:
        """Remove from active roster. Does not delete SOUL.md — evolution log kept."""
        if agent_id in EXECUTIVE_IDS:
            raise ValueError(f"Cannot deregister executive: {agent_id}")
        await self.set_status(agent_id, "fired")
        await self._r.srem(f"{REGISTRY_PREFIX}:index", agent_id)

    async def worker_count(self) -> int:
        agents = await self.list_active()
        return sum(1 for a in agents if not a.is_executive)

    async def agents_by_supervisor(self, supervisor: str) -> list[AgentSpec]:
        agents = await self.list_active()
        return [a for a in agents if a.supervisor == supervisor]
