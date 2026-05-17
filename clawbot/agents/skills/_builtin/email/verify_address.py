META = {
    "name": "email_verify_address", "builtin": True,
    "description": "Verify an email address deliverability. Returns deliverable bool and score 0-1.",
    "params": {"address": "str"},
    "returns": {"deliverable": "bool", "score": "float"},
}


async def run(ctx, address: str) -> dict:
    return await ctx.email.verify_address(address=address)
