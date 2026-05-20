"""
Z5 — Business-strategy registry.

Each genome currently encodes a niche + price + channels but ALL existing
businesses follow the same revenue model: "sell a personalised report
via lander + Stripe + LLM fulfilment." When that model fails (distribution
cold-start, no audience, content commodification), the cull+respawn loop
just reproduces the same model with a different niche. That's not
adaptation — that's repetition.

This module defines a strategy registry. A strategy = an entire
revenue-model template:
- mandate_template: what the cycle runner tells the LLM to focus on
- success_metric_field: what column on `businesses` measures progress
  (revenue_total_gbp for direct, or a metadata key for indirect models)
- skill_hints: which skills are most useful for this strategy
- distribution_required: True = needs human-driven seeding to start;
  False = can grow via organic discovery (SEO, search)

The genome gets a `strategy` field. The cycle runner reads it and uses
the strategy-specific mandate. The spawn loop biases toward strategies
that are underrepresented in the active swarm when the dominant strategy
is stalling.

Adding a new strategy is one entry here + one matching seed in
swarm_seeds.py. No new code required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


StrategyKey = Literal[
    "paid_personalised_report",
    "affiliate_aggregator",
    "freemium_lead_funnel",
    "seo_content_site",
]


@dataclass(frozen=True)
class BusinessStrategy:
    key: str
    display_name: str
    one_line: str  # shown in prompt for context
    mandate_template: str  # appears in cycle runner's MANDATE section
    distribution_required: bool  # True = needs human seeding; False = organic-discoverable
    skill_hints: list[str] = field(default_factory=list)
    success_metric: str = "revenue_total_gbp"  # what column on `businesses` measures progress


_REGISTRY: dict[str, BusinessStrategy] = {
    "paid_personalised_report": BusinessStrategy(
        key="paid_personalised_report",
        display_name="Paid Personalised Report",
        one_line="Sell an LLM-generated personalised report for £3-5 per buy.",
        mandate_template=(
            "Your funnel is the lander → email-capture → Stripe payment → emailed report.\n"
            "Goal: drive traffic to the lander. Every artifact you publish MUST include\n"
            "the lander URL with copy explaining what the customer gets (free taster +\n"
            "paid report). Articles without the lander link are wasted cycles.\n"
            "Honest warning: this strategy needs an audience. A brand-new social account\n"
            "with 0 followers will reach near-zero people. Consider if a different\n"
            "strategy would suit your niche better — you can suggest a pivot via\n"
            "an `escalate` field if you have strong evidence."
        ),
        distribution_required=True,
        skill_hints=["bluesky_post", "mastodon_post", "dev_to_publish", "medium_publish",
                     "write_long_form_article", "write_tweet_thread", "stripe_create_payment_link"],
        success_metric="revenue_total_gbp",
    ),
    "affiliate_aggregator": BusinessStrategy(
        key="affiliate_aggregator",
        display_name="Affiliate Aggregator",
        one_line="Build a comparison/directory of UK service providers in your niche. Monetize via affiliate links — earn a fee when readers click through and convert with the provider.",
        mandate_template=(
            "Your business is a comparison page (lander) listing providers in your niche\n"
            "(e.g. UK contractor insurance providers, IR35 accountants, mortgage brokers).\n"
            "Each provider entry has: name, key features, price, affiliate-tracked link.\n"
            "Goal each cycle: ADD or IMPROVE one provider entry on the lander, OR write\n"
            "a comparison article that links back to the lander. You earn when readers\n"
            "click through to providers via your tracked links.\n"
            "No payment processing on YOUR side — providers handle that. Your only\n"
            "deliverable is the curation + content. SEO-driven discovery via specific\n"
            "long-tail queries ('best IR35 accountant uk', 'cheapest contractor insurance')\n"
            "is the natural growth path. Distribution does not require an audience."
        ),
        distribution_required=False,
        skill_hints=["write_long_form_article", "write_case_study", "fs_write", "fs_read",
                     "vector_search", "vector_write", "http_fetch", "experiment_create",
                     "competitor_pricing_scrape", "keyword_research"],
        success_metric="revenue_total_gbp",
    ),
    "freemium_lead_funnel": BusinessStrategy(
        key="freemium_lead_funnel",
        display_name="Freemium Lead Funnel",
        one_line="Offer a genuinely useful free tool. Capture email. Don't charge yet — build a list that can be monetized later (sponsored content, partner offers, paid upgrade).",
        mandate_template=(
            "Your business gives away a free useful tool (the lander's free-tier\n"
            "assessment is real, polished, and self-contained). You don't charge\n"
            "money — your success metric is EMAIL LIST SIZE (captured leads).\n"
            "Goal each cycle: improve the free tool's quality OR write content that\n"
            "drives traffic to it. Articles should answer one specific question and\n"
            "link to the free tool as the next-step.\n"
            "Long-term play: once the list crosses ~100 emails, monetize via\n"
            "sponsored content, partner deals, or a paid upgrade. For now, just\n"
            "capture. No payment link needed."
        ),
        distribution_required=False,
        skill_hints=["write_long_form_article", "write_case_study", "write_landing_page_copy",
                     "fs_write", "vector_write", "bluesky_post", "mastodon_post",
                     "experiment_create"],
        success_metric="leads_total",  # use lead count as fitness signal
    ),
    "seo_content_site": BusinessStrategy(
        key="seo_content_site",
        display_name="SEO Content Site",
        one_line="Write 30-50 specific high-quality articles on a niche topic. Monetize via ads (AdSense) or affiliate links embedded in content. Pure long-tail SEO play.",
        mandate_template=(
            "Your business is a content site. Each cycle: write ONE specific, high-quality\n"
            "article (1000-2000 words) targeting one long-tail SEO keyword in your niche.\n"
            "Examples for IR35 niche: 'what counts as substitution for IR35 in 2026',\n"
            "'IR35 implications of being on the client's tech lead's holiday rota',\n"
            "'mutuality of obligation HMRC case studies 2025'.\n"
            "Each article: clear H1 question (matches search intent), structured body,\n"
            "internal links to other articles you've written, NO calls-to-action — Google\n"
            "penalises over-promotion on new domains.\n"
            "Monetization happens later via embedded contextual affiliate links once\n"
            "you have 20+ articles indexed and ranking. For now: write, publish,\n"
            "build the body of work. Patience required — SEO takes 3-6 months to bite."
        ),
        distribution_required=False,
        skill_hints=["write_long_form_article", "write_case_study", "fs_write", "fs_read",
                     "keyword_research", "serp_check", "schema_org_generate",
                     "sitemap_generate", "vector_search"],
        success_metric="article_count",  # use published-article count as fitness signal
    ),
}


def get_strategy(key: str) -> BusinessStrategy | None:
    return _REGISTRY.get(key)


def list_strategies() -> list[BusinessStrategy]:
    return list(_REGISTRY.values())


def strategy_keys() -> list[str]:
    return list(_REGISTRY.keys())


def default_strategy() -> str:
    """Default strategy when a genome doesn't declare one — backward compat
    for businesses spawned before Z5."""
    return "paid_personalised_report"
