"""Per-pack load + representative-call tests for the SEO pack."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clawbot.skill_ctx import make_noop_ctx
from clawbot.skill_registry import SkillRegistry

PACK_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"
EXPECTED_SEO_SKILLS = {
    "gsc_query", "bing_webmaster_query", "serp_check", "keyword_research",
    "backlink_audit", "sitemap_generate", "sitemap_submit",
    "schema_org_generate", "lighthouse_audit", "robots_txt_check",
}


@pytest.fixture(scope="module")
def registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=PACK_DIR)
    reg.discover()
    return reg


def test_seo_pack_loads(registry: SkillRegistry) -> None:
    loaded = set(registry.list_names())
    missing = EXPECTED_SEO_SKILLS - loaded
    assert not missing, f"SEO pack missing skills: {missing}"


def test_schema_org_generate_pure(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(registry.call(
        "schema_org_generate",
        {"schema_type": "Product",
         "properties": {"name": "Widget", "price": "9.99"}},
        ctx,
    ))
    assert record.ok is True, record.error
    doc = json.loads(record.result["json_ld"])
    assert doc["@type"] == "Product"
    assert doc["@context"] == "https://schema.org"
    assert doc["name"] == "Widget"
    assert "<script" in record.result["script_tag"]


def test_robots_txt_check_parses(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200,
        "text": ("User-agent: *\n"
                 "Disallow: /private\n"
                 "Allow: /public\n"
                 "Sitemap: https://example.com/sitemap.xml\n"),
        "headers": {},
    })
    record = asyncio.run(registry.call(
        "robots_txt_check", {"base_url": "https://example.com"}, ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["disallow"] == ["/private"]
    assert record.result["allow"] == ["/public"]
    assert record.result["sitemaps"] == ["https://example.com/sitemap.xml"]


def test_sitemap_generate_writes_urlset(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.fs.list = AsyncMock(return_value=[  # type: ignore[method-assign]
        "data/published/a.html", "data/published/b.html", "data/published/skip.txt",
    ])
    ctx.fs.write = AsyncMock(return_value=None)  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "sitemap_generate",
        {"base_url": "https://example.com/", "source_dir": "data/published"},
        ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["url_count"] == 2
    args, _ = ctx.fs.write.call_args
    xml = args[1]
    assert "<urlset" in xml
    assert "https://example.com/a" in xml
    assert "https://example.com/b" in xml


def test_sitemap_submit_pings_both(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.http.get = AsyncMock(return_value={"status": 200, "text": "", "headers": {}})  # type: ignore[method-assign]
    record = asyncio.run(registry.call(
        "sitemap_submit", {"sitemap_url": "https://example.com/sitemap.xml"}, ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["google_status"] == 200
    assert record.result["bing_status"] == 200
    assert ctx.http.get.call_count == 2


def test_gsc_query_returns_empty_without_token(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(registry.call(
        "gsc_query",
        {"site_url": "https://example.com/", "start_date": "2026-01-01", "end_date": "2026-01-31"},
        ctx,
    ))
    assert record.ok is True
    assert record.result["status"] == 401
    assert record.result["rows"] == []


def test_lighthouse_audit_parses_categories(registry: SkillRegistry) -> None:
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200,
        "text": json.dumps({
            "lighthouseResult": {"categories": {
                "performance": {"score": 0.92},
                "accessibility": {"score": 0.88},
                "seo": {"score": 1.0},
                "best-practices": {"score": 0.75},
            }},
        }),
        "headers": {},
    })
    record = asyncio.run(registry.call(
        "lighthouse_audit", {"url": "https://example.com"}, ctx,
    ))
    assert record.ok is True, record.error
    assert record.result["performance"] == 0.92
    assert record.result["seo"] == 1.0
    assert record.result["best_practices"] == 0.75
