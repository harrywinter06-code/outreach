# Outreach Email Templates — Veriflow Labs

Send from: harrywinter06@gmail.com (or hello@veriflowlabs.co.uk once domain is live)  
Subject lines A/B tested below. Use plain-text emails — compliance buyers are sceptical of HTML.

---

## Segment 1 — Fintech / Compliance teams (Sanctions API)

**Target titles:** Compliance Officer, MLRO, Head of Compliance, KYC Lead, AML Analyst  
**Target companies:** challenger banks, payment processors, crypto exchanges, FX brokers, lending platforms  
**Finding targets:** LinkedIn search "compliance officer" + fintech UK; GitHub orgs of UK fintechs; BuiltWith for companies using similar compliance APIs

**Subject A:** Sanctions API — OFAC + HMT in one call, 100 req/day free  
**Subject B:** Quick one: are you polling the OFAC SDN list manually?

---

Hi [Name],

I noticed [Company] is [building payments / onboarding SMEs / operating in FX] — sanctions screening tends to be a recurring pain point at that scale.

We just launched a batch screening API that checks OFAC SDN, UK HMT OFSI, and EU consolidated lists in a single call (up to 1,000 names). There's a free tier (100 req/day, no card) and a paid tier at £29/month for unlimited.

What makes it slightly different from the big providers: delta webhooks. You subscribe to a name and get pushed a notification the moment it appears on any list — no polling, no cron job.

If you want to try it: https://yield-system.fly.dev — sign up for a free key on the page.

Happy to answer any questions.

Harry Winter  
Veriflow Labs

---

## Segment 2 — PropTech / InsurTech / Data teams (Postcode API)

**Target titles:** Data Engineer, CTO, Head of Data, Product Manager, Actuary  
**Target companies:** estate agents with tech, mortgage brokers, insurance underwriters, health data companies, local authority analytics teams  
**Finding targets:** BuiltWith for postcodes.io users; GitHub for repos that import `postcodes.io`; LinkedIn "data engineer" + proptech UK

**Subject A:** UK postcode → IMD deprivation data in one API call  
**Subject B:** Are you hitting postcodes.io and then manually joining IMD data?

---

Hi [Name],

Quick one — I saw [Company] [is building a property risk model / does mortgage affordability scoring / works with postcode-level health data].

We built a postcode enrichment API that returns lat/lng, LSOA/MSOA, admin boundaries, and full IMD 2019 deprivation data (decile, quintile, score) in a single call. No separate ONS download, no join — everything comes back in one JSON response.

Free tier is 100 req/day (no card). Paid is £19/month unlimited.

Endpoint: `GET https://yield-system.fly.dev/v1/postcode/SW1A1AA`  
Sign up: https://yield-system.fly.dev

Worth a look if the postcodes.io → IMD manual join is something you're doing today.

Harry Winter  
Veriflow Labs

---

## Segment 3 — SaaS / Platform engineers (Webhook Queue)

**Target titles:** Backend Engineer, Platform Engineer, Staff Engineer, CTO  
**Target companies:** SaaS platforms that send webhooks to customers, payment platforms, e-commerce tools, B2B APIs  
**Finding targets:** Twitter/X posts complaining about webhook reliability; GitHub issues about webhook retry; Hacker News threads on webhook infrastructure

**Subject A:** Webhook retry queue — at-least-once delivery, idempotency keys, UK data residency  
**Subject B:** Stop reinventing webhook retry logic

---

Hi [Name],

If [Company] sends webhooks to customers, you've probably already dealt with the classic failure modes: endpoint down, duplicate delivery on retry, no replay mechanism.

We built a managed webhook queue that handles this: guaranteed at-least-once delivery, idempotency keys to prevent duplicate processing, exponential backoff, and event replay to any URL. UK data residency (London).

It's a 2-step integration: point your upstream at our ingress URL, configure your delivery target. Free tier (100 req/day, no card). Paid at £19/month.

Docs: https://yield-system.fly.dev  
Sign up: same page, takes 30 seconds.

Harry Winter  
Veriflow Labs

---

## Segment 4 — Email marketing / deliverability (Email DNS API)

**Target titles:** Email Marketing Manager, Head of CRM, Deliverability Engineer, Marketing Ops  
**Target companies:** email service providers, agencies sending bulk campaigns, any company that cares about inbox rates  
**Finding targets:** HubSpot/Mailchimp/SendGrid partners; email marketing communities (EmailGeeks Slack); LinkedIn "email deliverability"

**Subject A:** Check SPF/DMARC/BIMI for any domain in one API call  
**Subject B:** Your clients' domains — are they Google/Yahoo compliant?

---

Hi [Name],

Since Google and Yahoo tightened bulk-sender requirements in February 2024, DMARC configuration has become a pre-send audit item for anyone serious about deliverability.

We have an API that checks any domain for MX, SPF, DMARC, BIMI, and DNSSEC in a single call and returns an A–F compliance grade with specific fix recommendations.

If you're auditing client domains before campaigns, or building a compliance dashboard, it might be useful. Free tier is 100 req/day (no card). Paid is £19/month unlimited.

Try it: `curl https://yield-system.fly.dev/v1/domain/yourdomain.com -H "X-API-Key: ys_<key>"`  
Get a free key: https://yield-system.fly.dev

Harry Winter  
Veriflow Labs

---

## Community posts (non-email channels)

### Hacker News — Show HN

**Title:** Show HN: Veriflow Labs – four compliance/data APIs with free tier (sanctions, postcodes, webhooks, email DNS)

I built four small APIs targeting UK compliance and developer tooling use cases, all on a single platform:

1. **Sanctions screening** — batch check names against OFAC SDN, UK HMT OFSI, and EU lists. Delta webhooks when lists change. (£29/mo)
2. **UK postcode enrichment** — lat/lng + LSOA/MSOA + full IMD 2019 deprivation data in one call. (£19/mo)
3. **Webhook queue** — managed retry with idempotency keys, at-least-once delivery, event replay. (£19/mo)
4. **Email DNS score** — composite A–F grade across MX/SPF/DMARC/BIMI/DNSSEC, with fix recommendations. (£19/mo)

Free tier: 100 req/day, no credit card. Sign up at https://yield-system.fly.dev — key issued instantly.

Tech: FastAPI + SQLite on a Fly.io volume. OFAC and HMT lists refresh daily. Happy to answer questions.

---

### Reddit — r/sideprojects / r/webdev / r/devops

Same content as HN but shorter, more casual. Post separately per API to targeted subreddits (r/fintech for sanctions, r/dataisbeautiful for postcodes).

---

### Dev.to / Hashnode article draft

Title: "How I built a sanctions screening API with daily OFAC + HMT refresh for £4/month in hosting"

Cover: architecture (FastAPI → SQLite → Fly.io volume), iterparse streaming for 90MB XML, delta webhook design. Link to the live API at the end. This type of technical deep-dive drives inbound developer signups.

---

## Tracking

Keep a spreadsheet: Company | Name | Email | Segment | Sent date | Reply | Outcome.  
Target 30 outbound contacts in days 1–7. At a 2% conversion rate, that's ~1 paid customer.  
The real funnel is: 30 outreach → 5–8 free signups → 1–2 paid.
