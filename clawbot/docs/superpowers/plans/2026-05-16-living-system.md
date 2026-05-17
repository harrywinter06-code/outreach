# Clawbot: Living System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform clawbot from a deliberation engine that produces unread text into a living system where agents take real actions — hiring staff, assigning tasks, publishing product briefs, communicating with each other, and self-scheduling based on urgency.

**Architecture:** A `DirectiveRouter` subscribes to all executive bus topics, parses structured agent output, and dispatches to registered tool handlers. Agent output JSON gains an expanded vocabulary (`hire`, `fire`, `assign_task`, `publish_product`, `message`, `research`) plus `next_wakeup_s` for self-scheduling. A per-agent Redis inbox enables peer-to-peer delegation. A lateral-thought loop synthesises market signals weekly into novel product ideas.

**Tech Stack:** Python 3.12, asyncio, Redis Streams (existing `MessageBus`), JSONL for task persistence, httpx for web research.

---

## File Map

**New files:**
- `src/clawbot/json_util.py` — shared `extract_json()` (moved from scheduler.py)
- `src/clawbot/directive_router.py` — routes executive directives to tool handlers
- `src/clawbot/tasks.py` — JSONL-backed task store
- `src/clawbot/tools/__init__.py` — empty package marker
- `src/clawbot/tools/hiring.py` — hire/fire handlers
- `src/clawbot/tools/task_tool.py` — assign_task handler
- `src/clawbot/tools/publishing.py` — publish_product → operator escalation
- `src/clawbot/tools/messaging.py` — agent-to-agent message handler
- `src/clawbot/tools/web_research.py` — httpx fetch + LLM summarise
- `src/clawbot/lateral_thinker.py` — weekly cross-signal synthesis loop
- `tests/test_json_util.py`
- `tests/test_directive_router.py`
- `tests/test_tasks.py`
- `tests/test_tools_hiring.py`
- `tests/test_tools_task.py`
- `tests/test_tools_publishing.py`
- `tests/test_self_scheduling.py`
- `tests/test_agent_inbox.py`
- `tests/test_tools_web_research.py`
- `tests/test_lateral_thinker.py`

**Modified files:**
- `src/clawbot/scheduler.py` — wire DirectiveRouter, agent inboxes, self-scheduling; replace local `_extract_json` with import; expand executive prompts
- `src/clawbot/main.py` — construct TaskStore and pass to Scheduler

---

## Phase 1: Execution Kernel

### Task 1: Extract `_extract_json` to shared utility

**Files:**
- Create: `src/clawbot/json_util.py`
- Create: `tests/test_json_util.py`
- Modify: `src/clawbot/scheduler.py` (replace local `_extract_json` with import)

- [ ] **Step 1: Write the test**

```python
# tests/test_json_util.py
import pytest
from clawbot.json_util import extract_json


def test_extract_bare_json():
    assert extract_json('{"action": "think"}') == {"action": "think"}


def test_extract_fenced_json():
    assert extract_json('```json\n{"action": "hire"}\n```') == {"action": "hire"}


def test_extract_json_with_surrounding_text():
    result = extract_json('Here is my response:\n{"action": "think", "directive": "do x"}')
    assert result["action"] == "think"


def test_extract_json_raises_on_no_object():
    with pytest.raises(ValueError, match="no JSON object found"):
        extract_json("no json here at all")
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\Users\Winte\clawbot
uv run pytest tests/test_json_util.py -v
```
Expected: `ImportError: cannot import name 'extract_json' from 'clawbot.json_util'`

- [ ] **Step 3: Create `src/clawbot/json_util.py`**

```python
import json
import re

_JSON_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```")


def extract_json(text: str) -> dict:
    """Return first JSON object from text, stripping markdown fences if present."""
    match = _JSON_RE.search(text)
    blob = match.group(1) if match else text
    start = blob.find("{")
    end = blob.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in text")
    return json.loads(blob[start:end + 1])
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/test_json_util.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Update scheduler.py**

Remove the local `_extract_json` function (the one defined at module level in `scheduler.py`, currently lines ~81–90). Add at the top of the import block:

```python
from clawbot.json_util import extract_json as _extract_json
```

- [ ] **Step 6: Run existing scheduler tests to check no regressions**

```
uv run pytest tests/test_scheduler.py -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```
git add src/clawbot/json_util.py tests/test_json_util.py src/clawbot/scheduler.py
git commit -m "refactor: extract _extract_json to shared json_util module"
```

---

### Task 2: DirectiveRouter

**Files:**
- Create: `src/clawbot/directive_router.py`
- Create: `tests/test_directive_router.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_directive_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from clawbot.directive_router import DirectiveRouter, EXECUTIVE_TOPICS


@pytest.fixture
def bus():
    b = MagicMock()
    b.subscribe = AsyncMock()
    b.read_and_ack = AsyncMock(return_value=[])
    return b


@pytest.mark.asyncio
async def test_route_unknown_action_does_not_raise(bus):
    router = DirectiveRouter(bus)
    await router.route({"action": "unknown_xyz"})


@pytest.mark.asyncio
async def test_route_think_is_noop(bus):
    router = DirectiveRouter(bus)
    handler = AsyncMock()
    router.register("think", handler)
    await router.route({"action": "think"})
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_route_empty_action_is_noop(bus):
    router = DirectiveRouter(bus)
    handler = AsyncMock()
    router.register("", handler)
    await router.route({})
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_route_calls_registered_handler(bus):
    router = DirectiveRouter(bus)
    handler = AsyncMock()
    router.register("hire", handler)
    directive = {"action": "hire", "role": "writer", "mandate": "write posts"}
    await router.route(directive)
    handler.assert_awaited_once_with(directive)


@pytest.mark.asyncio
async def test_route_handler_exception_does_not_propagate(bus):
    router = DirectiveRouter(bus)

    async def bad_handler(params):
        raise RuntimeError("tool exploded")

    router.register("hire", bad_handler)
    await router.route({"action": "hire"})  # must not raise


def test_executive_topics_are_defined():
    assert "ceo.directive" in EXECUTIVE_TOPICS
    assert "cmo.directive" in EXECUTIVE_TOPICS
    assert len(EXECUTIVE_TOPICS) == 5
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_directive_router.py -v
```
Expected: `ImportError: cannot import name 'DirectiveRouter'`

- [ ] **Step 3: Create `src/clawbot/directive_router.py`**

```python
"""
Routes structured executive output from the bus to registered tool handlers.
The bridge between agent deliberation and real-world action.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, TYPE_CHECKING

from clawbot.json_util import extract_json

if TYPE_CHECKING:
    from clawbot.bus import MessageBus

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict], Awaitable[None]]

EXECUTIVE_TOPICS = [
    "ceo.directive",
    "cfo.directive",
    "cmo.directive",
    "coo.directive",
    "cto.directive",
]

_NOOP_ACTIONS = {"", "think"}


class DirectiveRouter:
    def __init__(self, bus: "MessageBus") -> None:
        self._bus = bus
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, action: str, handler: ToolHandler) -> None:
        self._handlers[action] = handler

    async def route(self, directive: dict, source_topic: str = "") -> None:
        action = str(directive.get("action", "")).strip().lower()
        if action in _NOOP_ACTIONS:
            return
        handler = self._handlers.get(action)
        if handler is None:
            logger.debug("No handler for action %r (from %s) — ignoring", action, source_topic)
            return
        try:
            await handler(directive)
        except Exception as exc:
            logger.error("Handler for action %r failed (from %s): %s", action, source_topic, exc)

    async def run_forever(self) -> None:
        for topic in EXECUTIVE_TOPICS:
            await self._bus.subscribe(topic)
        while True:
            for topic in EXECUTIVE_TOPICS:
                messages = await self._bus.read_and_ack(
                    topic, "directive-router", count=5, block_ms=1_000,
                )
                for msg in messages:
                    raw = msg.get("response", "")
                    if not raw:
                        continue
                    try:
                        directive = extract_json(raw)
                        directive["_source_topic"] = topic
                        await self.route(directive, source_topic=topic)
                    except Exception as exc:
                        logger.warning("Could not parse directive from %s: %s", topic, exc)
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/test_directive_router.py -v
```
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```
git add src/clawbot/directive_router.py tests/test_directive_router.py
git commit -m "feat: add DirectiveRouter — bridge between agent deliberation and tool execution"
```

---

### Task 3: Hire / Fire Tool Handlers

**Files:**
- Create: `src/clawbot/tools/__init__.py`
- Create: `src/clawbot/tools/hiring.py`
- Create: `tests/test_tools_hiring.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_tools_hiring.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from clawbot.tools.hiring import handle_hire, handle_fire


@pytest.fixture
def factory():
    f = MagicMock()
    f.spawn = AsyncMock()
    f.fire = AsyncMock()
    return f


@pytest.fixture
def pool():
    return MagicMock()


@pytest.mark.asyncio
async def test_handle_hire_calls_spawn(factory, pool):
    await handle_hire(
        {"action": "hire", "role": "content-writer", "mandate": "write SEO articles", "supervisor": "cmo"},
        factory=factory,
        pool=pool,
    )
    factory.spawn.assert_awaited_once_with(
        role="content-writer",
        supervisor="cmo",
        mandate="write SEO articles",
        pool=pool,
    )


@pytest.mark.asyncio
async def test_handle_hire_defaults_supervisor_to_ceo(factory, pool):
    await handle_hire({"action": "hire", "role": "writer", "mandate": "write"}, factory=factory, pool=pool)
    assert factory.spawn.call_args.kwargs["supervisor"] == "ceo"


@pytest.mark.asyncio
async def test_handle_hire_missing_role_skips_spawn(factory, pool):
    await handle_hire({"action": "hire", "mandate": "write articles"}, factory=factory, pool=pool)
    factory.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_handle_hire_missing_mandate_skips_spawn(factory, pool):
    await handle_hire({"action": "hire", "role": "writer"}, factory=factory, pool=pool)
    factory.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_handle_fire_calls_factory_fire(factory):
    await handle_fire({"action": "fire", "agent_id": "writer-001"}, factory=factory)
    factory.fire.assert_awaited_once_with("writer-001")


@pytest.mark.asyncio
async def test_handle_fire_missing_agent_id_skips(factory):
    await handle_fire({"action": "fire"}, factory=factory)
    factory.fire.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_tools_hiring.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `src/clawbot/tools/__init__.py`** (empty file)

- [ ] **Step 4: Create `src/clawbot/tools/hiring.py`**

```python
"""Hire and fire tool handlers for DirectiveRouter."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.agent_factory import AgentFactory
    from clawbot.llm_pool import LLMPool

logger = logging.getLogger(__name__)


async def handle_hire(params: dict, factory: "AgentFactory", pool: "LLMPool") -> None:
    role = str(params.get("role", "")).strip()
    mandate = str(params.get("mandate", "")).strip()
    supervisor = str(params.get("supervisor", "ceo")).strip() or "ceo"
    if not role:
        logger.warning("hire directive missing 'role': %s", params)
        return
    if not mandate:
        logger.warning("hire directive missing 'mandate': %s", params)
        return
    spec = await factory.spawn(role=role, supervisor=supervisor, mandate=mandate, pool=pool)
    logger.info("Hired %s for role %r (supervisor: %s)", spec.agent_id, role, supervisor)


async def handle_fire(params: dict, factory: "AgentFactory") -> None:
    agent_id = str(params.get("agent_id", "")).strip()
    if not agent_id:
        logger.warning("fire directive missing 'agent_id': %s", params)
        return
    await factory.fire(agent_id)
    logger.info("Fired agent %s", agent_id)
```

- [ ] **Step 5: Run tests**

```
uv run pytest tests/test_tools_hiring.py -v
```
Expected: 6 PASSED

- [ ] **Step 6: Commit**

```
git add src/clawbot/tools/ tests/test_tools_hiring.py
git commit -m "feat: add hire/fire tool handlers"
```

---

### Task 4: Task Store + Assign-Task Handler

**Files:**
- Create: `src/clawbot/tasks.py`
- Create: `src/clawbot/tools/task_tool.py`
- Create: `tests/test_tasks.py`
- Create: `tests/test_tools_task.py`

- [ ] **Step 1: Write TaskStore tests**

```python
# tests/test_tasks.py
import pytest
from clawbot.tasks import TaskStore


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks")


def test_create_task_writes_file(store):
    task = store.create(title="Research UK ISA rules", brief="Summarise 2026 limits", created_by="ceo", assignee_id="cfo")
    assert store._path(task.id).exists()


def test_create_task_returns_pending_status(store):
    task = store.create(title="t", brief="b", created_by="ceo", assignee_id="cmo")
    assert task.status == "pending"
    assert task.completed_at is None


def test_get_task_roundtrip(store):
    created = store.create(title="Do SEO", brief="Write 5 posts", created_by="ceo", assignee_id="cmo")
    fetched = store.get(created.id)
    assert fetched is not None
    assert fetched.title == "Do SEO"
    assert fetched.assignee_id == "cmo"


def test_get_missing_task_returns_none(store):
    assert store.get("nonexistent") is None


def test_update_status_changes_status(store):
    task = store.create(title="t", brief="b", created_by="ceo", assignee_id="cfo")
    updated = store.update_status(task.id, "active")
    assert updated.status == "active"


def test_update_status_done_sets_completed_at(store):
    task = store.create(title="t", brief="b", created_by="ceo", assignee_id="cfo")
    updated = store.update_status(task.id, "done", result="Completed successfully")
    assert updated.completed_at is not None
    assert updated.result == "Completed successfully"


def test_for_assignee_returns_pending_and_active_only(store):
    store.create(title="t1", brief="b", created_by="ceo", assignee_id="cmo")
    done = store.create(title="t2", brief="b", created_by="ceo", assignee_id="cmo")
    store.update_status(done.id, "done")
    tasks = store.for_assignee("cmo")
    assert len(tasks) == 1
    assert tasks[0].title == "t1"


def test_for_assignee_empty_dir_returns_empty(tmp_path):
    assert TaskStore(tmp_path / "nonexistent").for_assignee("ceo") == []


def test_all_active_excludes_done(store):
    t1 = store.create(title="a", brief="", created_by="ceo", assignee_id="cfo")
    t2 = store.create(title="b", brief="", created_by="ceo", assignee_id="cmo")
    store.update_status(t2.id, "done")
    ids = {t.id for t in store.all_active()}
    assert t1.id in ids
    assert t2.id not in ids
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_tasks.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `src/clawbot/tasks.py`**

```python
"""JSONL-backed task store. One JSON file per task under tasks_dir/."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path


@dataclass
class Task:
    id: str
    title: str
    brief: str
    created_by: str
    assignee_id: str
    status: str  # "pending" | "active" | "done" | "failed"
    created_at: str
    completed_at: str | None = None
    result: str | None = None


class TaskStore:
    def __init__(self, tasks_dir: Path) -> None:
        self._dir = tasks_dir

    def _path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.json"

    def create(self, title: str, brief: str, created_by: str, assignee_id: str) -> Task:
        task = Task(
            id=uuid.uuid4().hex[:12],
            title=title,
            brief=brief,
            created_by=created_by,
            assignee_id=assignee_id,
            status="pending",
            created_at=datetime.now(UTC).isoformat(),
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(task.id).write_text(json.dumps(asdict(task)), encoding="utf-8")
        return task

    def get(self, task_id: str) -> Task | None:
        path = self._path(task_id)
        if not path.exists():
            return None
        return Task(**json.loads(path.read_text(encoding="utf-8")))

    def update_status(self, task_id: str, status: str, result: str | None = None) -> Task | None:
        task = self.get(task_id)
        if task is None:
            return None
        task.status = status
        if result is not None:
            task.result = result
        if status in ("done", "failed"):
            task.completed_at = datetime.now(UTC).isoformat()
        self._path(task_id).write_text(json.dumps(asdict(task)), encoding="utf-8")
        return task

    def for_assignee(self, assignee_id: str) -> list[Task]:
        if not self._dir.exists():
            return []
        out = []
        for path in self._dir.glob("*.json"):
            try:
                task = Task(**json.loads(path.read_text(encoding="utf-8")))
                if task.assignee_id == assignee_id and task.status in ("pending", "active"):
                    out.append(task)
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def all_active(self) -> list[Task]:
        if not self._dir.exists():
            return []
        out = []
        for path in self._dir.glob("*.json"):
            try:
                task = Task(**json.loads(path.read_text(encoding="utf-8")))
                if task.status in ("pending", "active"):
                    out.append(task)
            except (json.JSONDecodeError, TypeError):
                continue
        return out
```

- [ ] **Step 4: Run TaskStore tests**

```
uv run pytest tests/test_tasks.py -v
```
Expected: 9 PASSED

- [ ] **Step 5: Write assign_task tool tests**

```python
# tests/test_tools_task.py
import pytest
from clawbot.tasks import TaskStore
from clawbot.tools.task_tool import handle_assign_task


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks")


@pytest.mark.asyncio
async def test_handle_assign_task_creates_task(store):
    await handle_assign_task(
        {
            "action": "assign_task",
            "task_title": "Write ISA guide",
            "task_brief": "2026 rules, 500 words",
            "assignee_id": "cmo",
            "created_by": "ceo",
        },
        store=store,
    )
    tasks = store.for_assignee("cmo")
    assert len(tasks) == 1
    assert tasks[0].title == "Write ISA guide"
    assert tasks[0].created_by == "ceo"


@pytest.mark.asyncio
async def test_handle_assign_task_missing_title_skips(store):
    await handle_assign_task(
        {"action": "assign_task", "assignee_id": "cmo", "task_brief": "b"},
        store=store,
    )
    assert store.for_assignee("cmo") == []


@pytest.mark.asyncio
async def test_handle_assign_task_missing_assignee_skips(store):
    await handle_assign_task(
        {"action": "assign_task", "task_title": "Do thing", "task_brief": "b"},
        store=store,
    )
    assert store.all_active() == []
```

- [ ] **Step 6: Run to verify failure**

```
uv run pytest tests/test_tools_task.py -v
```
Expected: `ImportError`

- [ ] **Step 7: Create `src/clawbot/tools/task_tool.py`**

```python
"""Task assignment tool handler for DirectiveRouter."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.tasks import TaskStore

logger = logging.getLogger(__name__)


async def handle_assign_task(params: dict, store: "TaskStore") -> None:
    title = str(params.get("task_title", "")).strip()
    brief = str(params.get("task_brief", "")).strip()
    assignee_id = str(params.get("assignee_id", "")).strip()
    created_by = str(params.get("created_by", "unknown")).strip()
    if not title:
        logger.warning("assign_task missing 'task_title': %s", params)
        return
    if not assignee_id:
        logger.warning("assign_task missing 'assignee_id': %s", params)
        return
    task = store.create(title=title, brief=brief, created_by=created_by, assignee_id=assignee_id)
    logger.info("Task %s assigned to %s: %r", task.id, assignee_id, title)
```

- [ ] **Step 8: Run all task tests**

```
uv run pytest tests/test_tasks.py tests/test_tools_task.py -v
```
Expected: 12 PASSED

- [ ] **Step 9: Commit**

```
git add src/clawbot/tasks.py src/clawbot/tools/task_tool.py tests/test_tasks.py tests/test_tools_task.py
git commit -m "feat: add TaskStore and assign_task tool handler"
```

---

### Task 5: Publish-Product Escalation Handler

**Context:** `GumroadClient.create_product()` raises `GumroadProductCreationUnsupported` — the Gumroad API does not support product creation. The `publish_product` action instead formats a detailed brief and escalates to the operator so they can create it in the Gumroad dashboard.

**Files:**
- Create: `src/clawbot/tools/publishing.py`
- Create: `tests/test_tools_publishing.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_tools_publishing.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from clawbot.tools.publishing import handle_publish_product


@pytest.fixture
def bus():
    b = MagicMock()
    b.publish = AsyncMock()
    return b


@pytest.mark.asyncio
async def test_handle_publish_product_escalates_to_operator(bus):
    await handle_publish_product(
        {
            "action": "publish_product",
            "product_title": "UK ISA Guide 2026",
            "product_description": "Comprehensive guide to ISA rules",
            "price_gbp": 9.99,
        },
        bus=bus,
    )
    bus.publish.assert_awaited_once()
    topic, payload = bus.publish.call_args.args
    assert topic == "operator.escalation"
    assert "UK ISA Guide 2026" in payload["summary"]
    assert payload["severity"] == "request"


@pytest.mark.asyncio
async def test_handle_publish_product_missing_title_skips(bus):
    await handle_publish_product(
        {"action": "publish_product", "product_description": "desc"},
        bus=bus,
    )
    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_handle_publish_product_includes_price_in_escalation(bus):
    await handle_publish_product(
        {
            "action": "publish_product",
            "product_title": "Tax Guide",
            "product_description": "UK tax rules for freelancers",
            "price_gbp": 14.99,
        },
        bus=bus,
    )
    _, payload = bus.publish.call_args.args
    assert "14.99" in payload["detail"]
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_tools_publishing.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `src/clawbot/tools/publishing.py`**

```python
"""
Publish-product tool handler.

Gumroad's POST /v2/products returns 404 — product creation via API is unsupported.
This handler escalates a formatted product brief to the operator via the existing
escalation channel so they can create it in the Gumroad dashboard.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, UTC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.bus import MessageBus

logger = logging.getLogger(__name__)


async def handle_publish_product(params: dict, bus: "MessageBus") -> None:
    title = str(params.get("product_title", "")).strip()
    description = str(params.get("product_description", "")).strip()
    price_gbp = params.get("price_gbp", 0)

    if not title:
        logger.warning("publish_product missing 'product_title': %s", params)
        return

    detail = (
        f"**Product title:** {title}\n\n"
        f"**Description:**\n{description}\n\n"
        f"**Suggested price:** £{price_gbp}\n\n"
        "Create this product at https://app.gumroad.com/products/new "
        "then reply with the product URL."
    )
    payload = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(UTC).isoformat(),
        "severity": "request",
        "from_agent": "cmo",
        "summary": f"New product ready to publish: {title} (£{price_gbp})",
        "detail": detail,
        "correlation_id": "publish_product",
    }
    await bus.publish("operator.escalation", payload)
    logger.info("Product brief escalated to operator: %r", title)
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/test_tools_publishing.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```
git add src/clawbot/tools/publishing.py tests/test_tools_publishing.py
git commit -m "feat: publish_product handler — escalates formatted brief to operator (Gumroad API doesn't support creation)"
```

---

### Task 6: Wire DirectiveRouter into Scheduler

**Files:**
- Modify: `src/clawbot/scheduler.py`

- [ ] **Step 1: Add imports at top of scheduler.py**

```python
from clawbot.directive_router import DirectiveRouter
from clawbot.tasks import TaskStore
from clawbot.tools.hiring import handle_hire, handle_fire
from clawbot.tools.task_tool import handle_assign_task
from clawbot.tools.publishing import handle_publish_product
```

- [ ] **Step 2: Add `task_store` param to `Scheduler.__init__`**

Add `task_store: TaskStore | None = None` as the last parameter of `__init__`. Inside `__init__` body, add:

```python
        self._task_store = task_store
        self._router = self._build_router()
```

- [ ] **Step 3: Add `_build_router` method**

Add this method to the `Scheduler` class immediately after `__init__`:

```python
    def _build_router(self) -> DirectiveRouter:
        from clawbot.agent_factory import AgentFactory
        router = DirectiveRouter(self._bus)
        if self._registry is not None:
            factory = AgentFactory(registry=self._registry, agents_dir=self._agents_dir)
            router.register("hire", lambda p: handle_hire(p, factory=factory, pool=self._pool))
            router.register("fire", lambda p: handle_fire(p, factory=factory))
        if self._task_store is not None:
            router.register("assign_task", lambda p: handle_assign_task(p, store=self._task_store))
        router.register("publish_product", lambda p: handle_publish_product(p, bus=self._bus))
        router.register(
            "message",
            lambda p: __import__("clawbot.tools.messaging", fromlist=["handle_message"]).handle_message(
                p,
                from_agent=p.get("_source_topic", "unknown.directive").split(".")[0],
                bus=self._bus,
            ),
        )
        return router
```

- [ ] **Step 4: Add router task to `run_forever`**

In `run_forever`, add to the `tasks` list:

```python
            asyncio.create_task(self._router.run_forever(), name="directive-router"),
```

- [ ] **Step 5: Run all tests**

```
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```
git add src/clawbot/scheduler.py
git commit -m "feat: wire DirectiveRouter into Scheduler — executives can now hire, fire, assign tasks, publish product briefs, message each other"
```

---

### Task 7: Expand Executive Action Vocabulary in Prompts

**Files:**
- Modify: `src/clawbot/scheduler.py`

- [ ] **Step 1: Add `_ACTION_VOCABULARY` constant**

Add this constant in `scheduler.py` after the existing interval constants:

```python
_ACTION_VOCABULARY = """\
Output JSON with this structure:
{
  "action": "think | hire | fire | assign_task | publish_product | message | research",
  "directive": "one sentence — what you are doing and why",
  "priority": "high | medium | low",
  "next_wakeup_s": <integer 60-1800 — when to run your next cycle>,
  "escalate": null,

  // hire: spawn a new worker agent
  "role": "job title",
  "mandate": "measurable outcome this agent must achieve",
  "supervisor": "agent_id of direct manager (default: ceo)",

  // fire: terminate an underperforming agent
  "agent_id": "exact agent_id to terminate",

  // assign_task: create a tracked task for an agent or executive
  "task_title": "short task name",
  "task_brief": "full instructions the assignee needs to execute",
  "assignee_id": "agent_id or executive id (ceo/cfo/cmo/coo/cto)",
  "created_by": "your agent_id",

  // publish_product: escalate a product brief to the operator for Gumroad creation
  "product_title": "product name",
  "product_description": "what it is, who it's for, why they need it now",
  "price_gbp": <number>,

  // message: send a direct message to another agent's inbox
  "to": "agent_id",
  "content": "message text",

  // research: fetch a URL and store findings in company brain
  "url": "full URL to fetch",
  "question": "what to extract from the page",

  // escalate: set when operator input is required
  "escalate": {"severity": "info|request|warning|urgent", "summary": "...", "detail": "..."}
}
Use action=think when reflecting without triggering any tool.
next_wakeup_s: set 60-120 if urgent, 900-1800 if idle.\
"""
```

- [ ] **Step 2: Replace the prompt tail in `_run_executive_cycle`**

Find the prompt string ending in `" whenever the operator needs to act or be informed."` inside `_run_executive_cycle`. Replace the entire prompt tail (from `"What is your next action?"` onwards) with:

```python
                    f"What is your next action?\n{_ACTION_VOCABULARY}"
```

- [ ] **Step 3: Replace the same prompt tail in `_run_lieutenant_cycle`**

Same replacement in `_run_lieutenant_cycle`.

- [ ] **Step 4: Run all tests**

```
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```
git add src/clawbot/scheduler.py
git commit -m "feat: expand executive action vocabulary — agents know all available tools and can self-schedule"
```

---

## Phase 2: Self-Scheduling

### Task 8: Parse and clamp wakeup requests

**Files:**
- Modify: `src/clawbot/scheduler.py`
- Create: `tests/test_self_scheduling.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_self_scheduling.py
from clawbot.scheduler import _parse_next_wakeup, _clamp_wakeup


def test_parse_next_wakeup_from_json():
    assert _parse_next_wakeup('{"action": "think", "next_wakeup_s": 120}') == 120


def test_parse_next_wakeup_fenced():
    assert _parse_next_wakeup('```json\n{"action": "think", "next_wakeup_s": 300}\n```') == 300


def test_parse_next_wakeup_missing_field_returns_none():
    assert _parse_next_wakeup('{"action": "think"}') is None


def test_parse_next_wakeup_invalid_json_returns_none():
    assert _parse_next_wakeup("not json at all") is None


def test_parse_next_wakeup_non_integer_returns_none():
    assert _parse_next_wakeup('{"next_wakeup_s": "soon"}') is None


def test_clamp_wakeup_below_floor():
    assert _clamp_wakeup(10) == 60


def test_clamp_wakeup_above_ceiling():
    assert _clamp_wakeup(9999) == 1800


def test_clamp_wakeup_in_range():
    assert _clamp_wakeup(300) == 300


def test_clamp_wakeup_at_floor():
    assert _clamp_wakeup(60) == 60


def test_clamp_wakeup_at_ceiling():
    assert _clamp_wakeup(1800) == 1800
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_self_scheduling.py -v
```
Expected: `ImportError: cannot import name '_parse_next_wakeup'`

- [ ] **Step 3: Add functions to scheduler.py**

Add after the existing interval constants block:

```python
_WAKEUP_FLOOR_S = 60
_WAKEUP_CEILING_S = 1800
_WAKEUP_DEFAULT_S = 300


def _parse_next_wakeup(text: str) -> int | None:
    """Extract next_wakeup_s from agent response JSON. Returns None if absent or unparseable."""
    try:
        data = _extract_json(text)
        val = data.get("next_wakeup_s")
        if val is None:
            return None
        return int(val)
    except Exception:
        return None


def _clamp_wakeup(seconds: int) -> int:
    return max(_WAKEUP_FLOOR_S, min(_WAKEUP_CEILING_S, seconds))
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/test_self_scheduling.py -v
```
Expected: 10 PASSED

- [ ] **Step 5: Commit**

```
git add src/clawbot/scheduler.py tests/test_self_scheduling.py
git commit -m "feat: add _parse_next_wakeup and _clamp_wakeup for self-scheduling"
```

---

### Task 9: Use self-declared wakeup in executive loops

**Files:**
- Modify: `src/clawbot/scheduler.py`

- [ ] **Step 1: Update `_run_executive_cycle` return type and value**

Change signature to `async def _run_executive_cycle(self) -> int | None:`.

After `response = await self._pool.complete(...)`, add:
```python
            requested_wakeup = _parse_next_wakeup(response)
```

At the very end of the method (after `await self._write_company_metrics()`), add:
```python
        return requested_wakeup if success else None
```

Add `requested_wakeup: int | None = None` as a local variable before the `try` block so it's defined even if the call fails.

- [ ] **Step 2: Update `_executive_loop` to use the returned wakeup**

Replace the existing sleep logic:

```python
    async def _executive_loop(self) -> None:
        while True:
            requested = await self._run_executive_cycle()
            if requested is not None:
                interval = _clamp_wakeup(requested)
            elif _is_skeleton_crew_hour():
                interval = EXECUTIVE_SKELETON_INTERVAL_S
            else:
                interval = _WAKEUP_DEFAULT_S
            await asyncio.sleep(interval)
```

- [ ] **Step 3: Update `_run_lieutenant_cycle` to return wakeup**

Change signature to `async def _run_lieutenant_cycle(self, agent_id: str) -> int | None:`.

Add `requested_wakeup: int | None = None` before the `try` block.

After `response = await self._pool.complete(...)`, add:
```python
                requested_wakeup = _parse_next_wakeup(response)
```

At the end of the method, add:
```python
        return requested_wakeup if success else None
```

- [ ] **Step 4: Update `_lieutenant_loop` to use the returned wakeup**

```python
    async def _lieutenant_loop(self, agent_id: str) -> None:
        while True:
            requested = await self._run_lieutenant_cycle(agent_id)
            if requested is not None:
                interval = _clamp_wakeup(requested)
            elif _is_skeleton_crew_hour():
                interval = EXECUTIVE_SKELETON_INTERVAL_S
            else:
                interval = _WAKEUP_DEFAULT_S
            await asyncio.sleep(interval)
```

- [ ] **Step 5: Run all tests**

```
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```
git add src/clawbot/scheduler.py
git commit -m "feat: self-scheduling — executives declare next_wakeup_s, scheduler honors it (60–1800s)"
```

---

## Phase 3: Agent Inboxes

### Task 10: Message handler + inbox publish

**Files:**
- Create: `src/clawbot/tools/messaging.py`
- Create: `tests/test_agent_inbox.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_agent_inbox.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from clawbot.tools.messaging import handle_message, format_inbox_messages


@pytest.fixture
def bus():
    b = MagicMock()
    b.publish = AsyncMock()
    return b


@pytest.mark.asyncio
async def test_handle_message_publishes_to_inbox(bus):
    await handle_message(
        {"action": "message", "to": "cmo", "content": "Focus on SEO guides this week"},
        from_agent="ceo",
        bus=bus,
    )
    bus.publish.assert_awaited_once()
    topic, payload = bus.publish.call_args.args
    assert topic == "inbox.cmo"
    assert payload["from"] == "ceo"
    assert payload["content"] == "Focus on SEO guides this week"


@pytest.mark.asyncio
async def test_handle_message_missing_to_skips(bus):
    await handle_message({"action": "message", "content": "hello"}, from_agent="ceo", bus=bus)
    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_missing_content_skips(bus):
    await handle_message({"action": "message", "to": "cmo"}, from_agent="ceo", bus=bus)
    bus.publish.assert_not_called()


def test_format_inbox_messages_empty():
    assert format_inbox_messages([]) == ""


def test_format_inbox_messages_formats_correctly():
    messages = [
        {"from": "ceo", "content": "Focus on revenue", "ts": "2026-05-16T10:00:00"},
        {"from": "cfo", "content": "Cash is tight", "ts": "2026-05-16T10:01:00"},
    ]
    result = format_inbox_messages(messages)
    assert "ceo" in result
    assert "Focus on revenue" in result
    assert "cfo" in result
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_agent_inbox.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `src/clawbot/tools/messaging.py`**

```python
"""Agent-to-agent messaging tool handler."""
from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.bus import MessageBus

logger = logging.getLogger(__name__)


async def handle_message(params: dict, from_agent: str, bus: "MessageBus") -> None:
    to = str(params.get("to", "")).strip()
    content = str(params.get("content", "")).strip()
    if not to:
        logger.warning("message directive missing 'to': %s", params)
        return
    if not content:
        logger.warning("message directive missing 'content': %s", params)
        return
    payload = {
        "from": from_agent,
        "content": content,
        "ts": datetime.now(UTC).isoformat(),
    }
    await bus.publish(f"inbox.{to}", payload)
    logger.info("Message %s → %s: %s", from_agent, to, content[:80])


def format_inbox_messages(messages: list[dict]) -> str:
    if not messages:
        return ""
    lines = ["Messages from colleagues:"]
    for msg in messages:
        lines.append(f"- {msg.get('from', 'unknown')}: {msg.get('content', '')}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/test_agent_inbox.py -v
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```
git add src/clawbot/tools/messaging.py tests/test_agent_inbox.py
git commit -m "feat: agent inbox messaging — executives can send messages to each other"
```

---

### Task 11: Executive cycles read inbox before thinking

**Files:**
- Modify: `src/clawbot/scheduler.py`

- [ ] **Step 1: Add `_read_agent_inbox` to Scheduler**

```python
    async def _read_agent_inbox(self, agent_id: str) -> str:
        """Read up to 5 pending inbox messages for this executive. Returns '' if none."""
        topic = f"inbox.{agent_id}"
        try:
            await self._bus.subscribe(topic)
            messages = await self._bus.read_and_ack(
                topic, f"exec-{agent_id}-inbox", count=5, block_ms=100,
            )
        except Exception as exc:
            logger.warning("Inbox read failed for %s: %s", agent_id, exc)
            return ""
        from clawbot.tools.messaging import format_inbox_messages
        return format_inbox_messages(messages)
```

- [ ] **Step 2: Inject inbox into `_run_executive_cycle` prompt**

Before building the `messages` list in `_run_executive_cycle`, add:

```python
        inbox_block = await self._read_agent_inbox("ceo")
```

Update the user content to include inbox_block:

```python
                "content": (
                    f"Current metrics:\n{json.dumps(metrics, indent=2)}"
                    f"{board_directive}{recent_decisions}"
                    + (f"\n\n{inbox_block}" if inbox_block else "")
                    + f"\n\nWhat is your next action?\n{_ACTION_VOCABULARY}"
                ),
```

- [ ] **Step 3: Inject inbox into `_run_lieutenant_cycle` prompt**

Same pattern. Before building `messages`, add:

```python
        inbox_block = await self._read_agent_inbox(agent_id)
```

Update the user content:

```python
                "content": (
                    f"Current metrics:\n{json.dumps(metrics, indent=2)}\n"
                    + (f"\n{inbox_block}\n" if inbox_block else "")
                    + f"\nWhat is your next action?\n{_ACTION_VOCABULARY}"
                ),
```

- [ ] **Step 4: Run all tests**

```
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```
git add src/clawbot/scheduler.py
git commit -m "feat: executives read peer inbox before each cycle — enables CEO→CMO delegation"
```

---

## Phase 4: Web Research Tool

### Task 12: Web research tool + brain storage

**Files:**
- Create: `src/clawbot/tools/web_research.py`
- Create: `tests/test_tools_web_research.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_tools_web_research.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clawbot.tools.web_research import fetch_and_summarise


@pytest.fixture
def pool():
    p = MagicMock()
    p.complete = AsyncMock(return_value="Summary: ISA limit is £20,000 in 2026.")
    return p


@pytest.mark.asyncio
async def test_fetch_and_summarise_calls_pool(pool):
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "<html><body><p>The ISA limit for 2026 is £20,000.</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        result = await fetch_and_summarise(
            url="https://example.com/isa",
            question="What is the ISA limit in 2026?",
            pool=pool,
        )
    assert "20,000" in result
    pool.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_and_summarise_returns_error_on_http_failure(pool):
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_client
        import httpx
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        result = await fetch_and_summarise(
            url="https://example.com",
            question="anything",
            pool=pool,
        )
    assert result.startswith("ERROR:")
    pool.complete.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_tools_web_research.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `src/clawbot/tools/web_research.py`**

```python
"""Fetch a URL, strip HTML, and summarise with an LLM call."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from clawbot.llm_pool import LLMPool

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s{2,}")
HTTP_TIMEOUT_S = 20.0
MAX_CONTENT_CHARS = 4000


def _strip_html(html: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()


async def fetch_and_summarise(url: str, question: str, pool: "LLMPool") -> str:
    """Fetch url, extract text, ask pool to answer question. Returns summary or ERROR: string."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            raw_text = _strip_html(response.text)[:MAX_CONTENT_CHARS]
    except httpx.HTTPError as exc:
        logger.warning("Web fetch failed for %s: %s", url, exc)
        return f"ERROR: could not fetch {url} — {exc}"

    messages = [
        {"role": "system", "content": "You are a research assistant. Answer only from the provided text."},
        {"role": "user", "content": f"Text from {url}:\n\n{raw_text}\n\nQuestion: {question}"},
    ]
    return await pool.complete(messages, tier="worker", max_tokens=400)
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/test_tools_web_research.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Register research handler in `_build_router` in scheduler.py**

Inside `_build_router`, add after the other registrations:

```python
        async def _handle_research(params: dict) -> None:
            from clawbot.tools.web_research import fetch_and_summarise
            url = str(params.get("url", "")).strip()
            question = str(params.get("question", "")).strip()
            if not url or not question:
                logger.warning("research directive missing url or question: %s", params)
                return
            result = await fetch_and_summarise(url=url, question=question, pool=self._pool)
            if self._brain is not None and not result.startswith("ERROR:"):
                await self._brain.write(
                    content=f"Research: {question}\nSource: {url}\nFindings: {result}",
                    category="decision",
                )
            logger.info("Research complete for %s: %s", url, result[:120])

        router.register("research", _handle_research)
```

- [ ] **Step 6: Run all tests**

```
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```
git add src/clawbot/tools/web_research.py tests/test_tools_web_research.py src/clawbot/scheduler.py
git commit -m "feat: web research tool — agents can fetch URLs and store findings in company brain"
```

---

## Phase 5: Lateral Thought

### Task 13: LateralThinker — weekly cross-signal synthesis

**Files:**
- Create: `src/clawbot/lateral_thinker.py`
- Create: `tests/test_lateral_thinker.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_lateral_thinker.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from clawbot.lateral_thinker import LateralThinker


@pytest.fixture
def pool():
    p = MagicMock()
    p.complete = AsyncMock(return_value='[{"idea": "ISA + freelance tax guide", "signals_combined": ["ISA", "freelance NI"], "rationale": "both trend together in March", "estimated_value": "£100-£300"}]')
    return p


@pytest.fixture
def brain():
    b = MagicMock()
    b.search = AsyncMock(return_value=[
        MagicMock(content="UK ISA limits raised to £25k"),
        MagicMock(content="Freelancer NI confusion after Spring Budget"),
        MagicMock(content="Self-assessment deadline confusion increasing"),
    ])
    b.write = AsyncMock()
    return b


@pytest.mark.asyncio
async def test_synthesise_calls_pool_with_signals(pool, brain):
    thinker = LateralThinker(pool=pool, brain=brain)
    await thinker.synthesise()
    pool.complete.assert_awaited_once()
    prompt_content = pool.complete.call_args.args[0][1]["content"]
    assert "ISA" in prompt_content
    assert "Freelancer" in prompt_content


@pytest.mark.asyncio
async def test_synthesise_writes_insights_to_brain(pool, brain):
    thinker = LateralThinker(pool=pool, brain=brain)
    await thinker.synthesise()
    brain.write.assert_awaited()
    written = brain.write.call_args.kwargs.get("content") or brain.write.call_args.args[0]
    assert "ISA" in written or "freelance" in written.lower()


@pytest.mark.asyncio
async def test_synthesise_with_too_few_signals_returns_early(pool, brain):
    brain.search = AsyncMock(return_value=[MagicMock(content="one signal")])
    thinker = LateralThinker(pool=pool, brain=brain)
    await thinker.synthesise()
    pool.complete.assert_not_called()
    brain.write.assert_not_called()


@pytest.mark.asyncio
async def test_synthesise_handles_llm_parse_failure_gracefully(pool, brain):
    pool.complete = AsyncMock(return_value="not valid json")
    thinker = LateralThinker(pool=pool, brain=brain)
    await thinker.synthesise()  # must not raise
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/test_lateral_thinker.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `src/clawbot/lateral_thinker.py`**

```python
"""
Weekly lateral thought loop — cross-signal synthesis.

Reads top-10 market signals from the brain and asks the LLM to find
non-obvious intersections: product ideas that emerge from combining
two or more signals, not from scoring each one individually.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawbot.llm_pool import LLMPool
    from clawbot.company_brain import CompanyBrain

logger = logging.getLogger(__name__)

SYNTHESIS_INTERVAL_S = 7 * 86_400
MIN_SIGNALS = 3

_SYNTHESIS_PROMPT = """\
You are a lateral thinking analyst for a UK digital products business.

Below are {n} trending market signals observed recently:

{signals}

Find 2-3 non-obvious product ideas that emerge from combining two or more of
these signals. Do NOT restate a single signal as a product. Look for intersections:
what unmet need spans multiple signals simultaneously?

Respond with a JSON array:
[
  {{
    "idea": "product title",
    "signals_combined": ["signal excerpt 1", "signal excerpt 2"],
    "rationale": "why this intersection is underserved right now",
    "estimated_value": "rough revenue estimate e.g. £50-£300 for a PDF guide"
  }}
]
Return [] if nothing genuine emerges at >0.6 confidence.\
"""


class LateralThinker:
    def __init__(self, pool: "LLMPool", brain: "CompanyBrain") -> None:
        self._pool = pool
        self._brain = brain

    async def synthesise(self) -> None:
        signals = await self._brain.search(
            query="trending opportunity market signal UK", k=10, category="market_signal"
        )
        if len(signals) < MIN_SIGNALS:
            logger.info("Lateral thinker: %d signals — skipping (need ≥%d)", len(signals), MIN_SIGNALS)
            return

        signal_text = "\n".join(f"{i+1}. {s.content[:200]}" for i, s in enumerate(signals))
        messages = [
            {"role": "system", "content": "You are a lateral thinking analyst. Respond only with valid JSON arrays."},
            {"role": "user", "content": _SYNTHESIS_PROMPT.format(n=len(signals), signals=signal_text)},
        ]
        try:
            raw = await self._pool.complete(messages, tier="executive", max_tokens=800)
            ideas = json.loads(raw)
        except Exception as exc:
            logger.warning("Lateral thinker parse failed: %s", exc)
            return

        if not isinstance(ideas, list):
            return

        for idea in ideas:
            if not isinstance(idea, dict):
                continue
            content = (
                f"LATERAL INSIGHT: {idea.get('idea', '')}\n"
                f"Signals: {', '.join(idea.get('signals_combined', []))}\n"
                f"Rationale: {idea.get('rationale', '')}\n"
                f"Est. value: {idea.get('estimated_value', '')}"
            )
            try:
                await self._brain.write(content=content, category="lateral_insight")
                logger.info("Lateral insight: %s", idea.get("idea", "")[:80])
            except Exception as exc:
                logger.warning("Brain write of lateral insight failed: %s", exc)

    async def run_continuous(self) -> None:
        while True:
            try:
                await self.synthesise()
            except Exception as exc:
                logger.error("Lateral thinker cycle failed: %s", exc)
            await asyncio.sleep(SYNTHESIS_INTERVAL_S)
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/test_lateral_thinker.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Wire into `Scheduler.run_forever`**

In `run_forever`, inside the `if self._brain is not None:` block (alongside `_brain_retention_loop`), add:

```python
            from clawbot.lateral_thinker import LateralThinker
            thinker = LateralThinker(pool=self._pool, brain=self._brain)
            tasks.append(asyncio.create_task(thinker.run_continuous(), name="lateral-thinker"))
```

- [ ] **Step 6: Run all tests**

```
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```
git add src/clawbot/lateral_thinker.py tests/test_lateral_thinker.py src/clawbot/scheduler.py
git commit -m "feat: lateral thought loop — weekly cross-signal synthesis generates novel product ideas"
```

---

## Phase 6: Wire TaskStore in main.py

### Task 14: Construct TaskStore at startup

**Files:**
- Modify: `src/clawbot/main.py`

- [ ] **Step 1: Read `src/clawbot/main.py`**

Open the file and find where `Scheduler(...)` is constructed.

- [ ] **Step 2: Add TaskStore construction**

Add near the top of the startup sequence (after any existing Path/metrics setup):

```python
from clawbot.tasks import TaskStore
from pathlib import Path

task_store = TaskStore(Path("/metrics/tasks"))
```

Pass it to the Scheduler constructor:

```python
scheduler = Scheduler(
    ...,          # all existing args unchanged
    task_store=task_store,
)
```

- [ ] **Step 3: Run full test suite**

```
uv run pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 4: Commit**

```
git add src/clawbot/main.py
git commit -m "feat: wire TaskStore into Scheduler at startup"
```

---

## Self-Review

**Spec coverage:**

| Vision requirement | Delivered by |
|---|---|
| Nothing hardcoded — agents self-schedule | Phase 2 (Tasks 8–9) |
| Hiring staff | Phase 1 Tasks 3, 6 |
| Running tasks (assign + track) | Phase 1 Tasks 4, 6 |
| Agents publishing product ideas | Phase 1 Task 5 |
| Agents communicating with each other | Phase 3 Tasks 10–11 |
| Agents researching the web | Phase 4 Task 12 |
| Lateral thought / novel ideas | Phase 5 Task 13 |
| Real actions (not just unread text) | Phase 1 Tasks 2, 6–7 |
| Permanent operation | No new work needed — system already loops forever; self-scheduling removes the hardcoded throttle |

**Known gap — follow-on plan needed:**
Worker agents spawned by AgentFactory run `_worker_agent_loop`, which currently doesn't read their task queue from `TaskStore`. A follow-on plan should add task injection: when `_worker_agent_loop` wakes, it reads `task_store.for_assignee(agent_id)`, appends pending tasks to the prompt, and marks them `active`. Without this, `assign_task` creates tasks but workers never see them.
