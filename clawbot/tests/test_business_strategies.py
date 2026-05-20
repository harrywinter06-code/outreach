"""Z5 — business-strategy registry + genome integration tests."""
import pytest


def test_registry_has_four_strategies():
    from clawbot.business_strategies import list_strategies, strategy_keys
    keys = set(strategy_keys())
    assert keys == {
        "paid_personalised_report",
        "affiliate_aggregator",
        "freemium_lead_funnel",
        "seo_content_site",
    }
    assert len(list_strategies()) == 4


def test_every_strategy_has_mandate_and_one_line():
    from clawbot.business_strategies import list_strategies
    for s in list_strategies():
        assert s.mandate_template.strip(), f"{s.key} missing mandate"
        assert s.one_line.strip(), f"{s.key} missing one_line"
        assert isinstance(s.distribution_required, bool)
        assert isinstance(s.skill_hints, list)


def test_distribution_required_is_split_across_strategies():
    """Whole point of strategy diversification: at least one strategy
    should NOT require operator distribution, so substrate-only path
    has at least one viable model."""
    from clawbot.business_strategies import list_strategies
    needs = [s for s in list_strategies() if s.distribution_required]
    organic = [s for s in list_strategies() if not s.distribution_required]
    assert needs, "at least one strategy should need distribution (paid_personalised_report)"
    assert organic, "at least one strategy must be organic-discoverable (SEO/affiliate/freemium)"


def test_get_strategy_returns_none_for_unknown():
    from clawbot.business_strategies import get_strategy
    assert get_strategy("not_a_real_strategy") is None


def test_default_strategy_matches_a_registered_one():
    from clawbot.business_strategies import default_strategy, get_strategy
    d = default_strategy()
    assert get_strategy(d) is not None, f"default strategy {d!r} not in registry"


def test_genome_accepts_strategy_field():
    from clawbot.business_store import validate_genome
    g = validate_genome({
        "niche_question": "what?", "price_gbp": 3.0,
        "strategy": "affiliate_aggregator",
    })
    assert g["strategy"] == "affiliate_aggregator"


def test_genome_strategy_defaults_to_paid_personalised_report():
    """Backward compat: pre-Z5 genomes (no strategy field) get the
    paid_personalised_report default. Existing businesses keep working."""
    from clawbot.business_store import validate_genome
    g = validate_genome({"niche_question": "what?", "price_gbp": 3.0})
    assert g["strategy"] == "paid_personalised_report"


def test_seed_pool_has_strategy_diversity():
    """We seed multiple strategies so the swarm has alternatives to try
    when one model stalls."""
    from clawbot.swarm_seeds import get_seed_genomes
    seeds = get_seed_genomes()
    strategies = {s["strategy"] for s in seeds}
    assert len(strategies) >= 3, f"only {len(strategies)} strategies in seed pool: {strategies}"
    assert "paid_personalised_report" in strategies
    assert any(s in strategies for s in ("seo_content_site", "affiliate_aggregator", "freemium_lead_funnel"))


def test_every_seed_genome_validates():
    """All seeds must validate against the Pydantic schema, including the
    new strategy field. Otherwise bootstrap dies on first spawn."""
    from clawbot.business_store import validate_genome
    from clawbot.swarm_seeds import get_seed_genomes
    for seed in get_seed_genomes():
        validated = validate_genome(seed)
        assert validated["strategy"], f"seed {seed.get('niche_question', '?')} produced empty strategy"


def test_cycle_prompt_renders_strategy_specific_mandate():
    """Different strategies → different mandate text. Renderer must pick
    the right one based on genome.strategy."""
    from clawbot.business_prompt_renderer import render_business_prompt
    from clawbot.business_store import Business
    from datetime import datetime, timezone
    UTC = timezone.utc

    def _make(strategy: str):
        return Business(
            business_id="b", name="bt", niche="x",
            genome={"niche_question": "x?", "price_gbp": 3.0,
                    "channels": ["dev_to"], "strategy": strategy},
            status="active", parent_id=None, template_id=None,
            budget_remaining_gbp=1.0, revenue_total_gbp=0.0, fitness_score=0.0,
            spawned_at=datetime.now(UTC), last_cycle_at=None,
            killed_at=None, kill_reason=None, metadata={},
        )

    paid = render_business_prompt(
        business=_make("paid_personalised_report"),
        recent_actions=[], recent_skill_results=[], skill_catalog=[],
    )
    affiliate = render_business_prompt(
        business=_make("affiliate_aggregator"),
        recent_actions=[], recent_skill_results=[], skill_catalog=[],
    )
    seo = render_business_prompt(
        business=_make("seo_content_site"),
        recent_actions=[], recent_skill_results=[], skill_catalog=[],
    )
    # Each should mention its own strategy key in the MANDATE header
    assert "strategy: paid_personalised_report" in paid
    assert "strategy: affiliate_aggregator" in affiliate
    assert "strategy: seo_content_site" in seo
    # And each strategy's distinctive content
    assert "comparison" in affiliate.lower() or "directory" in affiliate.lower() or "affiliate" in affiliate.lower()
    assert "long-tail" in seo.lower() or "article" in seo.lower() or "seo" in seo.lower()


def test_cycle_prompt_falls_back_gracefully_on_unknown_strategy():
    """Forward-compat: an LLM-mutated genome might set strategy=<new thing>
    not yet in the registry. Renderer shouldn't crash — falls back to
    generic mandate."""
    from clawbot.business_prompt_renderer import render_business_prompt
    from clawbot.business_store import Business
    from datetime import datetime, timezone
    UTC = timezone.utc
    biz = Business(
        business_id="b", name="bt", niche="x",
        genome={"niche_question": "x?", "price_gbp": 3.0,
                "channels": ["dev_to"], "strategy": "mystery_new_strategy"},
        status="active", parent_id=None, template_id=None,
        budget_remaining_gbp=1.0, revenue_total_gbp=0.0, fitness_score=0.0,
        spawned_at=datetime.now(UTC), last_cycle_at=None,
        killed_at=None, kill_reason=None, metadata={},
    )
    out = render_business_prompt(
        business=biz, recent_actions=[], recent_skill_results=[], skill_catalog=[],
    )
    # Doesn't crash; falls back to default mandate
    assert "mystery_new_strategy" in out
    assert "MANDATE" in out
