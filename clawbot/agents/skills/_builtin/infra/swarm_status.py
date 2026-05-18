"""Swarm Z2 — operator-queryable snapshot of swarm population state."""

META = {
    "name": "swarm_status",
    "builtin": True,
    "description": "Snapshot of swarm population: active count, templates, total revenue, per-business fitness/revenue.",
    "params": {},
    "returns": {
        "active_count": "int",
        "active_cap": "int",
        "template_count": "int",
        "total_revenue_gbp": "float",
        "active_summary": "str",
    },
}


async def run(ctx) -> dict:
    """Read directly from the businesses + business_templates tables.

    Does NOT go through SwarmController (which lives in the scheduler process,
    not the skill ctx); reads SQL directly so any caller can see swarm shape.
    """
    rows = await ctx.sql.query(
        "SELECT business_id, name, niche, fitness_score, revenue_total_gbp, "
        "budget_remaining_gbp, EXTRACT(EPOCH FROM (NOW() - spawned_at)) / 86400.0 AS age_days "
        "FROM businesses WHERE status='active' "
        "ORDER BY fitness_score DESC, revenue_total_gbp DESC LIMIT 50"
    )
    template_rows = await ctx.sql.query("SELECT COUNT(*) AS n FROM business_templates")
    rev_rows = await ctx.sql.query(
        "SELECT COALESCE(SUM(revenue_total_gbp), 0.0) AS t FROM businesses"
    )
    total_rev = float(rev_rows[0]["t"]) if rev_rows else 0.0

    lines = []
    for r in rows:
        lines.append(
            f"{r['business_id'][:8]} {r['name'][:24]:24s} "
            f"fit={float(r['fitness_score']):.2f} "
            f"£{float(r['revenue_total_gbp']):.2f} "
            f"age={float(r['age_days']):.1f}d"
        )

    return {
        "active_count": len(rows),
        "active_cap": 0,  # caller can cross-ref settings; this skill stays cap-agnostic
        "template_count": int(template_rows[0]["n"]) if template_rows else 0,
        "total_revenue_gbp": round(total_rev, 2),
        "active_summary": "\n".join(lines) if lines else "(no active businesses)",
    }
