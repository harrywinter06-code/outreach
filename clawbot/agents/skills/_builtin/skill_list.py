"""Built-in skill: list every registered skill with name + description.

Retrieves the brain-stored catalog via vector search and parses it back into
structured entries. Falls back to empty list if the catalog has not been written yet.
"""

META = {
    "name": "skill_list",
    "builtin": True,
    "description": "List every currently-registered skill with name + description. Use to discover what actions are available.",
    "params": {},
    "returns": {"skills": "list", "count": "int"},
}


async def run(ctx) -> dict:
    matches = await ctx.vector.search("Available skills catalog", k=1)
    if not matches:
        return {"skills": [], "count": 0}
    catalog_text = matches[0].get("text", "")
    skills = []
    for line in catalog_text.splitlines():
        line = line.strip()
        if line.startswith("- ") and ": " in line:
            name, _, desc = line[2:].partition(": ")
            skills.append({"name": name.strip(), "description": desc.strip()})
    return {"skills": skills, "count": len(skills)}
