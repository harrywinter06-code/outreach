"""Z2.5b — business prompt renderer + skill-catalog filtering tests."""
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

UTC = timezone.utc


def _make_business(*, business_id="b1", name="bt", niche="x", revenue=0.0,
                   spawned_days_ago=0.5, metadata=None,
                   genome=None):
    from clawbot.business_store import Business
    return Business(
        business_id=business_id, name=name, niche=niche,
        genome=genome or {
            "niche_question": "what is x?", "price_gbp": 3.0,
            "channels": ["dev_to", "medium"],
            "copy_voice": "plain", "fulfilment_template": "v1",
            "target_audience": "uk_adult",
        },
        status="active", parent_id=None, template_id=None,
        budget_remaining_gbp=1.0, revenue_total_gbp=float(revenue),
        fitness_score=0.0,
        spawned_at=datetime.now(UTC) - timedelta(days=spawned_days_ago),
        last_cycle_at=None, killed_at=None, kill_reason=None,
        metadata=metadata or {},
    )


@dataclass
class _StubSkill:
    name: str
    description: str = ""
    params: dict | None = None
    roles: list | None = None

    def __post_init__(self):
        if self.params is None:
            object.__setattr__(self, "params", {})
        if self.roles is None:
            object.__setattr__(self, "roles", [])


def test_prompt_contains_identity_state_recent_skills_mandate():
    from clawbot.business_prompt_renderer import render_business_prompt
    biz = _make_business()
    out = render_business_prompt(
        business=biz, recent_actions=[], recent_skill_results=[],
        skill_catalog=[_StubSkill(name="dev_to_publish"), _StubSkill(name="llm_complete")],
    )
    assert "=== IDENTITY ===" in out
    assert "=== STATE ===" in out
    assert "=== RECENT ATTEMPTS ===" in out
    assert "=== AVAILABLE SKILLS" in out
    assert "=== MANDATE ===" in out


def test_prompt_includes_genome_fields():
    from clawbot.business_prompt_renderer import render_business_prompt
    biz = _make_business(genome={
        "niche_question": "what council tax band am i?",
        "price_gbp": 3.5,
        "channels": ["dev_to", "bluesky"],
        "copy_voice": "plain_uk",
        "fulfilment_template": "council_tax_v2",
        "target_audience": "uk_homeowner",
    })
    out = render_business_prompt(
        business=biz, recent_actions=[], recent_skill_results=[],
        skill_catalog=[],
    )
    assert "what council tax band am i?" in out
    assert "£3.5" in out
    assert "dev_to" in out and "bluesky" in out
    assert "council_tax_v2" in out


def test_prompt_includes_business_id_in_example_response():
    """The example response in the mandate MUST contain the business_id so
    the LLM sees what attribution looks like."""
    from clawbot.business_prompt_renderer import render_business_prompt
    biz = _make_business(business_id="biz_xyz_12345")
    out = render_business_prompt(
        business=biz, recent_actions=[], recent_skill_results=[],
        skill_catalog=[],
    )
    assert "biz_xyz_12345" in out
    assert '"business_id"' in out


def test_prompt_includes_stall_count_in_state():
    from clawbot.business_prompt_renderer import render_business_prompt
    biz = _make_business(metadata={"artifact_stall_count": 2, "last_artifact_url": "https://dev.to/x"})
    out = render_business_prompt(
        business=biz, recent_actions=[], recent_skill_results=[],
        skill_catalog=[],
    )
    assert "Cycles without artifact: 2" in out
    assert "https://dev.to/x" in out


def test_filter_skills_keeps_channel_skills_and_core_primitives():
    """Channel skills + core-prefix skills both included. Test catalog has
    enough core-prefix skills (≥10 matches) so the fallback path doesn't
    fire and wrong-channel skills stay excluded."""
    from clawbot.business_prompt_renderer import filter_skills_for_business
    genome = {"channels": ["dev_to", "bluesky"]}
    catalog = [
        _StubSkill(name="dev_to_publish"),       # channel match
        _StubSkill(name="bluesky_post"),         # channel match
        _StubSkill(name="x_post"),               # wrong channel
        _StubSkill(name="medium_publish"),       # wrong channel
        _StubSkill(name="stripe_create_product"),    # not core, not channel
        # Core-prefix skills — need ≥10 of them so total ≥10 to avoid fallback
        _StubSkill(name="llm_complete"),
        _StubSkill(name="http_fetch"),
        _StubSkill(name="http_post"),
        _StubSkill(name="write_landing_page_copy"),
        _StubSkill(name="write_long_form_article"),
        _StubSkill(name="sql_query"),
        _StubSkill(name="fs_write"),
        _StubSkill(name="fs_read"),
        _StubSkill(name="vector_search"),
        _StubSkill(name="vector_write"),
        _StubSkill(name="experiment_create"),
        _StubSkill(name="experiment_record_observation"),
    ]
    out = filter_skills_for_business(catalog, genome)
    names = [e.name for e in out]
    # MUST contain channel + core
    for required in ("dev_to_publish", "bluesky_post", "llm_complete",
                     "http_fetch", "write_landing_page_copy", "sql_query"):
        assert required in names, f"{required} missing from filtered list: {names}"
    # MUST exclude wrong-channel + non-core skills (fallback didn't fire — ≥10 matches)
    assert "x_post" not in names
    assert "medium_publish" not in names
    assert "stripe_create_product" not in names


def test_filter_skills_falls_back_to_broader_catalog_when_too_few_match():
    """If filtering would leave <10 skills, expose more breadth so the LLM
    isn't starved of options."""
    from clawbot.business_prompt_renderer import filter_skills_for_business
    genome = {"channels": ["dev_to"]}
    catalog = [
        _StubSkill(name="dev_to_publish"),
        _StubSkill(name="some_obscure_skill"),
        _StubSkill(name="another_one"),
    ]
    out = filter_skills_for_business(catalog, genome)
    names = [e.name for e in out]
    # Only 1 channel + 0 core matches; fallback adds the rest up to 30
    assert len(out) == 3
    assert "some_obscure_skill" in names


def test_filter_skills_returns_full_entries_not_just_names():
    """Z2.5 fix: renderer needs full entry objects so it can read param
    signatures. Returning just names left the LLM guessing params."""
    from clawbot.business_prompt_renderer import filter_skills_for_business
    catalog = [
        _StubSkill(name="dev_to_publish", description="post to dev.to",
                   params={"title": "str", "body_markdown": "str"}),
    ]
    out = filter_skills_for_business(catalog, {"channels": ["dev_to"]})
    assert out  # must be non-empty
    e = out[0]
    # Entry, not bare string
    assert hasattr(e, "name")
    assert e.params == {"title": "str", "body_markdown": "str"}


def test_prompt_renders_skill_signatures_with_param_types():
    """The whole point of Z2.5 polish: LLM sees `name(p1: type, p2: type)`
    so it can construct valid action JSON instead of guessing."""
    from clawbot.business_prompt_renderer import render_business_prompt
    biz = _make_business()
    catalog = [
        _StubSkill(
            name="dev_to_publish",
            description="post an article to dev.to",
            params={"title": "str", "body_markdown": "str"},
        ),
    ]
    out = render_business_prompt(
        business=biz, recent_actions=[], recent_skill_results=[],
        skill_catalog=catalog,
    )
    assert "dev_to_publish(title: str, body_markdown: str)" in out
    assert "post an article to dev.to" in out
    assert "include EVERY listed param" in out  # mandate hardening


def test_prompt_renders_recent_failures_with_errors():
    """LLM must SEE its prior mistake to correct it. Recent attempts block
    shows skill_name + OK/FAIL + the error string."""
    from clawbot.business_prompt_renderer import render_business_prompt
    biz = _make_business()
    recent = [
        {"skill_name": "mastodon_post", "ok": False,
         "error": "missing required param: status"},
        {"skill_name": "dev_to_publish", "ok": True, "error": ""},
    ]
    out = render_business_prompt(
        business=biz, recent_actions=recent, recent_skill_results=[],
        skill_catalog=[],
    )
    assert "FAIL" in out and "mastodon_post" in out
    assert "missing required param: status" in out
    assert "OK" in out and "dev_to_publish" in out
