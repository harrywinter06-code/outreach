"""Consumes agent.spawn_request and agent.fire_request from the bus.

This is the receiving end of the worker_spawn / worker_fire skills. Lives
outside agent_registry.py because that file is protected — but it ONLY calls
registry.register / registry.deregister, never mutates the protected surface.
"""
from __future__ import annotations

import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from clawbot.agent_registry import AgentRegistry, AgentSpec, EXECUTIVE_IDS

logger = logging.getLogger(__name__)


class AgentLifecycle:
    def __init__(self, registry: AgentRegistry, bus: Any, workers_dir: Path) -> None:
        self._reg = registry
        self._bus = bus
        self._workers_dir = workers_dir

    async def run_loop(self) -> None:
        await self._bus.subscribe("agent.spawn_request")
        await self._bus.subscribe("agent.fire_request")
        while True:
            spawn_msgs = await self._bus.read_and_ack(
                "agent.spawn_request", "agent-lifecycle", count=5, block_ms=5000,
            )
            for m in spawn_msgs:
                try:
                    await self._handle_spawn(m)
                except Exception as exc:
                    logger.error("spawn failed: %s", exc)
            fire_msgs = await self._bus.read_and_ack(
                "agent.fire_request", "agent-lifecycle", count=5, block_ms=1000,
            )
            for m in fire_msgs:
                try:
                    await self._handle_fire(m)
                except Exception as exc:
                    logger.error("fire failed: %s", exc)

    async def _handle_spawn(self, msg: dict) -> None:
        agent_id = msg["agent_id"]
        role = msg["role"]
        soul_text = msg["soul_text"]
        supervisor = msg["supervisor"]
        call_interval_s = int(msg.get("call_interval_s", 600))

        soul_dir = self._workers_dir / agent_id
        soul_dir.mkdir(parents=True, exist_ok=True)
        soul_path = soul_dir / "SOUL.md"
        soul_path.write_text(soul_text, encoding="utf-8")

        spec = AgentSpec(
            agent_id=agent_id, role=role, supervisor=supervisor,
            soul_path=str(soul_path.relative_to(self._workers_dir.parent.parent)),
            status="active",
            created_at=datetime.now(UTC).isoformat(),
            call_interval_s=call_interval_s,
        )
        await self._reg.register(spec)
        logger.info("agent spawned: %s (role=%s, supervisor=%s)", agent_id, role, supervisor)

    async def _handle_fire(self, msg: dict) -> None:
        agent_id = msg["agent_id"]
        if agent_id in EXECUTIVE_IDS:
            logger.warning("refused fire of executive: %s", agent_id)
            return
        await self._reg.deregister(agent_id)
        logger.info("agent fired: %s (reason=%s)", agent_id, msg.get("reason", ""))
