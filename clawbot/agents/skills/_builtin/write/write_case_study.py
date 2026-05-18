META = {
    "name": "write_case_study", "builtin": True,
    "description": "Write a customer case study from problem/solution/results inputs. Markdown.",
    "params": {
        "customer_name": "str", "customer_role": "str",
        "problem": "str", "solution": "str", "results": "str",
        "interview_transcript": "str",
    },
    "returns": {"text": "str"},
    "cost_estimate_usd": 0.03,
    "timeout_s": 60.0,
}


async def run(
    ctx, customer_name: str, customer_role: str,
    problem: str, solution: str, results: str,
    interview_transcript: str = "",
) -> dict:
    system = (
        "You write B2B case studies. Markdown, 400-700 words. "
        "Structure: 1) one-paragraph customer intro, 2) Problem (what they tried, "
        "what failed), 3) Solution (how they used the product), 4) Results "
        "(numbers, with %s and absolute values), 5) One direct quote from the "
        "interview transcript if provided. No hype."
    )
    user = (
        f"Customer: {customer_name} ({customer_role})\n"
        f"Problem: {problem}\n"
        f"Solution: {solution}\n"
        f"Results: {results}\n"
        f"Interview transcript (use for direct quote):\n{interview_transcript[:4000]}\n\n"
        f"Write the case study. Markdown only."
    )
    text = await ctx.llm.complete(system=system, user=user, tier="executive")
    return {"text": text}
