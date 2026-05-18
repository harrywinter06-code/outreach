META = {
    "name": "privacy_policy_generate", "builtin": True,
    "description": "Generate a Privacy Policy draft for a company, GDPR/UK-GDPR aware. Uses "
                   "ctx.llm executive tier. Output is a draft — review by a solicitor before going live.",
    "params": {
        "company_name": "str", "jurisdiction": "str",
        "data_categories": "list", "third_party_processors": "list",
    },
    "returns": {"policy_markdown": "str"},
    "cost_estimate_usd": 0.05, "timeout_s": 60.0,
}


async def run(
    ctx, company_name: str, jurisdiction: str,
    data_categories: list | None = None,
    third_party_processors: list | None = None,
) -> dict:
    cats = data_categories or []
    proc = third_party_processors or []
    system = (
        "You are a startup legal-template generator. You produce conservative, "
        "industry-standard Privacy Policies in Markdown. You DO NOT invent processors "
        "or data categories beyond those listed. You output the full document only."
    )
    user = (
        f"Company: {company_name}\n"
        f"Governing law: {jurisdiction}\n"
        f"Personal data categories collected: {', '.join(cats) if cats else 'none specified'}\n"
        f"Third-party processors: {', '.join(proc) if proc else 'none'}\n\n"
        "Generate a complete Privacy Policy in Markdown with these sections: "
        "What data we collect, How we use it, Lawful bases (GDPR/UK-GDPR), "
        "Sharing & processors, International transfers, Retention, Your rights, "
        "Cookies, Children's privacy, Changes to this policy, Contact."
    )
    text = await ctx.llm.complete(system=system, user=user, tier="executive")
    return {"policy_markdown": text}
