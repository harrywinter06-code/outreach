META = {
    "name": "hashnode_publish", "builtin": True,
    "description": "Publish a post to Hashnode via GraphQL. Requires HASHNODE_PAT + HASHNODE_PUBLICATION_ID.",
    "params": {"title": "str", "body_markdown": "str", "tags": "list"},
    "returns": {"ok": "bool", "url": "str", "id": "str"},
}


async def run(
    ctx, title: str, body_markdown: str, tags: list | None = None,
) -> dict:
    import json as _json
    token = ctx.secret.get("HASHNODE_PAT")
    pub_id = ctx.secret.get("HASHNODE_PUBLICATION_ID")
    if not (token and pub_id):
        return {"ok": False, "url": "", "id": ""}
    tag_objects = [{"slug": t.lower().replace(" ", "-"), "name": t} for t in (tags or [])[:5]]
    query = """
    mutation PublishPost($input: PublishPostInput!) {
      publishPost(input: $input) {
        post { id slug url }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {"input": {
            "title": title,
            "contentMarkdown": body_markdown,
            "publicationId": pub_id,
            "tags": tag_objects,
        }},
    }
    res = await ctx.http.post(
        "https://gql.hashnode.com/",
        json=payload,
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    ok = 200 <= int(res.get("status", 0)) < 300
    try:
        body = _json.loads(res.get("text", "{}"))
        post = body.get("data", {}).get("publishPost", {}).get("post", {}) or {}
    except _json.JSONDecodeError:
        post = {}
    return {
        "ok": ok and bool(post),
        "url": str(post.get("url", "")),
        "id": str(post.get("id", "")),
    }
