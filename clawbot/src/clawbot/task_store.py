"""
JSONL-backed per-agent task queue.

Tasks are created by DirectiveRouter.assign_task, read by workers before each
cycle, and completed/failed by workers after execution. Two files per agent:
- tasks_dir/<agent_id>/pending.jsonl  — pending tasks
- tasks_dir/<agent_id>/completed.jsonl — archive of done/failed (append-only)

Single-process only: all agent loops run as asyncio coroutines in one process.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskStore:
    def __init__(self, tasks_dir: Path) -> None:
        self._dir = tasks_dir

    def _agent_dir(self, agent_id: str) -> Path:
        d = self._dir / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create_task(
        self,
        title: str,
        description: str,
        assigned_to: str,
        chain_id: str,
    ) -> str:
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
            "title": title[:200],
            "description": description[:2000],
            "assigned_to": assigned_to,
            "chain_id": chain_id,
            "status": "pending",
            "created_at": time.time(),
        }
        pending_path = self._agent_dir(assigned_to) / "pending.jsonl"
        with pending_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(task) + "\n")
        return task_id

    def read_tasks(self, agent_id: str) -> list[dict]:
        """Return all pending tasks for this agent."""
        path = self._agent_dir(agent_id) / "pending.jsonl"
        if not path.exists():
            return []
        tasks = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                t = json.loads(line)
                if t.get("status") == "pending":
                    tasks.append(t)
            except (json.JSONDecodeError, KeyError):
                continue
        return tasks

    def complete_task(self, task_id: str, agent_id: str) -> None:
        self._update_task(task_id, agent_id, status="completed")

    def fail_task(self, task_id: str, agent_id: str, reason: str = "") -> None:
        self._update_task(task_id, agent_id, status="failed", reason=reason)

    def _update_task(self, task_id: str, agent_id: str, **updates: object) -> None:
        path = self._agent_dir(agent_id) / "pending.jsonl"
        if not path.exists():
            return
        kept: list[str] = []
        found: dict | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                t = json.loads(line)
                if t.get("task_id") == task_id:
                    t.update(updates)
                    t["updated_at"] = time.time()
                    found = t
                else:
                    kept.append(line)
            except (json.JSONDecodeError, KeyError):
                kept.append(line)

        path.write_text(
            "\n".join(kept) + ("\n" if kept else ""),
            encoding="utf-8",
        )
        if found is not None:
            archive = self._agent_dir(agent_id) / "completed.jsonl"
            with archive.open("a", encoding="utf-8") as f:
                f.write(json.dumps(found) + "\n")
