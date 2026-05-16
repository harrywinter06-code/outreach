import pytest
import json
from pathlib import Path


def test_task_store_create_and_read(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task(title="Write UK ISA guide", description="Research and write",
                      assigned_to="worker-001", chain_id="abc-123")

    tasks = store.read_tasks("worker-001")
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Write UK ISA guide"
    assert tasks[0]["chain_id"] == "abc-123"
    assert tasks[0]["status"] == "pending"


def test_task_store_complete_task(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task("task A", "desc", "worker-001", "chain-1")

    tasks = store.read_tasks("worker-001")
    task_id = tasks[0]["task_id"]
    store.complete_task(task_id, "worker-001")

    pending = store.read_tasks("worker-001")
    assert len(pending) == 0


def test_task_store_fail_task(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task("task B", "desc", "worker-001", "chain-1")

    tasks = store.read_tasks("worker-001")
    task_id = tasks[0]["task_id"]
    store.fail_task(task_id, "worker-001", reason="LLM timeout")

    pending = store.read_tasks("worker-001")
    assert len(pending) == 0


def test_task_store_completed_task_in_archive(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task("task C", "desc", "worker-001", "chain-1")
    tasks = store.read_tasks("worker-001")
    store.complete_task(tasks[0]["task_id"], "worker-001")

    archive = tmp_path / "worker-001" / "completed.jsonl"
    assert archive.exists()
    lines = [l for l in archive.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["status"] == "completed"


def test_task_store_read_returns_empty_for_unknown_agent(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    assert store.read_tasks("nobody") == []


def test_task_store_multiple_agents_isolated(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    store.create_task("task for A", "desc", "agent-A", "chain-1")
    store.create_task("task for B", "desc", "agent-B", "chain-2")

    assert len(store.read_tasks("agent-A")) == 1
    assert len(store.read_tasks("agent-B")) == 1
    assert store.read_tasks("agent-A")[0]["title"] == "task for A"


def test_task_store_create_returns_task_id(tmp_path):
    from clawbot.task_store import TaskStore
    import uuid
    store = TaskStore(tmp_path)
    task_id = store.create_task("task", "desc", "worker", "chain")
    assert len(task_id) == 36  # UUID string
    uuid.UUID(task_id)  # must be valid UUID


def test_task_store_title_truncated_at_200(tmp_path):
    from clawbot.task_store import TaskStore
    store = TaskStore(tmp_path)
    long_title = "x" * 300
    store.create_task(long_title, "desc", "worker", "chain")
    tasks = store.read_tasks("worker")
    assert len(tasks[0]["title"]) == 200
