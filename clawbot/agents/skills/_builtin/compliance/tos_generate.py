META = {
    "name": "tos_generate", "builtin": True,
    "description": "Generate a Terms of Service draft for a company. Uses ctx.llm with an "
                   "executive-tier model and a fixed template. NOT legal advice — the output "
                   "should be reviewed by a solicitor before going live.",
    "params": {
        "company_name": "str", "jurisdiction": "str",
        "product_description": "str", "billing_model": "str",
    },
    "returns": {"tos_markdown": "str"},
    "cost_estimate_usd": 0.05, "timeout_s": 60.0,
}


async def run(
    ctx, company_name: str, jurisdiction: str,
    product_description: str, billing_model: str,
) -> dict:
    system = (
        "You are a startup legal-template generator. You produce conservative, "
        "industry-standard Terms of Service in Markdown. You DO NOT invent obligations. "
        "You output the full document only — no preamble."
    )
    user = (
        f"Company: {company_name}\n"
        f"Governing law: {jurisdiction}\n"
        f"Product: {product_description}\n"
        f"Billing model: {billing_model}\n\n"
        "Generate a complete Terms of Service in Markdown with these sections: "
        "Acceptance, Account Registration, Acceptable Use, Subscription & Billing, "
        "Termination, Intellectual Property, Limitation of Liability, "
        "Indemnification, Governing Law, Changes to Terms, Contact."
    )
    text = await ctx.llm.complete(system=system, user=user, tier="executive")
    return {"tos_markdown": text}
