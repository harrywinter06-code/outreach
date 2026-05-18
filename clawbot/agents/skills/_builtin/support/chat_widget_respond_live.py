META = {
    "name": "chat_widget_respond_live", "builtin": True,
    "description": "Publish a live chat-widget reply onto the chat.outbound bus topic. "
                   "Consumed by the widget gateway, which routes to the visitor session.",
    "params": {"session_id": "str", "text": "str"},
    "returns": {"message_id": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 5.0,
}


async def run(ctx, session_id: str, text: str) -> dict:
    msg_id = await ctx.bus.publish("chat.outbound", {
        "session_id": session_id,
        "text": text,
    })
    return {"message_id": msg_id}
