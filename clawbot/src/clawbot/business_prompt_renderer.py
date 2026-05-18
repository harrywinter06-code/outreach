"""Swarm Z2.5 Task B — render the per-business cycle prompt.

Pure function. Takes a Business + recent activity + skill catalog, returns
the prompt string the LLM sees during one business cycle.

The prompt is intentionally terse and action-focused:
- 5 sections, each clearly labeled
- The "mandate" section demands ONE concrete artifact per cycle (a
  measurable side-effect: URL, captured email, payment-link). Cycles
  that don't produce one increment the artifact-stall counter, which
  the cull loop reads.
- Skill catalog is filtered to the channels in the business's genome
  plus core primitives (write/llm/http/sql) — keeps the prompt under
  the free-tier token budget while preserving relevant capability.

This is the input side of the business cycle. The output is parsed by
business_cycle_runner.py which dispatches the action through the
existing directive_router with business_id attribution.
"""
from __future__ import annotations

import json
from typing import Any

from clawbot.business_store import Business


# Skill name prefixes that are universally useful for any business.
_CORE_SKILL_PREFIXES = (
    "llm_", "http_", "sql_", "fs_", "time_", "vector_", "write_",
    "skill_", "experiment_", "secret_",
)

# Maps a channel from the genome to skill prefixes/exact-names relevant
# to that channel. Used to filter the catalog to genome-relevant skills.
_CHANNEL_SKILL_HINTS: dict[str, tuple[str, ...]] = {
    "dev_to": ("dev_to_publish",),
    "medium": ("medium_publish",),
    "substack": ("substack_publish", "newsletter_send"),
    "hashnode": ("hashnode_publish",),
    "bluesky": ("bluesky_post",),
    "mastodon": ("mastodon_post",),
    "rss": ("rss_publish",),
    "youtube": ("youtube_upload",),
    "linkedin": ("linkedin_post",),
    "x": ("x_post",),
    "reddit": ("reddit_submit", "reddit_comment"),
}

# Action types that count as producing a concrete artifact, used by the
# runner to detect "did this cycle do something measurable?". Exposed
# here so the renderer can name them in the prompt.
ARTIFACT_ACTIONS = (
    "substack_publish", "medium_publish", "dev_to_publish", "hashnode_publish",
    "bluesky_post", "mastodon_post", "rss_publish", "youtube_upload",
    "linkedin_post", "x_post", "reddit_submit",
    "newsletter_send",
    "stripe_create_payment_link", "stripe_create_product",
    "email_send_cold", "email_send_followup_sequence",
    "write_landing_page_copy", "write_long_form_article",
)


def _entry_name(entry: Any) -> str | None:
    if entry is None:
        return None
    n = getattr(entry, "name", None)
    if n:
        return n
    if isinstance(entry, dict):
        return entry.get("name")
    return None


def filter_skills_for_business(
    skill_catalog: list[Any], genome: dict[str, Any],
) -> list[Any]:
    """Return SkillCatalogEntry objects (NOT just names) relevant to this
    business's channels + core primitives. Returning full entries lets the
    prompt render param signatures, not just bare skill names.

    Falls back to broader catalog if filtering removes too much."""
    if not skill_catalog:
        return []
    channels = [str(c).lower() for c in genome.get("channels", [])]
    channel_skills: set[str] = set()
    for ch in channels:
        for skill_name in _CHANNEL_SKILL_HINTS.get(ch, ()):
            channel_skills.add(skill_name)
    out: list[Any] = []
    seen: set[str] = set()
    for entry in skill_catalog:
        name = _entry_name(entry)
        if not name:
            continue
        if name in channel_skills:
            out.append(entry)
            seen.add(name)
            continue
        if any(name.startswith(p) for p in _CORE_SKILL_PREFIXES):
            out.append(entry)
            seen.add(name)
    # Fallback: if filtering would leave < 10 skills, expose more breadth
    if len(out) < 10:
        for entry in skill_catalog:
            name = _entry_name(entry)
            if name and name not in seen:
                out.append(entry)
                seen.add(name)
                if len(out) >= 30:
                    break
    return out


def _format_skill_signature(entry: Any) -> str:
    """Render one skill as `name(p1: type, p2: type) — description`.

    Description is truncated to keep the prompt compact. The signature is
    what the LLM needs to construct valid action JSON."""
    name = _entry_name(entry) or "?"
    params: dict[str, str] = (
        getattr(entry, "params", None)
        or (entry.get("params") if isinstance(entry, dict) else None)
        or {}
    )
    description: str = (
        getattr(entry, "description", None)
        or (entry.get("description") if isinstance(entry, dict) else None)
        or ""
    )
    sig_parts = [f"{p}: {t}" for p, t in params.items()]
    sig = f"{name}({', '.join(sig_parts)})"
    desc = description.strip().split("\n")[0][:120]
    return f"- {sig} — {desc}" if desc else f"- {sig}"


def render_business_prompt(
    *,
    business: Business,
    recent_actions: list[dict[str, Any]],
    recent_skill_results: list[dict[str, Any]],
    skill_catalog: list[Any],
) -> str:
    """Build the LLM prompt for one business cycle.

    Sections:
      1. IDENTITY — who you are (genome → narrative)
      2. STATE — measured fitness signals (revenue, age, last_artifact)
      3. RECENT — last few actions + results, truncated
      4. SKILLS — relevant catalog (filtered by channel + core primitives)
      5. MANDATE — produce ONE concrete artifact this cycle, respond as JSON
    """
    g = business.genome or {}
    sections: list[str] = []

    # 1. IDENTITY
    channels = ", ".join(g.get("channels", [])) or "(no channels set)"
    sections.append(
        "=== IDENTITY ===\n"
        f"You are running business `{business.name}` (id: {business.business_id}).\n"
        f"Niche: {g.get('niche_question', business.niche)}\n"
        f"Price: £{g.get('price_gbp', '?')}\n"
        f"Channels: {channels}\n"
        f"Voice: {g.get('copy_voice', 'plain')}\n"
        f"Fulfilment template: {g.get('fulfilment_template', 'default')}\n"
        f"Target audience: {g.get('target_audience', 'uk_adult')}"
    )

    # 2. STATE
    md = business.metadata or {}
    last_url = md.get("last_artifact_url", "(none)")
    payment_link = md.get("payment_link_url", "(not created)")
    stall = int(md.get("artifact_stall_count", 0))
    sections.append(
        "=== STATE ===\n"
        f"Revenue: £{float(business.revenue_total_gbp):.2f}\n"
        f"Budget remaining: £{float(business.budget_remaining_gbp):.2f}\n"
        f"Fitness score: {float(business.fitness_score):.3f}\n"
        f"Last artifact URL: {last_url}\n"
        f"Stripe payment link: {payment_link}\n"
        f"Cycles without artifact: {stall}"
    )

    # 3. RECENT — pulled from skill_calls. Each entry is a dict with keys
    # `skill_name`, `ok`, `error` (nullable). Shows the LLM exactly what it
    # tried last and why it failed — so the next cycle can correct.
    recent_lines: list[str] = []
    for act in (recent_actions or [])[-5:]:
        skill = act.get("skill_name") or act.get("action") or "?"
        ok = "OK" if act.get("ok", True) else "FAIL"
        err = (act.get("error") or "").strip()
        if err and not act.get("ok", True):
            recent_lines.append(f"  - {ok}  {skill}  ← {err[:120]}")
        else:
            recent_lines.append(f"  - {ok}  {skill}")
    sections.append(
        "=== RECENT ATTEMPTS ===\n" +
        ("\n".join(recent_lines) if recent_lines else "(none yet — this is your first cycle)")
    )

    # 4. SKILLS — render full signatures so the LLM constructs valid actions.
    relevant_entries = filter_skills_for_business(skill_catalog, g)
    sig_lines = [_format_skill_signature(e) for e in relevant_entries]
    sections.append(
        "=== AVAILABLE SKILLS (use ONLY these; include EVERY listed param) ===\n"
        + ("\n".join(sig_lines) if sig_lines else "(none available)")
    )

    # 5. MANDATE
    artifact_list = ", ".join(ARTIFACT_ACTIONS[:8]) + ", ..."
    response_example = json.dumps({
        "action": "dev_to_publish",
        "title": "Council Tax Bands Explained — Free 2-Minute Check",
        "body_markdown": "...",
        "business_id": business.business_id,
    })
    sections.append(
        "=== MANDATE ===\n"
        "Produce ONE concrete artifact this cycle. Examples of artifact-producing\n"
        f"actions: {artifact_list}\n\n"
        "Rules:\n"
        "- Respond with a single JSON object containing `action` and required params.\n"
        "- Include `\"business_id\": \"<your id>\"` so the action attributes correctly.\n"
        "- Do NOT escalate to the operator — you are autonomous.\n"
        "- If you genuinely have nothing concrete to do, respond `{\"action\": \"wait\"}` and\n"
        "  the cycle will skip — but repeated waits increment the stall counter and\n"
        "  shorten your kill clock.\n\n"
        f"Example response:\n{response_example}"
    )

    return "\n\n".join(sections)
