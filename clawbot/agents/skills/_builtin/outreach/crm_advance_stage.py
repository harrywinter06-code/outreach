META = {
    "name": "crm_advance_stage", "builtin": True,
    "description": "Move a lead to a new pipeline stage (e.g., 'contacted', 'replied', 'qualified', 'closed_won', 'closed_lost').",
    "params": {"email": "str", "new_stage": "str"},
    "returns": {"email": "str", "stage": "str", "updated": "bool"},
}


async def run(ctx, email: str, new_stage: str) -> dict:
    norm = email.strip().lower()
    rows = await ctx.sql.query(
        "UPDATE leads SET stage = $1, updated_at = NOW() "
        "WHERE email = $2 RETURNING email, stage",
        new_stage, norm,
    )
    updated = bool(rows)
    return {
        "email": norm,
        "stage": new_stage if updated else "",
        "updated": updated,
    }
