"""Per-pack load + representative-call tests for the intel/research pack."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clawbot.skill_ctx import make_noop_ctx
from clawbot.skill_registry import SkillRegistry

PACK_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"
EXPECTED_INTEL_SKILLS = {
    "web_deep_research", "web_diff_page", "news_monitor_topic",
    "social_listen_brand", "competitor_pricing_scrape", "github_trending",
    "arxiv_search", "arxiv_summarize", "reviews_scrape_g2",
    "glassdoor_scrape_company", "crunchbase_lookup",
}


@pytest.fixture(scope="module")
def registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=PACK_DIR)
    reg.discover()
    return reg


def test_intel_pack_loads(registry: SkillRegistry) -> None:
    loaded = set(registry.list_names())
    missing = EXPECTED_INTEL_SKILLS - loaded
    assert not missing, f"intel pack missing skills: {missing}"


def test_web_diff_page_first_seen(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200, "text": "alpha\nbeta\ngamma", "headers": {},
    })
    ctx.fs.read = AsyncMock(side_effect=FileNotFoundError())  # type: ignore[method-assign]
    ctx.fs.write = AsyncMock(return_value=None)  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "web_diff_page", {"url": "https://example.com"}, ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["is_first_seen"] is True
    assert "alpha" in record.result["added"]
    ctx.fs.write.assert_called_once()


def test_web_diff_page_detects_diff(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200, "text": "alpha\nbeta\nnew_line", "headers": {},
    })
    ctx.fs.read = AsyncMock(return_value="alpha\nbeta\nold_line")  # type: ignore[method-assign]
    ctx.fs.write = AsyncMock(return_value=None)  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "web_diff_page", {"url": "https://example.com"}, ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["is_first_seen"] is False
    assert "new_line" in record.result["added"]
    assert "old_line" in record.result["removed"]


def test_arxiv_search_parses_atom(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    atom = """<?xml version="1.0"?>
    <feed>
      <entry>
        <id>http://arxiv.org/abs/2401.00001</id>
        <title>Test Paper</title>
        <summary>An abstract here</summary>
        <published>2026-05-01</published>
        <author><name>Alice</name></author>
        <author><name>Bob</name></author>
      </entry>
    </feed>"""
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200, "text": atom, "headers": {},
    })
    record = asyncio.run(registry.call(
        "arxiv_search", {"query": "diffusion", "max_results": 5}, ctx,
    ))
    assert record.ok is True, record.error
    assert len(record.result["papers"]) == 1
    p = record.result["papers"][0]
    assert "Test Paper" in p["title"]
    assert p["authors"] == ["Alice", "Bob"]


def test_github_trending_parses_json(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200,
        "text": json.dumps({"items": [
            {"full_name": "owner/repo", "html_url": "https://github.com/owner/repo",
             "stargazers_count": 1234, "description": "a thing", "language": "Python"},
        ]}),
        "headers": {},
    })
    record = asyncio.run(registry.call(
        "github_trending", {"language": "python", "days": 7, "per_page": 10}, ctx,
    ))
    assert record.ok is True, record.error
    assert len(record.result["repos"]) == 1
    assert record.result["repos"][0]["name"] == "owner/repo"
    assert record.result["repos"][0]["stars"] == 1234


def test_crunchbase_lookup_no_key(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(registry.call(
        "crunchbase_lookup", {"company_slug": "stripe"}, ctx,
    ))
    assert record.ok is True
    assert record.result["status"] == 401


def test_news_monitor_filters_seen(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    rss = ("<rss><channel>"
           "<item><title>A</title><link>http://a/1</link></item>"
           "<item><title>B</title><link>http://b/2</link></item>"
           "</channel></rss>")
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200, "text": rss, "headers": {},
    })
    ctx.fs.read = AsyncMock(return_value="http://a/1")  # type: ignore[method-assign]
    ctx.fs.write = AsyncMock(return_value=None)  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "news_monitor_topic", {"topic": "ai", "max_items": 10}, ctx,
    ))
    assert record.ok is True, record.error
    titles = [it["title"] for it in record.result["new_items"]]
    assert "B" in titles
    assert "A" not in titles
    assert record.result["total_fetched"] == 2


def test_web_deep_research_synthesizes(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.search.search = AsyncMock(return_value=[  # type: ignore[method-assign]
        {"url": "https://a", "title": "A", "content": "A says X"},
        {"url": "https://b", "title": "B", "content": "B says Y"},
    ])
    ctx.llm.complete = AsyncMock(return_value="Summary [1] [2].")  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "web_deep_research", {"topic": "X versus Y", "max_results": 2}, ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["summary"] == "Summary [1] [2]."
    assert len(record.result["sources"]) == 2
