import re

META = {
    "name": "arxiv_summarize", "builtin": True,
    "description": "Fetch an arXiv abstract page and produce a 3-bullet plain-English summary.",
    "params": {"arxiv_id": "str"},
    "returns": {"title": "str", "summary": "str"},
    "cost_estimate_usd": 0.002, "timeout_s": 60.0,
}


async def run(ctx, arxiv_id: str) -> dict:
    encoded = arxiv_id.replace(" ", "+")
    resp = await ctx.http.get(
        f"http://export.arxiv.org/api/query?id_list={encoded}",
    )
    text = str(resp.get("text", ""))
    title = ""
    abstract = ""
    m = re.search(r"<entry>(.*?)</entry>", text, flags=re.DOTALL)
    if m:
        entry = m.group(1)
        t = re.search(r"<title>(.*?)</title>", entry, flags=re.DOTALL)
        s = re.search(r"<summary>(.*?)</summary>", entry, flags=re.DOTALL)
        title = re.sub(r"\s+", " ", t.group(1).strip()) if t else ""
        abstract = re.sub(r"\s+", " ", s.group(1).strip()) if s else ""

    if not abstract:
        return {"title": title, "summary": ""}

    summary = await ctx.llm.complete(
        system="You translate dense academic abstracts into 3 short plain-English bullets. No jargon.",
        user=f"Title: {title}\n\nAbstract: {abstract}\n\nWrite 3 bullets.",
        tier="worker",
    )
    return {"title": title, "summary": summary}
