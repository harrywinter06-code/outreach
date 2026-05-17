META = {
    "name": "stripe_issue_card", "builtin": True,
    "description": "Issue a virtual Stripe card for an agent with a daily spend limit (USD). "
                   "Returns card id + last4 + expiry. Agent uses these via browser-use to checkout.",
    "params": {"cardholder_id": "str", "daily_limit_usd": "int", "agent_id": "str"},
    "returns": {"id": "str", "last4": "str", "exp_month": "int",
                "exp_year": "int", "status": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0, "requires_approval": True,
}


async def run(ctx, cardholder_id: str, daily_limit_usd: int, agent_id: str) -> dict:
    card = await ctx.payments.issue_card(
        cardholder_id=cardholder_id,
        daily_limit_usd=daily_limit_usd,
        agent_id=agent_id,
    )
    return {
        "id": card["id"], "last4": card["last4"],
        "exp_month": card["exp_month"], "exp_year": card["exp_year"],
        "status": card["status"],
    }
