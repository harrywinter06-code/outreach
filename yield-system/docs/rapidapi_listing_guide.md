# RapidAPI Provider Listing — Step-by-Step Guide

Last updated: 2026-05-15. Verified against RapidAPI docs.

---

## Before you start

### Critical: OpenAPI version incompatibility

FastAPI 0.100+ generates **OpenAPI 3.1.0** by default. RapidAPI only accepts **2.0, 3.0.0, 3.0.1, and 3.0.2**. The spec at `docs/openapi.json` will be rejected.

Fix before submitting: downgrade the spec to 3.0.2 using the script below, or define endpoints manually in RapidAPI's UI.

```bash
# On Windows PowerShell — run from yield-system/
python3 - <<'EOF'
import json, re

with open("docs/openapi.json") as f:
    spec = json.load(f)

# Downgrade version
spec["openapi"] = "3.0.2"

# OpenAPI 3.1 uses anyOf for nullable — convert to nullable: true
spec_str = json.dumps(spec)
# Replace {"anyOf": [{"type": "X"}, {"type": "null"}]} -> {"type": "X", "nullable": true}
spec_str = re.sub(
    r'\{"anyOf":\s*\[\{"type":\s*"(\w+)"\},\s*\{"type":\s*"null"\}\]\}',
    r'{"type": "\1", "nullable": true}',
    spec_str
)

with open("docs/openapi_3_0_2.json", "w") as f:
    f.write(spec_str)

print("Saved docs/openapi_3_0_2.json")
EOF
```

Validate the output at https://editor.swagger.io before uploading.

---

### How RapidAPI authentication works with your backend

RapidAPI issues its own key (`X-RapidAPI-Key`) to consumers. It proxies their requests to your backend. You need to configure what RapidAPI sends *to your backend* as the auth header.

**The approach for Veriflow Labs:**
1. Create one dedicated "rapidapi" customer in your backend (see below)
2. Configure RapidAPI to inject that customer's `X-API-Key` as an additional request header on every proxied request
3. RapidAPI enforces its own tier rate limits (free/paid) before proxying
4. Your backend sees all RapidAPI traffic as a single authenticated customer

This means per-RapidAPI-subscriber tracking lives in RapidAPI's analytics, not your ledger. Acceptable for now.

**Create the RapidAPI backend customer (do once per API):**
```bash
flyctl ssh console -C "sh -c 'python3 -c \"from yield_system.auth import create_customer; r=create_customer(\\\"sanctions\\\", \\\"rapidapi@veriflowlabs.co.uk\\\", \\\"paid\\\"); print(r[\\\"api_key\\\"])\"'"
```
Run the same for `postcode`, `webhookq`, `email`. Note the 4 keys — you will paste them into RapidAPI's "Additional Header" config.

---

## Step 1 — Account and payout setup

1. Go to **https://rapidapi.com** and sign in (or create an account — same account for consumer + provider).
2. Click your avatar (top right) → **My APIs**. This puts you in provider mode.
3. In the left sidebar, click your account name dropdown → **Payment Settings**.
4. Click **Connect PayPal**. Follow the OAuth flow.
   - PayPal is the **only** payout method. Payoneer was discontinued.
   - Payouts are in **USD only**, paid out in the first week of the month following the billing period (i.e. May revenue → early July payout).
   - RapidAPI takes **25%** of all revenue. Price accordingly.

Do not skip this — APIs cannot go public until payout is configured.

---

## Step 2 — Create each API listing

You will create 4 separate listings. Do one at a time. The steps are identical for each.

### 2a. Create the API

1. Go to **My APIs** → click **+ Add New API** (left sidebar).
2. Fill in the three required fields:
   - **API Name** — use the names below. No special characters (`!@#$%^&*`). Spaces and dashes are fine.
   - **Short Description** — shown in search tiles, gets truncated. Keep under 100 chars.
   - **Category** — use the categories below.
3. Click **Add API**.

| | API Name | Short Description | Category |
|---|---|---|---|
| A | Sanctions Screening | Batch-screen names against OFAC SDN, UK HMT OFSI, and EU consolidated lists | Finance |
| B | UK Postcode Enrichment | Resolve any UK postcode to lat/lng, LSOA, MSOA, and IMD 2019 deprivation data | Data |
| C | Webhook Delivery Queue | Managed webhook retry with idempotency keys, exponential backoff, and event replay | Tools |
| D | Email DNS Compliance Score | Composite A–F score across MX, SPF, DMARC, BIMI, and DNSSEC for any domain | Email |

### 2b. Import the OpenAPI spec

After creating the API you land on the **Hub Listing** tab.

1. Click **Definitions** in the left sidebar.
2. Click **Add Definition** → **Import from OpenAPI**.
3. Upload `docs/openapi_3_0_2.json` (the downgraded spec you generated above).
   - **Important**: only import the endpoints relevant to this API. The full spec includes all 4 products. You can either:
     - Upload the full spec and then **delete** unrelated endpoints in the Definitions UI, or
     - Create a filtered spec per API before uploading (cleaner)
4. If the import fails, paste the JSON into https://editor.swagger.io, fix any errors it reports, re-export, and re-upload.

**Endpoints per API:**

| API | Keep | Delete |
|---|---|---|
| A Sanctions | `/v1/sanctions/screen`, `/v1/sanctions/watchlist` | all others |
| B Postcode | `/v1/postcode/{raw}` | all others |
| C Webhook Queue | `/v1/webhookq/projects`, `/v1/webhookq/ingress/{token}`, `/v1/webhookq/events/{token}`, `/v1/webhookq/egress/{token}` | all others |
| D Email DNS | `/v1/domain/{domain}` | all others |

### 2c. Set the base URL

1. In **Definitions** → **Base URL**, enter: `https://yield-system.fly.dev`
2. Leave protocol as `https`.

### 2d. Configure authentication

1. In **Definitions** → **Security**, click **New Scheme**.
2. Set:
   - **Scheme name**: `ApiKeyAuth`
   - **Authorization set**: `API Key`
   - **Key**: `X-API-Key`
   - **Add to**: `Header`
3. Click **Save**.
4. Apply this scheme to **all endpoints** for this API.

Then add the backend key as an additional header:

1. Go to **Definitions** → **Additional Request Headers** (or find it under the endpoint config).
2. Add a header:
   - **Name**: `X-API-Key`
   - **Value**: the `ys_...` key you generated in the pre-step above for this specific API
3. This is what RapidAPI will inject when proxying to your backend. It is static and shared across all RapidAPI consumers of this API.

> **Note**: this means all RapidAPI traffic hits your backend as one customer. Rate limiting for RapidAPI consumers is enforced by RapidAPI's plan quotas, not your backend.

### 2e. Write the listing description

In **Hub Listing** → **Overview**, paste the long description for this API (markdown is supported):

---

**API A — Sanctions Screening:**
```
Screen individuals and entities against all major public sanctions lists in a single API call.

**Data sources (refreshed daily):**
- OFAC SDN (US Treasury) — 18,959 entries
- UK HMT OFSI Consolidated List — 5,134 entries

**Key features:**
- Batch up to 1,000 names per call
- Names normalised (unicode, case, punctuation) before matching
- Returns matched name, source list, sanctions programme, and known aliases
- `POST /v1/sanctions/watchlist` — subscribe a webhook URL to receive a push when a watched name appears on any list

**Authentication:** X-API-Key header (issued by Veriflow Labs, not RapidAPI)
**Base URL:** https://yield-system.fly.dev
```

**API B — UK Postcode Enrichment:**
```
One call returns everything you need for a UK postcode:

- **Coordinates** — WGS84 lat/lng
- **Admin geography** — LSOA code, MSOA code, district, region
- **IMD 2019 deprivation** — decile (1 = most deprived), quintile, raw score

Built on ONS Open Geography data. No separate ONS account or data licence required.

**Authentication:** X-API-Key header
**Base URL:** https://yield-system.fly.dev
```

**API C — Webhook Delivery Queue:**
```
Offload reliable webhook delivery from your own stack.

1. `POST /v1/webhookq/projects` — create a project, get an ingress token
2. Point your upstream service at `POST /v1/webhookq/ingress/{token}`
3. Events queue durably; delivered to your target URL with exponential backoff retry
4. Replay any event to a new URL via `POST /v1/webhookq/egress/{token}`

**Features:**
- Idempotency keys — duplicate payloads with the same body+key are deduplicated (returns 409)
- Exponential backoff retry on failed deliveries
- `GET /v1/webhookq/events/{token}` — list stored events with cursor pagination
- 7-day event retention (free tier)
- UK data residency (London, Fly.io lhr)

**Authentication:** no auth required for ingress (token in URL path); X-API-Key for management endpoints
**Base URL:** https://yield-system.fly.dev
```

**API D — Email DNS Compliance Score:**
```
One call returns a composite email compliance score across all major DNS records.

**Returns:**
- MX records list
- SPF record (raw value)
- DMARC policy (raw value)
- BIMI record (raw value)
- DNSSEC enabled (boolean)
- Composite grade A–F with point breakdown (max 100)
- Specific fix recommendations for each gap

**Scoring:**
- MX: 20pts  |  SPF: 20–25pts  |  DMARC: 20–30pts  |  BIMI: 10pts  |  DNSSEC: 15pts

Google and Yahoo require DMARC authentication for bulk senders (mandate: Feb 2024).

**Authentication:** X-API-Key header
**Base URL:** https://yield-system.fly.dev
```

---

### 2f. Set pricing

1. Go to **Hub Listing** → **Pricing**.
2. Click **Create Plan** twice to create two plans.

**Plan 1 — Basic (free):**
- Name: `Basic`
- Price: `$0 / month`
- Quota type: `Requests`
- Limit: `100 / day` (hard limit)

**Plan 2 — Pro (paid):**
- Name: `Pro`
- Price: use the values below
- Quota type: `Requests`
- Limit: Unlimited (or a very high number like 10,000,000/month)

| API | Pro price (USD/mo) | Your net after 25% | ~GBP net |
|---|---|---|---|
| A Sanctions | $37 | $27.75 | ~£22 |
| B Postcode | $25 | $18.75 | ~£15 |
| C Webhook Queue | $25 | $18.75 | ~£15 |
| D Email DNS | $25 | $18.75 | ~£15 |

> RapidAPI prices are USD. These figures are intentionally set to land near the GBP prices on your direct landing page after the 25% cut.

### 2g. Add logo and external website

1. **Hub Listing** → **Overview** → upload a logo (PNG, square, at least 200×200px). Use `Veriflow Labs Logo.jpg` from the project root — crop to square first.
2. Set **Website URL**: `https://yield-system.fly.dev`

RapidAPI documentation says APIs without an external website rank lower. Always fill this in.

### 2h. Request public listing

1. Go to **Hub Listing** → **Overview** → click **Make Public** or **Submit for Review** (button wording varies).
2. RapidAPI will review the listing. Timelines are not officially documented — contact support via https://rapidapi.zendesk.com if no response in 5 business days.
3. While awaiting review, the API is visible to you in private mode and you can test via the RapidAPI playground.

---

## Step 3 — Test before going live

1. In your listing, click **Test Endpoint** (the playground tab).
2. Paste your `X-API-Key` value (the `ys_...` backend key).
3. Run a test call — verify you get a real response, not a 401 or 422.
4. If you get 422: check the base URL is exactly `https://yield-system.fly.dev` (no trailing slash).
5. If you get 401/403: verify the additional request header is configured with the correct key.

---

## Step 4 — After listing goes live

1. Monitor **Analytics** in the provider dashboard — track requests, subscribers, and revenue.
2. Watch the **Discussion** tab — answer questions there; it directly impacts consumer trust.
3. Check **Subscriptions** — see which tier each subscriber is on.

---

## Submission order

Submit all 4 simultaneously so reviews run in parallel. Estimated time to first paid subscriber via RapidAPI: 1–3 weeks (account approval + consumer discovery + trial → upgrade).

Checklist:
- [ ] Run the OpenAPI 3.0.2 downgrade script and validate the output
- [ ] Connect PayPal in Payment Settings
- [ ] Create 4 backend API keys (one per experiment) for RapidAPI traffic
- [ ] Create and configure all 4 listings (name, description, base URL, security, pricing)
- [ ] Test each endpoint in the RapidAPI playground
- [ ] Submit all 4 for public listing
