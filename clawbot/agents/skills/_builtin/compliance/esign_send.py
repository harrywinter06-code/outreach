META = {
    "name": "esign_send", "builtin": True,
    "description": "Send a document for e-signature via Dropbox Sign (formerly HelloSign). "
                   "Needs DROPBOX_SIGN_API_KEY. The file is referenced by an already-uploaded "
                   "file URL; this skill creates a signature request, not the upload step.",
    "params": {
        "title": "str", "subject": "str", "file_url": "str",
        "signer_name": "str", "signer_email": "str",
    },
    "returns": {"signature_request_id": "str", "signing_url": "str"},
    "cost_estimate_usd": 0.0, "timeout_s": 30.0,
}


async def run(
    ctx, title: str, subject: str, file_url: str,
    signer_name: str, signer_email: str,
) -> dict:
    import base64 as _b64
    import json as _json
    api_key = ctx.secret.get("DROPBOX_SIGN_API_KEY")
    auth = _b64.b64encode(f"{api_key}:".encode()).decode()
    resp = await ctx.http.post(
        "https://api.hellosign.com/v3/signature_request/send",
        json={
            "title": title, "subject": subject,
            "file_url": [file_url],
            "signers": [{"email_address": signer_email, "name": signer_name}],
            "test_mode": 0,
        },
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
    )
    try:
        data = _json.loads(resp.get("text") or "{}")
    except ValueError:
        data = {}
    request = data.get("signature_request", {})
    signatures = request.get("signatures", [])
    signing_url = signatures[0].get("sign_url", "") if signatures else ""
    return {
        "signature_request_id": str(request.get("signature_request_id", "")),
        "signing_url": signing_url,
    }
