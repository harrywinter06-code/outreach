META = {
    "name": "vector_write", "builtin": True,
    "description": "Write a memory to the company brain. Kind: observation, decision, lesson, signal.",
    "params": {"text": "str", "kind": "str"},
    "returns": {"id": "str"},
}


async def run(ctx, text: str, kind: str) -> dict:
    mem_id = await ctx.vector.write(text, kind=kind)
    return {"id": mem_id}
