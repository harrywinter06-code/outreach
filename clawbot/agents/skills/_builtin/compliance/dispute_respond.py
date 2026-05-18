META = {
    "name": "dispute_respond", "builtin": True,
    "description": "Submit evidence to a Stripe dispute. The evidence dict should follow Stripe's "
                   "dispute-evidence schema (customer_communication, receipt, service_documentation, "
                   "shipping_address, etc.). Submitting starts the evidence-review clock.",
    "params": {"dispute_id": "str", "evidence": "dict"},
    "returns": {"id": "str", "status": "str", "submitted": "bool"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(ctx, dispute_id: str, evidence: dict) -> dict:
    result = await ctx.payments.respond_to_dispute(
        dispute_id=dispute_id, evidence=evidence,
    )
    return {
        "id": str(result.get("id", dispute_id)),
        "status": result.get("status", "unknown"),
        "submitted": bool(result.get("evidence_submitted", True)),
    }
