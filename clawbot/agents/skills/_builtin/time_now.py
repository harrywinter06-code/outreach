META = {
    "name": "time_now", "builtin": True,
    "description": "Current UTC time as ISO string and epoch seconds.",
    "params": {},
    "returns": {"iso": "str", "epoch": "float"},
}


async def run(ctx) -> dict:
    return {"iso": ctx.time.now_iso(), "epoch": ctx.time.epoch_s()}
