import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from clawbot.chat import (
    append_operator_message, OperatorInbox, OperatorMessage,
    respond_to_operator, CHAT_SYSTEM_TAIL,
)


# ── Inbox round-trip ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_append_writes_inbox_jsonl(tmp_path):
    await append_operator_message(tmp_path, "hey, how's revenue today?")
    path = tmp_path / "operator_inbox.jsonl"
    assert path.exists()
    line = json.loads(path.read_text().strip())
    assert line["text"] == "hey, how's revenue today?"


@pytest.mark.asyncio
async def test_append_truncates_oversize_text(tmp_path):
    await append_operator_message(tmp_path, "x" * 10_000)
    line = json.loads((tmp_path / "operator_inbox.jsonl").read_text().strip())
    assert len(line["text"]) == 4000


def test_drain_empty_returns_empty(tmp_path):
    inbox = OperatorInbox(tmp_path)
    assert inbox.drain_new_messages() == []


@pytest.mark.asyncio
async def test_drain_returns_new_messages(tmp_path):
    await append_operator_message(tmp_path, "first")
    await append_operator_message(tmp_path, "second")
    inbox = OperatorInbox(tmp_path)
    drained = inbox.drain_new_messages()
    assert len(drained) == 2
    assert drained[0].text == "first"


@pytest.mark.asyncio
async def test_drain_is_idempotent(tmp_path):
    await append_operator_message(tmp_path, "only message")
    inbox = OperatorInbox(tmp_path)
    first = inbox.drain_new_messages()
    second = inbox.drain_new_messages()
    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_drain_picks_up_messages_appended_after_first_drain(tmp_path):
    await append_operator_message(tmp_path, "before")
    inbox = OperatorInbox(tmp_path)
    inbox.drain_new_messages()
    await append_operator_message(tmp_path, "after")
    assert inbox.drain_new_messages()[0].text == "after"


def test_drain_skips_malformed_lines(tmp_path):
    path = tmp_path / "operator_inbox.jsonl"
    path.write_text(
        '{"ts": "2026-01-01", "text": "ok"}\n'
        'garbage\n'
        '{"ts": "2026-01-01", "text": "fine"}\n',
        encoding="utf-8",
    )
    drained = OperatorInbox(tmp_path).drain_new_messages()
    assert len(drained) == 2


# ── respond_to_operator ─────────────────────────────────────────────────────


def _write_ceo_soul(tmp_path, content: str = "## IMMUTABLE\nCEO mandate.\n## MUTABLE\n### x\nstuff"):
    p = tmp_path / "ceo" / "SOUL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_respond_returns_llm_text_stripped(tmp_path):
    _write_ceo_soul(tmp_path)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="  hey — revenue is £0 still, working on it  ")
    response = await respond_to_operator(
        pool=pool,
        agents_dir=tmp_path,
        metrics_dir=tmp_path / "metrics",
        message_text="how's revenue?",
    )
    assert response == "hey — revenue is £0 still, working on it"


@pytest.mark.asyncio
async def test_respond_prompt_includes_chat_system_tail(tmp_path):
    _write_ceo_soul(tmp_path)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="ok")
    await respond_to_operator(
        pool=pool, agents_dir=tmp_path,
        metrics_dir=tmp_path / "metrics", message_text="hi",
    )
    system_prompt = pool.complete.call_args.args[0][0]["content"]
    assert "conversational register" in system_prompt.lower()
    assert CHAT_SYSTEM_TAIL.strip().split("\n")[0] in system_prompt


@pytest.mark.asyncio
async def test_respond_includes_metrics_when_present(tmp_path):
    _write_ceo_soul(tmp_path)
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "company_metrics.json").write_text(
        json.dumps({"revenue_7d_gbp": 18.5, "worker_count": 2, "timestamp": "2026-05-16"}),
    )
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="ok")
    await respond_to_operator(
        pool=pool, agents_dir=tmp_path, metrics_dir=metrics_dir, message_text="status?",
    )
    user_msg = pool.complete.call_args.args[0][1]["content"]
    assert "18.50" in user_msg
    assert "workers: 2" in user_msg


@pytest.mark.asyncio
async def test_respond_handles_missing_metrics(tmp_path):
    _write_ceo_soul(tmp_path)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="ok")
    await respond_to_operator(
        pool=pool, agents_dir=tmp_path,
        metrics_dir=tmp_path / "metrics", message_text="hi",
    )
    user_msg = pool.complete.call_args.args[0][1]["content"]
    assert "no metrics yet" in user_msg.lower()


@pytest.mark.asyncio
async def test_respond_returns_empty_string_on_llm_failure(tmp_path):
    _write_ceo_soul(tmp_path)
    pool = MagicMock()
    pool.complete = AsyncMock(side_effect=RuntimeError("rate-limited"))
    response = await respond_to_operator(
        pool=pool, agents_dir=tmp_path,
        metrics_dir=tmp_path / "metrics", message_text="hi",
    )
    assert response == ""


@pytest.mark.asyncio
async def test_respond_uses_brain_when_message_is_substantive(tmp_path):
    _write_ceo_soul(tmp_path)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="ok")
    brain = MagicMock()
    fake_entry = MagicMock()
    fake_entry.content = "Last week we pivoted away from r/ContractorUK"
    brain.search = AsyncMock(return_value=[fake_entry])

    await respond_to_operator(
        pool=pool, agents_dir=tmp_path,
        metrics_dir=tmp_path / "metrics",
        message_text="what's the current marketing approach?",  # >20 chars
        brain=brain,
    )
    user_msg = pool.complete.call_args.args[0][1]["content"]
    assert "ContractorUK" in user_msg


@pytest.mark.asyncio
async def test_respond_skips_brain_for_trivial_messages(tmp_path):
    _write_ceo_soul(tmp_path)
    pool = MagicMock()
    pool.complete = AsyncMock(return_value="ok")
    brain = MagicMock()
    brain.search = AsyncMock()

    await respond_to_operator(
        pool=pool, agents_dir=tmp_path,
        metrics_dir=tmp_path / "metrics",
        message_text="hi",  # too short
        brain=brain,
    )
    brain.search.assert_not_called()


# ── OperatorMessage dataclass ───────────────────────────────────────────────


def test_operator_message_dataclass():
    m = OperatorMessage(ts="2026-05-16T10:00:00+00:00", text="hello")
    assert m.text == "hello"
