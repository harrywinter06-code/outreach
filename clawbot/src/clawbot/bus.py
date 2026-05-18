"""
Redis Streams message bus for inter-agent communication.
Streams (not Pub/Sub) give persistence and consumer group semantics —
a message is never lost if the consumer crashes mid-processing.
"""
import json
from datetime import datetime, UTC
from typing import Any


STREAM_PREFIX = "clawbot:bus"
CONSUMER_GROUP = "clawbot-agents"


def _stream(topic: str) -> str:
    return f"{STREAM_PREFIX}:{topic}"


class MessageBus:
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
        assert self._redis is not None, "call connect() before using MessageBus"
        return self._redis

    async def publish(self, topic: str, payload: dict) -> str:
        """Append a message to the stream. Returns the Redis stream entry ID."""
        entry = {
            "payload": json.dumps(payload),
            "ts": datetime.now(UTC).isoformat(),
        }
        msg_id: str = await self._r.xadd(_stream(topic), entry, maxlen=10_000, approximate=True)
        return msg_id

    async def subscribe(self, topic: str) -> None:
        """Create consumer group if it doesn't exist yet."""
        try:
            await self._r.xgroup_create(
                _stream(topic), CONSUMER_GROUP, id="0", mkstream=True
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read(
        self,
        topic: str,
        consumer_id: str,
        count: int = 10,
        block_ms: int = 5_000,
    ) -> list[dict]:
        """
        Read new messages for this consumer. Returns parsed payload dicts.
        Blocks up to block_ms if no messages are ready.

        Auto-subscribes (creates the consumer group + empty stream) on the
        first NOGROUP error and retries once. This lets ad-hoc topics created
        by skills (e.g. operator.approval_reply) work without main.py having
        to enumerate every possible topic up front.
        """
        try:
            results = await self._r.xreadgroup(
                CONSUMER_GROUP,
                consumer_id,
                {_stream(topic): ">"},
                count=count,
                block=block_ms,
            )
        except Exception as exc:
            if "NOGROUP" not in str(exc):
                raise
            await self.subscribe(topic)
            results = await self._r.xreadgroup(
                CONSUMER_GROUP,
                consumer_id,
                {_stream(topic): ">"},
                count=count,
                block=block_ms,
            )
        messages = []
        if results:
            for _, entries in results:
                for msg_id, fields in entries:
                    data = json.loads(fields["payload"])
                    data["_id"] = msg_id
                    messages.append(data)
        return messages

    async def ack(self, topic: str, msg_id: str) -> None:
        """Acknowledge a message so it leaves the pending list."""
        await self._r.xack(_stream(topic), CONSUMER_GROUP, msg_id)

    async def read_and_ack(
        self,
        topic: str,
        consumer_id: str,
        count: int = 10,
        block_ms: int = 5_000,
    ) -> list[dict]:
        """Read messages and ack them atomically (use when exactly-once not required)."""
        messages = await self.read(topic, consumer_id, count, block_ms)
        for msg in messages:
            await self.ack(topic, msg["_id"])
        return messages

    async def publish_inbox(self, agent_id: str, payload: dict) -> str:
        """Publish to a per-agent inbox stream with a tighter maxlen cap (1000)."""
        entry = {
            "payload": json.dumps(payload),
            "ts": datetime.now(UTC).isoformat(),
        }
        msg_id: str = await self._r.xadd(
            _stream(f"inbox.{agent_id}"), entry, maxlen=1_000, approximate=True,
        )
        return msg_id
