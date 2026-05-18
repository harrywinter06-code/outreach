import base64
import json

META = {
    "name": "keyword_research", "builtin": True,
    "description": "Volume + difficulty + CPC for a seed keyword via DataForSEO Labs. Requires DATAFORSEO_LOGIN/PASSWORD.",
    "params": {"keyword": "str", "location_code": "int", "language_code": "str"},
    "returns": {"data": "list", "status": "int"},
    "cost_estimate_usd": 0.001, "timeout_s": 30.0,
}


async def run(ctx, keyword: str, location_code: int = 2840, language_code: str = "en") -> dict:
    login = ctx.secret.get("DATAFORSEO_LOGIN")
    pwd = ctx.secret.get("DATAFORSEO_PASSWORD")
    if not (login and pwd):
        return {"data": [], "status": 401}
    auth = base64.b64encode(f"{login}:{pwd}".encode()).decode()
    body = [{
        "keywords": [keyword],
        "location_code": location_code,
        "language_code": language_code,
    }]
    resp = await ctx.http.post(
        "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
        json=body,
        headers={"Authorization": f"Basic {auth}"},
    )
    text = str(resp.get("text", ""))
    data: list = []
    if resp.get("status") == 200 and text:
        try:
            payload = json.loads(text)
            tasks = payload.get("tasks", [])
            if tasks and tasks[0].get("result"):
                data = tasks[0]["result"]
        except (ValueError, json.JSONDecodeError):
            data = []
    return {"data": data, "status": int(resp.get("status", 0))}
