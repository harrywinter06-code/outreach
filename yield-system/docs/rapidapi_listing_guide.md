# RapidAPI Listing Guide — Veriflow Labs

## Account setup (do once)
1. Go to https://rapidapi.com/provider
2. Sign in / create account
3. Go to **My APIs → + Add New API**
4. For each API below: choose **Import from OpenAPI** and paste the spec URL or the JSON from `docs/openapi.json` filtered to that API's paths.

Base URL for all APIs: `https://yield-system.fly.dev`
Authentication: **Header** `X-API-Key` — users get this from `POST /signup` or the landing page form.

---

## API A — Sanctions Screening

**Name:** Sanctions Screening API  
**Short description:** Batch-screen up to 1,000 names per call against OFAC SDN, UK HMT OFSI, and EU consolidated sanctions lists. Real-time delta webhooks on list changes.  
**Category:** Finance → Compliance  
**Tags:** sanctions, compliance, KYC, AML, OFAC, HMT, fintech  
**Base URL:** `https://yield-system.fly.dev`

**Long description (paste into RapidAPI markdown editor):**

Screen individuals and entities against all major sanctions lists in a single API call.

**Data sources refreshed daily:**
- OFAC SDN (US Treasury) — 18,959 entries
- UK HMT OFSI Consolidated List — 5,134 entries
- EU Consolidated Sanctions List — coming soon

**Key features:**
- Batch up to 1,000 names per request
- Returns matched name, source list, sanctions programme, and known aliases
- Subscribe to delta webhooks — receive a push notification the moment a watched name appears on any list (no polling required)
- Names are normalised (unicode, case, punctuation) before matching

**Pricing on RapidAPI:**
| Tier | Price | Limit |
|------|-------|-------|
| Free | $0/mo | 100 req/day |
| Pro | $36/mo | Unlimited |

*(Set RapidAPI price to $36/mo to cover their 25% cut and land at ~£21 net, close to our £29 target)*

**Endpoints to expose:**
- `POST /v1/sanctions/screen` — batch name screening
- `POST /v1/sanctions/watchlist` — subscribe to delta webhook

---

## API B — UK Postcode Enrichment

**Name:** UK Postcode Enrichment API  
**Short description:** Resolve any UK postcode to lat/lng, LSOA/MSOA codes, admin boundaries, and full IMD 2019 deprivation data (decile, quintile, score) in a single call.  
**Category:** Data → Geolocation  
**Tags:** postcode, UK, deprivation, IMD, LSOA, geolocation, enrichment  
**Base URL:** `https://yield-system.fly.dev`

**Long description:**

One call returns everything you need for a UK postcode:
- **Coordinates** — WGS84 lat/lng
- **Admin geography** — LSOA code, MSOA code, district, region
- **IMD 2019 deprivation data** — decile (1=most deprived), quintile, raw score

Built on ONS Open Geography data. No ONS account or data licence required.

**Use cases:** insurance underwriting, PropTech site selection, health analytics, local authority dashboards, mortgage risk scoring.

**Pricing on RapidAPI:**
| Tier | Price | Limit |
|------|-------|-------|
| Free | $0/mo | 100 req/day |
| Pro | $24/mo | Unlimited |

*(£17.40 net after RapidAPI cut — acceptable for this tier)*

**Endpoints to expose:**
- `GET /v1/postcode/{postcode}` — single postcode lookup

---

## API C — Webhook Queue

**Name:** Webhook Delivery Queue  
**Short description:** Guaranteed at-least-once webhook delivery with idempotency keys and exponential backoff retry. UK data residency. 7-day free retention.  
**Category:** Tools → Developer Tools  
**Tags:** webhook, retry, queue, idempotent, delivery, infrastructure  
**Base URL:** `https://yield-system.fly.dev`

**Long description:**

Offload reliable webhook delivery from your own stack.

**How it works:**
1. Create a project → get an ingress token
2. Point your upstream service at `POST /v1/webhookq/ingress/{token}`
3. Events are stored durably and delivered to your target URL
4. Failed deliveries retry with exponential backoff (1s → 2s → 4s → … up to 24h)
5. Idempotency keys prevent duplicate processing on retries

**Features:**
- Idempotent ingress — duplicate payloads with the same body+key are deduplicated
- Replay any events to a new URL via `POST /v1/webhookq/egress/{token}`
- 7-day retention (free), 30-day (paid)
- UK data residency (London Fly.io region)

**Pricing on RapidAPI:**
| Tier | Price | Limit |
|------|-------|-------|
| Free | $0/mo | 100 req/day |
| Pro | $24/mo | Unlimited |

**Endpoints to expose:**
- `POST /v1/webhookq/projects` — create project, get token
- `POST /v1/webhookq/ingress/{token}` — receive events
- `GET /v1/webhookq/events/{token}` — list stored events
- `POST /v1/webhookq/egress/{token}` — replay events to target URL

---

## API D — Email DNS Compliance Score

**Name:** Email DNS Compliance Score  
**Short description:** Composite A–F compliance score across MX, SPF, DMARC, BIMI, and DNSSEC for any domain. Identifies misconfigured records in a single call.  
**Category:** Email → Verification  
**Tags:** email, DNS, SPF, DMARC, BIMI, DNSSEC, deliverability, compliance  
**Base URL:** `https://yield-system.fly.dev`

**Long description:**

One API call tells you exactly how well a domain is configured for email delivery and security.

**Returns:**
- MX records list
- SPF record (raw value)
- DMARC policy (raw value)
- BIMI record (raw value)
- DNSSEC enabled (boolean)
- Composite score A–F with point breakdown
- Specific recommendations for each missing or misconfigured record

**Why it matters:** Google and Yahoo require DMARC authentication for bulk senders as of February 2024. Non-compliant domains get rejected or junked.

**Use cases:** deliverability audits, lead list hygiene, domain portfolio monitoring, pre-send compliance checks, security tooling.

**Pricing on RapidAPI:**
| Tier | Price | Limit |
|------|-------|-------|
| Free | $0/mo | 100 req/day |
| Pro | $24/mo | Unlimited |

**Endpoints to expose:**
- `GET /v1/domain/{domain}` — score a domain

---

## Submission checklist

- [ ] Create RapidAPI provider account
- [ ] Add billing/payout method (Payoneer or PayPal — needed before listing goes live)
- [ ] Create API A (Sanctions) — import OpenAPI, set pricing, submit for review
- [ ] Create API B (Postcode) — import OpenAPI, set pricing, submit for review
- [ ] Create API C (Webhook Queue) — import OpenAPI, set pricing, submit for review
- [ ] Create API D (Email DNS) — import OpenAPI, set pricing, submit for review
- [ ] Update RapidAPI base URL once custom domain is live (`veriflowlabs.co.uk`)

**Expected review time:** 3–7 days. Submit all four at once to run reviews in parallel.
