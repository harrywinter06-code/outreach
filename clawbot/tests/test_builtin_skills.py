import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import make_noop_ctx

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


@pytest.fixture(scope="module")
def builtin_registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


EXPECTED_BUILTINS = {
    "http_fetch", "http_post", "llm_complete", "vector_search", "vector_write",
    "secret_get", "fs_read", "fs_write", "fs_list", "sql_query",
    "operator_message", "operator_request_approval", "time_now", "bus_publish",
    "worker_spawn", "worker_fire", "skill_request",
    "account_create", "account_get", "account_list", "account_mark_zombie",
    "stripe_issue_card", "stripe_freeze_card", "stripe_list_authorizations",
    # Phase H — Task 31 writing pack
    "write_long_form_article", "write_tweet_thread", "write_linkedin_post",
    "write_cold_email", "write_landing_page_copy", "write_case_study",
    "summarize", "translate", "grammar_check", "readability_score",
    "tone_rewrite",
    # Phase H — Task 25 revenue pack
    "gumroad_list_products", "gumroad_sales_last_7d", "gumroad_get_sale",
    "paypal_create_order", "paypal_capture_order", "paypal_list_transactions",
    "crypto_generate_receive_address", "crypto_check_balance",
    "stripe_subscription_create", "stripe_subscription_cancel",
    "revenue_aggregate_today_gbp",
    # Phase H — Task 27 publishing pack
    "substack_publish", "medium_publish", "dev_to_publish", "hashnode_publish",
    "bluesky_post", "mastodon_post", "rss_publish", "buffer_schedule",
    "newsletter_send", "youtube_upload",
    # Phase H — Task 29 outreach + CRM pack
    "hunter_find_email", "apollo_search_contacts",
    "email_warmup_send", "email_warmup_inbox_clean",
    "email_send_cold", "email_send_followup_sequence",
    "email_classify_reply", "email_suppress",
    "crm_upsert_lead", "crm_advance_stage", "lead_score",
    # Phase H — Session B (research/experiments/browser/media/SEO)
    "experiment_create", "experiment_record_observation",
    "experiment_compute_significance", "bandit_allocate_budget",
    "experiment_kill_underperformer", "experiment_summarize",
    "browser_signup", "browser_form_fill", "browser_extract_structured",
    "browser_solve_captcha", "browser_save_session", "browser_load_session",
    "browser_navigate_and_record", "browser_screenshot_element",
    "gsc_query", "bing_webmaster_query", "serp_check", "keyword_research",
    "backlink_audit", "sitemap_generate", "sitemap_submit",
    "schema_org_generate", "lighthouse_audit", "robots_txt_check",
    "web_deep_research", "web_diff_page", "news_monitor_topic",
    "social_listen_brand", "competitor_pricing_scrape", "github_trending",
    "arxiv_search", "arxiv_summarize", "reviews_scrape_g2",
    "glassdoor_scrape_company", "crunchbase_lookup",
    "video_generate", "video_subtitle", "video_dub",
    "podcast_generate", "logo_generate", "favicon_generate",
    "image_remove_bg", "image_upscale", "screenshot_annotate",
    # Phase H — Task 36 support pack
    "support_send_email_reply", "support_assign_ticket", "support_canned_response",
    "chat_widget_respond_live", "calendar_book_slot", "survey_send_nps",
    # Phase H — Task 28 launch pack
    "producthunt_schedule", "betalist_submit", "indiehackers_post",
    "hn_show_submit", "directory_submit_g2", "directory_submit_capterra",
    "directory_submit_alternative_to", "haro_respond",
    "prnewswire_submit", "podcast_pitch",
    # Phase H — Task 26 finance + UK-gov pack
    "companies_house_search", "companies_house_get_company",
    "companies_house_get_officers", "companies_house_get_filings",
    "companies_house_monitor_filings", "hmrc_check_vat_number",
    "freeagent_create_invoice", "freeagent_record_expense",
    "xero_reconcile_transaction",
    "compute_runway_months", "ir35_determine_status",
    # Phase H — Task 35 dev/infra pack
    "github_create_repo", "github_create_release", "github_star_repo",
    "github_search_issues",
    "npm_publish", "pypi_publish", "docker_build_and_push",
    "dns_set_record", "dns_verify_propagation", "ssl_check_expiry",
    "domain_check_availability", "domain_register",
    "cloudflare_purge_cache", "cloudflare_deploy_pages_site",
    "infra_db_health", "infra_redis_health", "infra_status_report",
    # Swarm Phase Z2
    "swarm_status",
    # Phase H — Task 37 compliance pack
    "sanctions_check", "kyc_verify_address", "fraud_score_transaction",
    "captcha_solve", "gdpr_data_export", "gdpr_delete_user",
    "tos_generate", "privacy_policy_generate",
    "dmca_takedown_request", "esign_send", "dispute_respond",
}


def test_all_expected_builtins_load(builtin_registry):
    loaded = set(builtin_registry.list_names())
    missing = EXPECTED_BUILTINS - loaded
    assert not missing, f"missing built-in skills: {missing}"


def test_http_fetch_returns_dict(builtin_registry):
    ctx = make_noop_ctx(caller_id="test", budget_usd=0.0)
    record = asyncio.run(builtin_registry.call(
        "http_fetch", {"url": "https://example.com"}, ctx,
    ))
    assert record.ok is True
    assert "text" in record.result
    assert "status" in record.result


def test_time_now_returns_iso(builtin_registry):
    ctx = make_noop_ctx(caller_id="t", budget_usd=0)
    record = asyncio.run(builtin_registry.call("time_now", {}, ctx))
    assert record.ok is True
    assert "iso" in record.result


def test_worker_spawn_publishes_to_bus(builtin_registry):
    ctx = make_noop_ctx(caller_id="ceo", budget_usd=0)
    ctx.bus.publish = AsyncMock(return_value="msg-id")  # type: ignore[method-assign]
    record = asyncio.run(builtin_registry.call(
        "worker_spawn",
        {"role": "researcher", "soul_text": "you research things", "supervisor": "ceo"},
        ctx,
    ))
    assert record.ok is True
    ctx.bus.publish.assert_called_once()
    args = ctx.bus.publish.call_args.args
    assert args[0] == "agent.spawn_request"


def test_worker_fire_publishes_to_bus(builtin_registry):
    ctx = make_noop_ctx(caller_id="ceo", budget_usd=0)
    ctx.bus.publish = AsyncMock(return_value="msg-id")  # type: ignore[method-assign]
    record = asyncio.run(builtin_registry.call(
        "worker_fire", {"agent_id": "researcher-001", "reason": "redundant"}, ctx,
    ))
    assert record.ok is True
    topic, payload = ctx.bus.publish.call_args.args
    assert topic == "agent.fire_request"
    assert payload["agent_id"] == "researcher-001"


def test_skill_request_publishes(builtin_registry):
    from unittest.mock import AsyncMock
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0)
    ctx.bus.publish = AsyncMock(return_value="id")  # type: ignore[method-assign]
    record = asyncio.run(builtin_registry.call("skill_request", {
        "name": "weather", "description": "fetch weather",
        "params_schema": {"city": "str"}, "returns_schema": {"temp_c": "float"},
        "example_call": {"city": "London"},
    }, ctx))
    assert record.ok is True
    topic, payload = ctx.bus.publish.call_args.args
    assert topic == "skill.request"
    assert payload["name"] == "weather"
    assert payload["requested_by"] == "cto"
