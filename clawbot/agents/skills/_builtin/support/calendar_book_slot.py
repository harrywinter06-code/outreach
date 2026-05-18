META = {
    "name": "calendar_book_slot", "builtin": True,
    "description": "Book a slot on a Cal.com event type for a customer. Requires CAL_COM_API_KEY. "
                   "Returns booking id and confirmation URL.",
    "params": {
        "event_type_id": "int", "start_iso": "str", "attendee_email": "str",
        "attendee_name": "str", "notes": "str",
    },
    "returns": {"booking_id": "str", "url": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 20.0,
}


async def run(
    ctx, event_type_id: int, start_iso: str, attendee_email: str,
    attendee_name: str, notes: str = "",
) -> dict:
    api_key = ctx.secret.get("CAL_COM_API_KEY")
    payload = {
        "eventTypeId": event_type_id,
        "start": start_iso,
        "responses": {
            "email": attendee_email,
            "name": attendee_name,
            "notes": notes,
        },
        "timeZone": "UTC",
        "language": "en",
    }
    resp = await ctx.http.post(
        f"https://api.cal.com/v1/bookings?apiKey={api_key}",
        json=payload,
    )
    import json as _json
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    booking = data.get("booking") or data
    return {
        "booking_id": str(booking.get("id", "")),
        "url": booking.get("url") or booking.get("uid", ""),
    }
