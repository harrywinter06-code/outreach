import base64
import json

META = {
    "name": "serp_check", "builtin": True,
    "description": "Pull live SERP results for a keyword via DataForSEO. Returns the top organic results. Requires DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD.",
    "params": {"keyword": "str", "location_code": "int", "language_code": "str"},
    "returns": {"results": "list", "status": "int"},
    "cost_estimate_usd": 0.001, "timeout_s": 30.0,
}


async def run(ctx, keyword: str, location_code: int = 2840, language_code: str = "en") -> dict:
    login = ctx.secret.get("DATAFORSEO_LOGIN")
    pwd = ctx.secret.get("DATAFORSEO_PASSWORD")
    if not (login and pwd):
        return {"results": [], "status": 401}
    auth = base64.b64encode(f"{login}:{pwd}".encode()).decode()
    body = [{
        "keyword": keyword, "location_code": location_code,
        "language_code": language_code, "depth": 10,
    }]
    resp = await ctx.http.post(
        "https://api.dataforseo.com/v3/serp/google/organic/live/advanced",
        json=body,
        headers={"Authorization": f"Basic {auth}"},
    )
    text = str(resp.get("text", ""))
    results: list = []
    if resp.get("status") == 200 and text:
        try:
            payload = json.loads(text)
            tasks = payload.get("tasks", [])
            if tasks and tasks[0].get("result"):
                items = tasks[0]["result"][0].get("items", [])
                results = [
                    {"rank": i.get("rank_absolute"), "url": i.get("url"),
                     "title": i.get("title"), "domain": i.get("domain")}
                    for i in items if i.get("type") == "organic"
                ]
        except (ValueError, json.JSONDecodeError):
            results = []
    return {"results": results, "status": int(resp.get("status", 0))}
