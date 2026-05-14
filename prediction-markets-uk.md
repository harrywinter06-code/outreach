# UK Prediction Market Income — Research Findings
*Rounds 1–5 | Last updated: May 2026*

---

## Executive Summary

A UK resident can legally trade prediction markets and earn systematic income using the Betfair Exchange. The cleanest viable path is a Metaculus-calibrated mispricing bot on Betfair, targeting niche political markets (£10k–£100k matched volume) where algorithmic competition is thin. Total entry cost: £299 one-time + ~£45/month operating. Individual gambling winnings are confirmed tax-free under UK law as of the November 2025 HMRC consultation response.

Polymarket is geoblocked and legally off-limits. Kalshi is US-only. Every other route has material friction (application process, thin liquidity, or unconfirmed retail launch).

---

## 1. Legal Status — UK Landscape

### Confirmed Legal (UK)

| Platform | Regulator | Notes |
|---|---|---|
| Betfair Exchange | UKGC | Primary venue. Deep liquidity. API costs £299. |
| Smarkets | UKGC | 2% flat commission. API requires application + £150. |
| Matchbook Predictions | UKGC | Launched Jan 2026 (B2B rollout; retail not confirmed live). |
| Betdaq | UKGC | £250 API one-time. Thin liquidity outside horse racing. |

### Confirmed Illegal / Blocked (UK)

| Platform | Reason |
|---|---|
| Polymarket | Explicitly geoblocked. FCA binary options ban 2019. UK in restricted country list. VPN enforcement intensified late 2025; Dutch KSA fined Polymarket €420k/week Feb 2026. UK payment methods detected at deposit stage. |
| Kalshi | US-only (CFTC-regulated DCM). Requires US SSN. No UK expansion timeline. |
| IBKR/ForecastEx | UK clients blocked. "International: Not available." Confirmed. |

### Tax Treatment (confirmed November 2025)

Individual gambling winnings — including from automated bots — are **tax-free** in the UK. The April 2025 HMRC consultation was exclusively about *operator* duty structure. The November 2025 government response explicitly did not introduce any bettor-level tax and confirmed no such change is planned. Even if the bot is your primary income source, HMRC's position is that gambling is not a trade.

---

## 2. Platform Entry Costs — Verified

### Betfair

| Item | Cost | Notes |
|---|---|---|
| Personal Live API Key | **£299 one-time** (non-refundable) | Required for real-time order execution. Delayed key (free) cannot place orders. |
| Commercial Vendor License | **£499 additional** | Only needed if selling software to third parties. |
| Commission — My Betfair Rewards Basic | **2% on net profit** | Opt in instantly: Account > My Betfair Rewards > Basic. Zero volume requirement. |
| Expert Fee — Tier 1 | **0%** | 52-week gross profit below £25,000 |
| Expert Fee — Tier 2 | **20%** | 52-week gross profit £25,000–£100,000 |
| Expert Fee — Tier 3 | **40%** | 52-week gross profit above £100,000 |
| Expert Fee conditions | Both must be true | (1) 52-week gross in threshold AND (2) lifetime gross positive |
| 1,000-bet/hour excess | **£0.01/bet** on excess | Only applies above 1,000 bets in a single hour; offset by commission generated |

Expert Fee notes:
- Commission paid acts as a credit buffer — more commission = larger Expert Fee shield.
- £25k/year threshold = £2,083/month gross profit. A bot targeting £500–1,000/month operates below threshold for years.
- Betfair actively monitors linked accounts. Never attempt to split across multiple accounts to avoid the fee.

### Smarkets

| Item | Cost |
|---|---|
| API Access | **£150 upfront** + application required |
| Commission | **2% flat** on net profit |
| Application | Via form at docs.smarkets.com. Prioritises market makers. Apply stating passive limit-order strategy. |
| Approval timeline | Not publicly documented. Email api@smarkets.com. |

Note: The £150 figure is user-confirmed. All public sources (bettingdev.com, caanberry.com) say "free" — these are outdated. The Smarkets Help Centre API article is login-gated and not publicly accessible.

### Betdaq

| Item | Cost |
|---|---|
| API Access | **£250 one-time** (confirmed from betdaq.zendesk.com) |
| Commission (default) | **5%** |
| Commission (minimum) | **2%** when Take% ≤ 50% over rolling 7 weeks |
| New customer rate | **3% fixed** for first 7 weeks |
| Promotional rates | **Not available** to API customers |

Betdaq commission scale (from api.betdaq.com — primary source):

| Take% (rolling 7 weeks) | Commission |
|---|---|
| 94–100% | 5.0% |
| 87–93% | 4.5% |
| 80–86% | 4.0% |
| 71–79% | 3.5% |
| 61–70% | 3.0% |
| 51–60% | 2.5% |
| 0–50% | **2.0%** |

Reaching 2% requires ≥50% Make bets (passive limit orders). A market-making bot achieves this structurally.

### Matchbook

| Item | Cost |
|---|---|
| Standard API tier | **Free** (all registered customers) |
| GET requests above free tier | **£100 per 1M requests** |
| WRITE requests (order placement) | **Free** at reasonable frequency |
| Authentication | Session token from login endpoint; no separate purchase |

Matchbook Predictions status (May 2026): B2B rollout only. Retail launch not confirmed. easyBet is the first white-label operator. No confirmed retail matched volume data. Contact b2b@matchbook.com to monitor launch status.

### Monthly Operating Costs

| Item | Cost |
|---|---|
| VPS — London, Contabo Linux | £9/month |
| VPS — ScalaCube Windows (Betfair-specialist) | £30/month |
| Claude API (with prompt caching 90% off + batch API 50% off) | £25–65/month |
| Metaculus data | £0 (free REST API, no authentication) |
| betfairlightweight + Flumine | £0 (open source, MIT) |
| PMXT | £0 (open source) |
| rozzac90/matchbook Python wrapper | £0 (open source) |

**Cheapest legal UK stack**: Matchbook (£0 entry, free API) + Metaculus + Claude API. Monthly burn: £34–74. Risk: retail liquidity not yet confirmed.

**Recommended stack**: Betfair (£299 one-time) + Metaculus + Flumine + Claude API. Monthly burn: £34–74 + 2% commission on profits.

---

## 3. Betfair Predicts — The Critical 2026 Development

Flutter/Betfair launched "Betfair Predicts" in beta in April 2026. This is a **Yes/No prediction market interface built on top of the existing Betfair Exchange**, not a separate platform.

Key facts:
- **Same order book** as the existing Exchange — no separate liquidity pool
- **Same API**: the £299 Personal Live Key gives access to all Betfair Predicts markets
- **Yes/No format**: customers select Yes or No, stake, and trade peer-to-peer
- **Categories**: sports, politics, entertainment (examples: "Will Taylor Swift be most played Spotify artist in 2026?")
- **Status**: invite-only beta (May 2026). Full launch timeline: not announced. Flutter has signalled UK is the test market before US expansion — full launch likely H2 2026.
- **Commission**: same as standard Exchange (2% via My Betfair Rewards Basic)

**Strategic implication**: Betfair Predicts is the UK's legal Polymarket equivalent, backed by Betfair's deep exchange liquidity. Any bot built on the standard Betfair Exchange API can trade Betfair Predicts markets without modification. To get beta access: check betfair.com/betfair-predicts for an opt-in form on an existing account.

---

## 4. Strategy Rankings (Evidence-Based)

### Tier 1 — Build Now

**Metaculus/Betfair Mispricing Bot**

Signal: Metaculus community prediction (free API, no auth, Brier score 0.111 — best documented calibration of any public platform). Strong calibration for questions resolving within 90 days; poor beyond 1 year.

Edge: Betfair politics markets are priced by traders who are not calibrated forecasters. Metaculus community medians are generated by incentivised, scored participants who update on new information. The divergence between these two pricing mechanisms creates exploitable mispricings.

Target markets: UK politics, non-election events (by-elections, policy outcomes, council results). Total matched volume £10k–£100k. Algorithmic competition is thin in these markets precisely because they are too small for institutional bots but large enough to fill reasonably sized positions.

Evidence: Metaculus Brier 0.111 (predictionmarketsreviews.com 2026 review). Betfair politics liquidity confirmed at £180M in 2024 UK general election — deep enough that niche markets represent a meaningful fraction.

Architecture:
```
Metaculus API (free, no auth)
    GET /api2/questions/?status=open&forecast_type=binary
    Filter: close_time < 90 days from today
    ↓
Claude API: fuzzy-match Metaculus question text to Betfair market name
    (prompt cache: system context cached, only market title changes per call)
    ↓
betfairlightweight: fetch current implied probability
    implied_p = (1 / best_back_price) × (1 - 0.02)  # adjust for 2% commission
    ↓
Mispricing filter: |metaculus_p - implied_p| > 0.04
    (4% minimum edge covers 2% commission + slippage buffer)
    ↓
Kelly sizing: stake = (edge / (1 - implied_p)) × 0.25 × bankroll
    Cap: 5% of bankroll per market
    ↓
Flumine: place limit order (back if metaculus_p > implied_p, lay if reverse)
    event_type_ids=["2378961"]  # Politics
    ↓
Resolution monitor: log actual vs predicted, update fuzzy-match accuracy weekly
```

**Betfair Predicts Market Making**

When Betfair Predicts reaches full retail launch (estimated H2 2026): entertainment/culture markets will have low competition, wide spreads, and thin initial liquidity. Market-making bots posting passive limit orders on both sides earn the spread repeatedly. No predictive signal needed — pure liquidity provision.

Advantage over Betfair Exchange sports: entertainment markets are new, have no established bot ecosystem, and Betfair's own LP market-making framework (Flumine) handles passive order management natively.

---

### Tier 2 — Apply Now, Build When Approved

**Smarkets Market-Making**

Apply immediately at docs.smarkets.com. Frame the application as: passive limit order market-making strategy, 100% Make bets. Smarkets prioritises market makers in the approval queue.

PMXT (pmxt-dev/pmxt, 622 stars) added Smarkets Python exchange classes on April 8, 2026. The `create_order()` method is listed as supported but has no publicly documented live fill confirmation. Test with small capital before full deployment. Fallback: direct Smarkets REST API at api.smarkets.com.

```python
from pmxt import Smarkets

smk = Smarkets(api_key="...")
markets = smk.fetch_markets()
order = smk.create_order(
    outcome=market.yes,
    side="buy",
    type="limit",
    price=0.55,
    amount=100
)
# Verify order_id is returned — silent None = order not placed
assert order.id is not None, "Smarkets order not confirmed"
```

---

### Tier 3 — Monitor, Do Not Build Yet

**Matchbook Predictions**

First-mover opportunity once retail liquidity appears. Zero entry cost. Zero bot competition. But no confirmed retail depth as of May 2026. Monitor sbcnews.co.uk and b2b.matchbook.com for launch announcement.

**Betdaq Political Markets**

£250 entry, 5% default commission (requires maker-heavy discipline to reach 2%). Thin liquidity outside horse racing. Not worth building toward unless specific political market depth appears.

---

### Confirmed Dead Ends

| Strategy | Reason |
|---|---|
| Cross-exchange arb (Betfair ↔ Smarkets) | 10% fill rate at target price. 4% combined commission floor. Not profitable. |
| NegRisk arb on Polymarket | Illegal (UK geoblocked). Do not VPN. |
| LP market-making on Polymarket | Same — illegal. |
| Near-resolution bonds on Polymarket | Same — illegal. |
| Betfair Beacon trading | Creator (BowTiedBettor) explicitly states "don't believe this will be a money making machine." |
| GoodJudgment Open as calibration signal | No free API or data endpoint. Not accessible programmatically. |
| Manifold Markets | Play-money only since Feb 2025. Zero real-money signal value. |
| Metaforecast | Inactive. Page states "We aren't currently maintaining Metaforecast." |
| warproxxx/poly-maker | Creator explicitly states "not profitable in today's market, will lose money." |
| 0xalberto/polymarket-arbitrage-bot | No code. Telegram sales pitch. |
| Polymarket/agents | Archived May 11, 2026. |
| IBKR/ForecastEx | UK clients blocked. |

---

## 5. Open-Source Stack — Confirmed Working (2026)

| Library | Use | Status |
|---|---|---|
| [betfairlightweight](https://github.com/liampauling/betfairlightweight) | Betfair API wrapper (Python) | Updated March 16, 2026. 486 stars. |
| [Flumine](https://github.com/betcode-org/flumine) | Betfair trading framework | Updated April 14, 2026. Python 3.9–3.14. |
| [PMXT](https://github.com/pmxt-dev/pmxt) | Unified prediction market API (Smarkets, Kalshi, Polymarket, 10+ others) | v2.41.0 released May 13, 2026. 622 stars. Smarkets classes exposed April 8, 2026. |
| [rozzac90/matchbook](https://github.com/rozzac90/matchbook) | Matchbook Exchange Python wrapper | PyPI installable. 17 stars. |
| [guberm/polymarket-bot](https://github.com/guberm/polymarket-bot) | Claude ensemble bot (Polymarket only) | Architecture reference only — Polymarket is illegal for UK users. |

**Flumine minimal setup** (confirmed working pattern):
```python
import betfairlightweight
from flumine import Flumine, BaseStrategy, clients
from betfairlightweight.filters import streaming_market_filter

trading = betfairlightweight.APIClient("username")
client = clients.BetfairClient(trading, paper_trade=True)  # Paper trade first
framework = Flumine(client=client)

class MispricingStrategy(BaseStrategy):
    def check_market_book(self, market, market_book):
        return market_book.status != "CLOSED"

    def process_market_book(self, market, market_book):
        pass  # Implement signal logic here

strategy = MispricingStrategy(
    market_filter=streaming_market_filter(
        event_type_ids=["2378961"],  # Politics
        country_codes=["GB"],
        market_types=["WINNER"]
    )
)
framework.add_strategy(strategy)
framework.run()
```

**Metaculus free API** (no auth required):
```python
import requests

r = requests.get(
    "https://www.metaculus.com/api2/questions/",
    params={
        "status": "open",
        "forecast_type": "binary",
        "close_time__lt": "2026-08-14",  # 90 days from today
    }
)
questions = r.json()["results"]
# Each question has: community_prediction, resolution_criteria, close_time, title
```

**ElectionBettingOdds cross-platform signal** (free, no auth):
Aggregates live odds from Betfair, Smarkets, PredictIt, Polymarket, Kalshi. Converts to probability: `((1/Bid + 1/Ask) / 2)`. Scrape as a free secondary validation signal alongside Metaculus.

---

## 6. Red-Team Risk Register

| Risk | Severity | Status | Mitigation |
|---|---|---|---|
| HMRC taxes bot winnings | High | **False alarm** — confirmed safe. Nov 2025 government response: no bettor taxation, no change planned. | None needed. |
| Betfair Expert Fee destroys profit at scale | High | **Real but manageable**. Only triggers above £25k/year gross profit. | Monitor rolling 52-week P&L in Betfair dashboard. Stay below £2,083/month gross. Commission credit buffers threshold. |
| Metaculus calibration poor for target markets | Medium | **Partially confirmed**. Brier 0.111 (best public platform). Degrades for 1yr+ horizons. | Filter to markets resolving within 90 days only. |
| Matchbook Predictions has no retail liquidity | Medium | **Confirmed risk**. B2B rollout only as of May 2026. | Do not build for Matchbook yet. Monitor for retail launch. |
| PMXT Smarkets order placement silently fails | Medium | **Unconfirmed**. Classes exposed April 8, 2026 but no live fill confirmation found. | Paper-trade 48 hours, verify every `create_order()` returns a non-None order ID before going live. |
| Betfair bans bot account | Low | **Manageable**. Exchange earns commission from all sides — no incentive to ban profitable traders. Restriction only for market manipulation. | Place genuine limit orders. Do not spoof or layer. Stay under 1,000 bets/hour to avoid excess charge. |
| Expert Fee evasion via multi-account | High | **Do not attempt**. Betfair actively detects linked accounts and applies fee as single customer. | Single account only. |
| Smarkets application rejected | Medium | **Real risk**. No timeline or guarantee. | Apply now. Build on Betfair in parallel. When/if approved, add Smarkets via PMXT without architectural changes. |

---

## 7. Calibration Sources — Ranked

| Source | Quality | Access | Horizon |
|---|---|---|---|
| Metaculus community prediction | Best public platform (Brier 0.111) | Free REST API, no auth | Best for <90 days |
| ElectionBettingOdds | Multi-platform consensus | Free scrape | Real-time |
| GoodJudgment Open | Superforecasters — best human calibration | No free API | N/A for automation |
| Manifold Markets | Play-money only since Feb 2025 | Free API | Not useful for real signals |

---

## 8. What to Do, In Order

1. **Today**: Register existing Betfair account, opt in to My Betfair Rewards Basic (2% commission). Check betfair.com/betfair-predicts for Betfair Predicts beta opt-in.

2. **This week**: Purchase Betfair Personal Live API Key (£299). Install betfairlightweight + Flumine. Run the paper-trade strategy against Betfair politics markets using Metaculus as signal. Log edge accuracy.

3. **Parallel**: Submit Smarkets API application. State passive limit-order market-making strategy. Email api@smarkets.com with the same framing.

4. **After 4 weeks of paper trading**: Assess edge accuracy from resolution log. If Metaculus-vs-Betfair divergences resolve in your favour >55% of the time (net of 2% commission): go live with small capital (£500–1,000 bankroll, 5% max per market Kelly cap).

5. **When Smarkets approves**: Add Smarkets as a second venue via PMXT. Test create_order() with £10 test orders, verify order IDs are returned before scaling.

6. **When Betfair Predicts goes full retail (est. H2 2026)**: Extend the same architecture to entertainment/culture markets. Adjust event_type_ids to include the Betfair Predicts market type once documented.

7. **When Matchbook confirms retail liquidity**: £0 entry cost. First-mover opportunity. Add as third venue.

---

## 9. Unresolved — Cannot Be Confirmed from Public Sources

| Item | Status |
|---|---|
| Smarkets £150 fee — primary source | Help centre login-gated. User-confirmed correct. Cannot independently verify from public page. |
| Smarkets approval timeline | Not documented anywhere public. |
| Matchbook Predictions retail liquidity | Platform in rollout. No confirmed retail matched volume. |
| Betfair Advanced/Pro historical data pricing | "Contact us" only. No public price listed. |
| PMXT Smarkets live fill confirmation | Listed as supported since April 8, 2026. No independent test result found. |
| Betfair Predicts full launch date | Beta since April 2026. Flutter CEO signalled H2 2026 is the target. Unconfirmed. |
| Metaculus vs Betfair edge — empirical size | No published study measuring divergence magnitude on matched markets. Requires building and running the bot to measure. |
