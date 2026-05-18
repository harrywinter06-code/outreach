META = {
    "name": "crm_upsert_lead", "builtin": True,
    "description": "Insert or update a lead in the leads table. Email is the primary key.",
    "params": {
        "email": "str", "name": "str", "company": "str",
        "title": "str", "source": "str", "stage": "str",
    },
    "returns": {"email": "str", "stage": "str", "created": "bool"},
}


async def run(
    ctx, email: str, name: str = "", company: str = "",
    title: str = "", source: str = "", stage: str = "new",
) -> dict:
    norm_email = email.strip().lower()
    existing = await ctx.sql.query(
        "SELECT email FROM leads WHERE email = $1", norm_email,
    )
    created = not bool(existing)
    await ctx.sql.query(
        "INSERT INTO leads (email, name, company, title, source, stage) "
        "VALUES ($1, $2, $3, $4, $5, $6) "
        "ON CONFLICT (email) DO UPDATE SET "
        "name = EXCLUDED.name, company = EXCLUDED.company, "
        "title = EXCLUDED.title, source = EXCLUDED.source, "
        "stage = EXCLUDED.stage, updated_at = NOW()",
        norm_email, name, company, title, source, stage,
    )
    return {"email": norm_email, "stage": stage, "created": created}
