"""
Starter genomes — hand-curated bootstrap pool for the swarm's first spawns.

These are NOT templates (templates require graduation via £50+ revenue).
They're seed genomes the SwarmController samples from when:
- The template pool is empty (cold start), OR
- A diversification cycle wants a wholly fresh bet outside the template
  distribution

Niches were chosen for: (a) clear answer derivable from public data + LLM
reasoning, (b) measurable UK search demand, (c) recurring anxiety/admin
question, (d) £3-5 price point feels right for personal use.

Edit this file to evolve the seed pool. Genomes that prove their worth
in production graduate to the template pool automatically.
"""
from __future__ import annotations


SEED_GENOMES: list[dict] = [
    # Z3: IR35 paid-report business. Highest-value audience but worst
    # cold-start: distribution_required=True, brand-new account = 0 reach.
    {
        "niche_question": "am i inside or outside ir35 for my current contract?",
        "price_gbp": 5.0,
        "channels": ["dev_to", "medium", "bluesky", "mastodon"],
        "copy_voice": "plain_uk_explainer",
        "fulfilment_template": "ir35_quickcheck_v1",
        "target_audience": "uk_contractor_freelancer",
        "strategy": "paid_personalised_report",
        "extra": {
            "free_tier_promise": "structured 7-question check with verdict",
            "paid_tier_promise": "hmrc-aligned full assessment + tailored evidence checklist + next-step recommendation",
            "data_sources": ["hmrc_cest_guidance"],
        },
    },
    # Z5: SEO-content variant of IR35. No distribution needed — Google
    # organic search delivers traffic over weeks-months as articles index.
    # Lowest cold-start barrier of the four strategies.
    {
        "niche_question": "ir35 status indicators and case law explained for uk contractors",
        "price_gbp": 5.0,  # placeholder; monetization is later via affiliate
        "channels": ["dev_to", "medium"],  # publish to platforms with built-in SEO
        "copy_voice": "plain_uk_explainer",
        "fulfilment_template": "ir35_quickcheck_v1",
        "target_audience": "uk_contractor_freelancer",
        "strategy": "seo_content_site",
        "extra": {
            "keyword_targets": ["ir35 substitution clause example",
                                "mutuality of obligation hmrc case",
                                "ir35 control test what counts",
                                "outside ir35 evidence checklist"],
        },
    },
    # Z5: Affiliate-aggregator for UK contractor services. No payment
    # processing required on our side. Long-tail SEO discoverable.
    {
        "niche_question": "best uk contractor insurance providers compared",
        "price_gbp": 3.0,  # placeholder; affiliate earns per click-through
        "channels": ["dev_to", "medium"],
        "copy_voice": "plain_uk_explainer",
        "fulfilment_template": "ir35_quickcheck_v1",  # unused for affiliate model
        "target_audience": "uk_contractor_freelancer",
        "strategy": "affiliate_aggregator",
        "extra": {
            "comparison_niche": "uk_contractor_insurance",
            "providers_to_evaluate": ["Kingsbridge", "Markel", "Hiscox", "Caunce O'Hara", "Qdos"],
        },
    },
    # Z5: Freemium lead funnel for IR35. No payment, just email capture.
    # Lower friction; monetization via partner referrals later.
    {
        "niche_question": "free ir35 status assessment tool for uk contractors",
        "price_gbp": 3.0,  # placeholder; not actually charged
        "channels": ["dev_to", "medium", "bluesky"],
        "copy_voice": "plain_uk_explainer",
        "fulfilment_template": "ir35_quickcheck_v1",
        "target_audience": "uk_contractor_freelancer",
        "strategy": "freemium_lead_funnel",
        "extra": {
            "monetization_intent": "build_list_then_partner_referrals",
        },
    },
    {
        "niche_question": "what council tax band is my property in and is it correct?",
        "price_gbp": 3.0,
        "channels": ["dev_to", "medium", "bluesky", "mastodon"],
        "copy_voice": "plain_uk_explainer",
        "fulfilment_template": "council_tax_v1",
        "target_audience": "uk_homeowner_or_tenant",
        "strategy": "paid_personalised_report",
        "extra": {
            "free_tier_promise": "instant band lookup + average for street",
            "paid_tier_promise": "personalised challenge letter draft + valuation comparison + 5-year savings estimate",
            "data_sources": ["voa_band_lookup", "land_registry_sold_prices"],
        },
    },
    {
        "niche_question": "how much can i borrow for a uk mortgage based on my income and outgoings?",
        "price_gbp": 4.0,
        "channels": ["dev_to", "medium", "mastodon"],
        "copy_voice": "plain_uk_explainer",
        "fulfilment_template": "mortgage_affordability_v1",
        "target_audience": "uk_first_time_buyer_or_remortgagor",
        "strategy": "paid_personalised_report",
        "extra": {
            "free_tier_promise": "rough affordability range (3.5-4.5x income)",
            "paid_tier_promise": "lender-by-lender breakdown with current 2026 multiples + stress test + max-likely vs comfortable",
            "data_sources": ["lender_multiples_2026", "boe_base_rate"],
        },
    },
]


def get_seed_genomes() -> list[dict]:
    """Return a copy of the seed pool — never mutate the module-level list."""
    return [dict(g) for g in SEED_GENOMES]
