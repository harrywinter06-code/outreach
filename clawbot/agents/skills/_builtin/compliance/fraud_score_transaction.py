META = {
    "name": "fraud_score_transaction", "builtin": True,
    "description": "Read Stripe Radar's risk_score for a charge (0=safe, 100=high risk). "
                   "Composes ctx.payments.list_charges; finds the charge and returns its score "
                   "+ Radar outcome. Needs STRIPE_SECRET_KEY.",
    "params": {"charge_id": "str"},
    "returns": {"risk_score": "int", "outcome": "str", "rule_name": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 15.0,
}


async def run(ctx, charge_id: str) -> dict:
    charges = await ctx.payments.list_charges(limit=100)
    for charge in charges:
        if str(charge.get("id", "")) == charge_id:
            outcome_obj = charge.get("outcome") or {}
            return {
                "risk_score": int(outcome_obj.get("risk_score", 0)),
                "outcome": outcome_obj.get("type", "unknown"),
                "rule_name": (outcome_obj.get("rule") or {}).get("description", ""),
            }
    return {"risk_score": -1, "outcome": "not_found", "rule_name": ""}
