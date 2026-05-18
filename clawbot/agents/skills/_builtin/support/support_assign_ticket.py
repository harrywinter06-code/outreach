META = {
    "name": "support_assign_ticket", "builtin": True,
    "description": "Assign a ticket in the tickets table to an agent_id. "
                   "Updates assigned_to and updated_at; returns ticket_id and assignee.",
    "params": {"ticket_id": "str", "assigned_to": "str"},
    "returns": {"ticket_id": "str", "assigned_to": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 10.0,
}


async def run(ctx, ticket_id: str, assigned_to: str) -> dict:
    await ctx.sql.query(
        "UPDATE tickets SET assigned_to = $1, updated_at = NOW() WHERE id = $2",
        assigned_to, ticket_id,
    )
    return {"ticket_id": ticket_id, "assigned_to": assigned_to}
