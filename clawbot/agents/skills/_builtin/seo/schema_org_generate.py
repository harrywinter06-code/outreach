import json

META = {
    "name": "schema_org_generate", "builtin": True,
    "description": "Emit a schema.org JSON-LD <script> block from a typed properties dict. Useful for Product/Article/Organization page markup.",
    "params": {"schema_type": "str", "properties": "dict"},
    "returns": {"json_ld": "str", "script_tag": "str"},
}


async def run(ctx, schema_type: str, properties: dict) -> dict:
    doc: dict = {"@context": "https://schema.org", "@type": schema_type, **properties}
    json_ld = json.dumps(doc, indent=2, ensure_ascii=False)
    script_tag = f'<script type="application/ld+json">\n{json_ld}\n</script>'
    return {"json_ld": json_ld, "script_tag": script_tag}
