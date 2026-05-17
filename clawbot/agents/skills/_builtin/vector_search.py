META = {
    "name": "vector_search", "builtin": True,
    "description": "Semantic search over company brain. Returns up to k matching memories.",
    "params": {"query": "str", "k": "int"},
    "returns": {"matches": "list"},
}


async def run(ctx, query: str, k: int = 5) -> dict:
    matches = await ctx.vector.search(query, k=k)
    return {"matches": matches}
