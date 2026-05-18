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
    # Z3: IR35 is the depth-first focus. Lowest factual-error surface (the
    # HMRC CEST framework is well-defined), clearest expert competition
    # (£150-300 accountant fee), highest-value audience (UK contractors).
    # The fulfilment template `ir35_quickcheck_v1` is the only one with a
    # real prompt body wired up; council_tax/mortgage stay in the pool for
    # later when their templates exist + IR35 has proven conversion.
    {
        "niche_question": "am i inside or outside ir35 for my current contract?",
        "price_gbp": 5.0,
        "channels": ["dev_to", "medium", "bluesky", "mastodon"],
        "copy_voice": "plain_uk_explainer",
        "fulfilment_template": "ir35_quickcheck_v1",
        "target_audience": "uk_contractor_freelancer",
        "extra": {
            "free_tier_promise": "structured 7-question check with verdict",
            "paid_tier_promise": "hmrc-aligned full assessment + tailored evidence checklist + next-step recommendation",
            "data_sources": ["hmrc_cest_guidance"],
        },
    },
    {
        "niche_question": "what council tax band is my property in and is it correct?",
        "price_gbp": 3.0,
        "channels": ["dev_to", "medium", "bluesky", "mastodon"],
        "copy_voice": "plain_uk_explainer",
        "fulfilment_template": "council_tax_v1",
        "target_audience": "uk_homeowner_or_tenant",
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
