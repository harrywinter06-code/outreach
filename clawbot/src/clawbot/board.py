import json
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from typing import Any, Literal

VoteChoice = Literal["CONTINUE", "PIVOT", "RESET"]
BoardOutcome = Literal["CONTINUE", "PIVOT", "RESET"]

SHAREHOLDERS = [
    "shareholder-activist",
    "shareholder-conservative",
    "shareholder-diversifier",
    "shareholder-longterm",
    "shareholder-opportunist",
]

EMERGENCY_TRIGGERS = {
    "revenue_flat_days": 3,       # days with £0 revenue triggers emergency vote
    "strategy_unchanged_days": 7, # same strategy for 7 days
    "spend_pct_threshold": 0.80,  # 80% of daily spend limit for 2 days
}

# Minimum votes required when require_quorum=True. The charter mandates a 3-of-5
# majority, so a single missing vote is recoverable, but 2+ missing votes make any
# outcome a minority decision — better to re-collect than fall back to tie-break PIVOT.
QUORUM_MIN_VOTES = 4


class QuorumNotReached(RuntimeError):
    """Raised when an emergency tally is attempted with fewer than QUORUM_MIN_VOTES."""

    def __init__(self, cast: int, missing: list[str]) -> None:
        super().__init__(
            f"Only {cast}/{len(SHAREHOLDERS)} votes cast; missing: {missing}. "
            f"Need at least {QUORUM_MIN_VOTES} for emergency tally."
        )
        self.cast = cast
        self.missing = missing


@dataclass
class BoardVote:
    shareholder_id: str
    vote: VoteChoice
    rationale: str
    timestamp: str = ""

    def __post_init__(self):
        self.timestamp = self.timestamp or datetime.now(UTC).isoformat()

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "BoardVote":
        return cls(**json.loads(raw))


@dataclass
class BoardResolution:
    date: str
    votes: list[BoardVote]
    outcome: BoardOutcome
    requires_ceo_action: bool
    action_required: str  # instruction to CEO if PIVOT or RESET

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d)

    @classmethod
    def from_json(cls, raw: str) -> "BoardResolution":
        d = json.loads(raw)
        d["votes"] = [BoardVote(**v) for v in d["votes"]]
        return cls(**d)


class BoardVotingSystem:
    def __init__(self, redis_url: str):
        self._url = redis_url
        self._redis: Any = None

    async def connect(self) -> None:
        import redis.asyncio as aioredis
        self._redis = await aioredis.from_url(self._url, decode_responses=True)

    async def close(self):
        if self._redis:
            await self._redis.aclose()

    @property
    def _r(self):
        assert self._redis is not None, "call connect() before using BoardVotingSystem"
        return self._redis

    def _vote_key(self, date: str, shareholder_id: str) -> str:
        return f"clawbot:board:votes:{date}:{shareholder_id}"

    def _resolution_key(self, date: str) -> str:
        return f"clawbot:board:resolution:{date}"

    async def submit_vote(self, vote: BoardVote) -> None:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        key = self._vote_key(date, vote.shareholder_id)
        await self._r.set(key, vote.to_json(), ex=86400 * 7)  # retain 7 days

    async def tally_votes(
        self,
        date: str | None = None,
        require_quorum: bool = False,
    ) -> BoardResolution:
        date = date or datetime.now(UTC).strftime("%Y-%m-%d")
        votes: list[BoardVote] = []
        missing: list[str] = []
        for sid in SHAREHOLDERS:
            raw = await self._r.get(self._vote_key(date, sid))
            if raw:
                votes.append(BoardVote.from_json(raw))
            else:
                missing.append(sid)

        if require_quorum and len(votes) < QUORUM_MIN_VOTES:
            raise QuorumNotReached(cast=len(votes), missing=missing)

        counts = {"CONTINUE": 0, "PIVOT": 0, "RESET": 0}
        for v in votes:
            counts[v.vote] += 1

        # Majority (3+) wins; tie-break is PIVOT (caution over inertia)
        if counts["RESET"] >= 3:
            outcome: BoardOutcome = "RESET"
        elif counts["PIVOT"] >= 3:
            outcome = "PIVOT"
        elif counts["CONTINUE"] >= 3:
            outcome = "CONTINUE"
        else:
            outcome = "PIVOT"  # tie-break: caution

        requires_action = outcome in ("PIVOT", "RESET")
        action_map = {
            "CONTINUE": "",
            "PIVOT": "Propose a new strategic direction within 24 hours. Present to board for vote.",
            "RESET": "Pause all current initiatives. Convene full strategic review. Present 3 new directions.",
        }

        resolution = BoardResolution(
            date=date,
            votes=votes,
            outcome=outcome,
            requires_ceo_action=requires_action,
            action_required=action_map[outcome],
        )
        await self._r.set(self._resolution_key(date), resolution.to_json(), ex=86400 * 30)
        return resolution

    async def get_latest_resolution(self) -> BoardResolution | None:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        raw = await self._r.get(self._resolution_key(date))
        if raw:
            return BoardResolution.from_json(raw)
        return None

    async def check_emergency_triggers(self, metrics: dict) -> bool:
        """Return True if an emergency board vote should be convened."""
        revenue_flat = metrics.get("revenue_flat_days", 0)
        strategy_days = metrics.get("strategy_unchanged_days", 0)

        if revenue_flat >= EMERGENCY_TRIGGERS["revenue_flat_days"]:
            await self._r.publish(
                "clawbot:board:emergency",
                json.dumps({"reason": f"Revenue flat for {revenue_flat} days", "metrics": metrics}),
            )
            return True
        if strategy_days >= EMERGENCY_TRIGGERS["strategy_unchanged_days"]:
            await self._r.publish(
                "clawbot:board:emergency",
                json.dumps({"reason": f"Strategy unchanged for {strategy_days} days", "metrics": metrics}),
            )
            return True
        return False

    async def votes_cast_today(self) -> int:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        count = 0
        for sid in SHAREHOLDERS:
            if await self._r.exists(self._vote_key(date, sid)):
                count += 1
        return count

    async def quorum_reached(self) -> bool:
        return await self.votes_cast_today() >= 3
