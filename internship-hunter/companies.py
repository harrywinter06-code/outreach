"""
Target company list — curated for realism.

Harry's actual profile: UCL IMB predicted First, Python intermediate,
algorithmic trading project (data pipeline / paper trading), no prior internship,
applying in May 2026 for June–September start. UK citizen.

The question asked before every entry: would a motivated UCL IMB student
with basic Python and a trading project actually get a positive response
to a cold email at this company in May 2026?

Tiers:
  COLD EMAIL  — 20–200 people, founder/technical lead is reachable,
                no formal intern programme, profile matches the work.
                Cold email to the CTO or Head of Data is the right move.

  PORTAL ONLY — 300+ people, or formal recruiting process.
                Cold email won't bypass HR. Apply through their careers page.
                These exist in the list for the job discovery pipeline.

Abroad — visa reality:
  Ireland:   Common Travel Area — UK citizens need no visa at all.
  Canada:    IEC Working Holiday visa (~£150, Harry applies once, valid 2 years).
             Zero burden on the company — Harry arrives like any other candidate.
             Toronto/Montreal AI + fintech scene is strong and less competitive
             than London for cold email at this profile level.
  Australia: Working Holiday visa (subclass 417, ~£330). Same logic as Canada.
             Smaller tech scene — only worth it if a specific company is a strong fit.
  EU (post-Brexit): UK citizens need work permits. Most 50-200 person EU startups
             will not go through the admin for a 3-month intern. Companies 300+
             with real HR departments sometimes will — treat as portal-only and
             check their careers page for explicit intern sponsorship language.
  USA:       J-1 intern visa requires company-side sponsorship infrastructure.
             Summer 2026 US positions mostly filled by May. Not viable for cold
             email this cycle.
  Remote:    Company is distributed; Harry works from the UK. No visa needed.
"""

from tracker import upsert_company

# Format: (name, website, careers_url, sector, size_band, notes)
TARGET_COMPANIES = [

    # ── Data / Analytics / Research Platforms ────────────────────────────────
    # Companies where the core product IS data — strong fit for a data analyst intern.
    # Harry's job would be internal analytics, data pipelines, or product analysis.
    (
        "Causal",
        "causal.app",
        "causal.app/careers",
        "Data/Analytics",
        "50-100",
        "COLD EMAIL. Business modelling and scenario planning tool — a better Excel for financial teams. London, Series B ($30m). ~50 people. Harry's financial modelling background is directly relevant. Founders still accessible.",
    ),
    (
        "Attest",
        "attest.com",
        "attest.com/careers",
        "Data/Research",
        "100-200",
        "COLD EMAIL. Consumer research platform. London, Series C. Data and product analyst roles. Small enough that a cold email to the Head of Data lands. Harry's analytical thinking is a genuine fit.",
    ),
    (
        "Bud Financial",
        "thisisbud.com",
        "thisisbud.com/careers",
        "Data/Fintech",
        "50-100",
        "COLD EMAIL. Financial data enrichment and transaction categorisation for banks. London. Almost every role touches data — strong fit. Small team, founders accessible.",
    ),
    (
        "Signal AI",
        "signal-ai.com",
        "signal-ai.com/careers",
        "Data/NLP",
        "100-200",
        "COLD EMAIL. Media intelligence platform — NLP to track companies, risk signals, and topics. London, Series C. Research analyst and data roles. Harry could contribute to data labelling, analysis pipelines, client reporting.",
    ),
    (
        "Synaptic",
        "synaptic.ai",
        "synaptic.ai/careers",
        "Data/Finance",
        "50-100",
        "COLD EMAIL. Investment intelligence platform — aggregates company data for investors. London. Strong alignment with Harry's trading and finance interest. Small enough that cold email reaches the founder directly.",
    ),
    (
        "Behavox",
        "behavox.com",
        "behavox.com/careers",
        "Data/Compliance",
        "100-200",
        "COLD EMAIL. AI-powered compliance and conduct risk platform for financial institutions. London, Series B. Analyses communication and transaction data. Data analyst / research analyst internship realistic.",
    ),
    (
        "Kaiko",
        "kaiko.com",
        "kaiko.com/careers",
        "Data/Crypto",
        "100-200",
        "COLD EMAIL (London office). Crypto market data and analytics. Paris HQ but London office means no visa issue. Trading project experience is a genuine hook — they serve quant funds and exchanges. Data analyst roles.",
    ),
    (
        "Soda",
        "sodadata.io",
        "sodadata.io/careers",
        "Data Quality",
        "50-100",
        "COLD EMAIL (remote). Data quality and observability SaaS. Remote-first culture. Data engineering / analyst roles. Harry stays in UK, no visa needed. Series A.",
    ),

    # ── Fintech / Insurtech ────────────────────────────────────────────────────
    # Companies where data analysis and operations roles are common.
    # Cold email works at the smaller ones; portal only above ~300 people.
    (
        "Hyperexponential",
        "hyperexponential.com",
        "hyperexponential.com/careers",
        "Insurtech/Data",
        "100-200",
        "COLD EMAIL. Insurance pricing modelling platform. London, Series B. Explicitly quant/data culture — their team is actuaries and data scientists. Strong profile fit for Harry. CTO/Head of Data is reachable.",
    ),
    (
        "Chip",
        "getchip.com",
        "getchip.com/careers",
        "Fintech",
        "50-100",
        "COLD EMAIL. AI savings and investment app. London, Series C. Small team — founder-accessible. Data and product analyst roles. Harry's investing interest is a genuine hook.",
    ),
    (
        "Cleo",
        "meetcleo.com",
        "meetcleo.com/careers",
        "Fintech/AI",
        "100-200",
        "COLD EMAIL. AI financial assistant (chatbot for budgeting and spending). London, Series C. Data / growth analyst roles. ML-driven product — good cold email angle around the data side of an AI consumer app.",
    ),
    (
        "Freetrade",
        "freetrade.io",
        "freetrade.io/careers",
        "Fintech",
        "100-200",
        "COLD EMAIL. Commission-free investing app. London, Series C. Data analyst roles. Harry's trading and investing background is a direct hook here. CTO/Head of Data reachable.",
    ),
    (
        "Griffin",
        "griffin.com",
        "griffin.com/careers",
        "Fintech/BaaS",
        "100-200",
        "COLD EMAIL. Banking-as-a-service API. London, Series B ($24m). Data and compliance analyst roles. Small enough for cold email to work. Interesting infrastructure play in UK fintech.",
    ),
    (
        "Yapily",
        "yapily.com",
        "yapily.com/careers",
        "Open Banking",
        "100-200",
        "COLD EMAIL. Open banking API across 17 European countries. London, Series B. Data-focused team. Analyst and data engineering roles realistic for a motivated student.",
    ),
    (
        "Primer",
        "primer.io",
        "primer.io/careers",
        "Fintech/Payments",
        "100-200",
        "COLD EMAIL. Payment orchestration platform. London, Series B. Python-heavy stack. Data analyst roles — payment routing is fundamentally a data optimisation problem.",
    ),
    (
        "Juro",
        "juro.com",
        "juro.com/careers",
        "Legal AI / Ops",
        "50-100",
        "COLD EMAIL. Contract lifecycle management. London, Series B. Ops analyst and data roles. Small team — founder directly accessible. Harry's analytical thinking suits the product.",
    ),
    (
        "Moneybox",
        "moneyboxapp.com",
        "moneyboxapp.com/careers",
        "Fintech",
        "100-200",
        "COLD EMAIL. Savings and investing app. London, Series D. Product / data analyst roles. Harry's investing angle is a natural hook in the cold email.",
    ),
    (
        "Flagstone",
        "flagstoneim.com",
        "flagstoneim.com/careers",
        "Fintech/Savings",
        "100-200",
        "COLD EMAIL. Cash savings deposit platform — routes savings across 60+ UK banks. London, Series B. Small enough for cold email. Data analyst / ops roles in a financially-focused team.",
    ),
    (
        "iwoca",
        "iwoca.co.uk",
        "iwoca.co.uk/careers/",
        "Fintech/Lending",
        "200-500",
        "COLD EMAIL (borderline). SME lending, ML-driven credit underwriting. London. Getting larger (~300 people) but still accessible. Data analyst and credit analyst roles. Worth a cold email to Head of Data Science.",
    ),
    (
        "Cytora",
        "cytora.com",
        "cytora.com/careers",
        "AI/Insurance",
        "50-100",
        "COLD EMAIL. Digitises commercial insurance risk data using AI. London, Series B. Very data-heavy product. Small team — founder accessible. Data operations analyst internship realistic.",
    ),

    # ── AI Startups with Analyst / Data Ops Needs ─────────────────────────────
    # Companies where Harry's role would be data analysis or operations,
    # not ML research. The AI is their product — Harry helps with the data side.
    (
        "Synthesized",
        "synthesized.io",
        "synthesized.io/careers",
        "AI/Data",
        "50-100",
        "COLD EMAIL. Synthetic data generation for ML and privacy compliance. London. Small team, founders accessible. Data analyst / data engineering intern realistic.",
    ),
    (
        "Greyparrot",
        "greyparrot.ai",
        "greyparrot.ai/careers",
        "AI/Climate",
        "50-100",
        "COLD EMAIL. AI for waste recognition and recycling analytics. London, Series A. Unusual angle — cold email can lean into the climate/data theme. Small team, CTO reachable.",
    ),
    (
        "Phoebe.ai",
        "phoebe.ai",
        "phoebe.ai/careers",
        "AI/HR",
        "<50",
        "COLD EMAIL. AI recruiting platform. London. Tiny team — founders read everything. Any analytical or data role is realistic at this size.",
    ),
    (
        "Cervest",
        "cervest.earth",
        "cervest.earth/careers",
        "AI/Climate",
        "50-100",
        "COLD EMAIL. Climate intelligence and physical risk analytics. London, Series B. Quantitative methodology for climate risk — good fit for analytical profile. Data analyst roles.",
    ),
    (
        "Monolith AI",
        "monolithai.com",
        "monolithai.com/careers",
        "AI/Engineering",
        "50-100",
        "COLD EMAIL. Engineering simulation AI — ML surrogates replacing finite element analysis. London, Series B ($25m). Data engineering roles. Less competitive sector than pure ML.",
    ),
    (
        "Hadean",
        "hadean.com",
        "hadean.com/careers",
        "AI/Simulation",
        "50-100",
        "COLD EMAIL. Distributed computing for large-scale simulation. London. Defence and enterprise clients. Data and engineering analyst roles. Unusual enough that a thoughtful cold email stands out.",
    ),
    (
        "Papercup",
        "papercup.com",
        "papercup.com/careers",
        "AI/Media",
        "50-100",
        "COLD EMAIL. AI dubbing for video content. London, Series B. Data analyst roles on the media/content analytics side. Small team.",
    ),

    # ── BioAI / Healthcare Data ────────────────────────────────────────────────
    # Cambridge-based companies are genuinely accessible for a London student.
    # Data analyst roles here are realistic — it's not ML research, it's data work.
    (
        "Healx",
        "healx.io",
        "healx.io/careers",
        "BioAI",
        "50-100",
        "COLD EMAIL. Rare disease AI. Cambridge (~1 hour from London). Small enough for a cold email to the CTO to land. Tech / data internships available. Unusual sector — stands out in a sea of fintech applications.",
    ),
    (
        "Congenica",
        "congenica.com",
        "congenica.com/careers",
        "BioAI",
        "50-100",
        "COLD EMAIL. Clinical genomics decision support. Cambridge. Interprets genomic variants — data analysis roles. Quantitative rigour required but not ML research. Small team.",
    ),
    (
        "Relation Therapeutics",
        "relationrx.com",
        "relationrx.com/careers",
        "BioAI",
        "50-100",
        "COLD EMAIL. ML for rare disease drug discovery using single-cell genomics. London. Essentially a data science company. Small team, data analyst roles realistic.",
    ),

    # ── Ireland — No Visa Required (Common Travel Area) ───────────────────────
    # UK citizens can work in Ireland without any visa or work permit.
    # Worth including for the right candidate — Dublin is a short flight.
    (
        "Tines",
        "tines.com",
        "tines.com/careers",
        "Security Automation",
        "200-500",
        "COLD EMAIL (Dublin, no visa). Security workflow automation — no-code automation for security teams. Dublin, Series C ($115m). Data and ops analyst roles. UK citizen needs no visa for Ireland. Worth a cold email to Head of Operations.",
    ),
    (
        "Wayflyer",
        "wayflyer.com",
        "wayflyer.com/careers",
        "Fintech/Lending",
        "200-500",
        "COLD EMAIL (Dublin, no visa). Revenue-based financing for e-commerce brands. Dublin, Series B ($150m). Data analyst roles — underwriting and growth analytics. UK citizen needs no visa for Ireland.",
    ),

    # ── Canada — IEC Working Holiday (no company sponsorship needed) ─────────────
    # UK citizens get a 2-year IEC working holiday visa for ~£150.
    # Zero burden on the company — Harry applies like any other candidate.
    # Toronto is the best cold email market: strong AI/fintech, less saturated than London.
    (
        "Ada",
        "ada.cx",
        "ada.cx/careers",
        "AI/SaaS",
        "200-500",
        "COLD EMAIL (Toronto, IEC visa — no sponsorship needed). AI-powered customer service automation. Toronto, Series C ($130m). Data analyst and AI ops roles. Similar profile to Cleo — AI consumer product with data team. Cold email to Head of Data or CTO is viable at this size.",
    ),
    (
        "Float",
        "float.com",
        "float.com/careers",
        "Fintech",
        "50-100",
        "COLD EMAIL (Toronto, IEC visa — no sponsorship needed). Corporate spend management and cards for Canadian businesses. Toronto, Series B. ~80 people. Data analyst roles. Small enough that a cold email reaches the founder. Harry's fintech + data background is a direct fit.",
    ),
    (
        "BenchSci",
        "benchsci.com",
        "benchsci.com/careers",
        "BioAI",
        "200-500",
        "COLD EMAIL (Toronto, IEC visa — no sponsorship needed). AI platform for pre-clinical drug research — helps scientists find validated reagents. Toronto, Series C ($95m). Data and research analyst roles. Harry's EEG/neuro project (if built) is a genuine hook. Cold email to Head of Data Science.",
    ),
    (
        "Cohere",
        "cohere.com",
        "cohere.com/careers",
        "AI/LLM",
        "200-500",
        "COLD EMAIL (Toronto, IEC visa — no sponsorship needed). Enterprise LLM platform. Toronto, Series C ($270m). ~500 people — borderline for cold email but the AI angle justifies the attempt. Data / ML ops analyst roles. Harry's internship hunter (Anthropic API) and EEG project are both relevant hooks.",
    ),

    # ── Remote-Friendly — Harry Stays in the UK ───────────────────────────────
    # Company is distributed; Harry works from the UK. No visa needed.
    (
        "Dune Analytics",
        "dune.com",
        "dune.com/careers",
        "Data/Crypto",
        "50-100",
        "COLD EMAIL (remote). On-chain crypto data analytics platform. Remote-first. SQL and data analysis focused. Harry's trading / data pipeline experience is relevant to the crypto data space.",
    ),
    (
        "Hex",
        "hex.tech",
        "hex.tech/careers",
        "Data",
        "50-100",
        "COLD EMAIL (remote). Collaborative data notebook (Python + SQL). Remote-first, US-based but hires globally. Series B. Internal data / product analyst role realistic. No visa needed working remotely from UK.",
    ),
    (
        "Codat",
        "codat.io",
        "codat.io/careers",
        "Fintech/Data",
        "100-200",
        "COLD EMAIL (London/remote). Financial data APIs for accounting and banking software. London HQ but remote-friendly. Series C. Data analyst and ops roles. Strong fit for Harry's finance + data background.",
    ),

    # ── UK Commodity & Market Data ───────────────────────────────────────────
    # Harry's trading pipeline background is a direct hook here.
    (
        "Vortexa",
        "vortexa.com",
        "vortexa.com/careers",
        "Data/Commodities",
        "100-200",
        "COLD EMAIL. Real-time energy cargo and commodity flow analytics — serves hedge funds, refiners, and energy traders. London, Series B+. ~200 people. Harry's algorithmic trading pipeline is a direct hook: this is the data infrastructure for the kind of strategies his system models. Strong fit for data analyst internship.",
    ),
    (
        "Beacon",
        "beacon.io",
        "beacon.io/careers",
        "Data/Logistics",
        "100-200",
        "COLD EMAIL. Freight market intelligence — real-time rates, lane data, and carrier analytics. London, Series C ($80m total). ~120 people. Data analyst roles on the market intelligence side. Harry's data pipeline experience is relevant.",
    ),

    # ── UK ESG / Climate Tech ─────────────────────────────────────────────────
    (
        "Sylvera",
        "sylvera.com",
        "sylvera.com/careers",
        "Data/ESG",
        "50-100",
        "COLD EMAIL. Independent carbon credit ratings and analytics — the Moody's of carbon markets. London, Series B. ~100 people. Produces rigorous analytical output on carbon project quality. Data analyst and research analyst roles. Unusual sector stands out from fintech-heavy applications.",
    ),
    (
        "Altruistiq",
        "altruistiq.com",
        "altruistiq.com/careers",
        "Data/Sustainability",
        "50-100",
        "COLD EMAIL. Supply chain carbon data and scope 3 emissions tracking. London, Series B. ~80 people. Data-heavy product — quantifying emissions across complex global supply chains. Data analyst roles. Small team, founders accessible.",
    ),

    # ── UK Open Banking / Additional Fintech ─────────────────────────────────
    (
        "Moneyhub",
        "moneyhub.com",
        "moneyhub.com/careers",
        "Data/Open Banking",
        "50-100",
        "COLD EMAIL. Open banking data and analytics platform for banks, insurers, and pension providers. London, Series B (Lloyds strategic investor). ~100 people. Strong data culture — their product IS the analytics layer. Data analyst and product analyst roles. Harry's fintech and data pipeline background is a direct fit.",
    ),
    (
        "Volt",
        "volt.io",
        "volt.io/careers",
        "Fintech/Payments",
        "100-200",
        "COLD EMAIL. Real-time open banking payment network across 30+ markets. London, Series B ($60m). ~150 people. Payments analytics and data analyst roles. Growing fast. CTO/Head of Data reachable at this size.",
    ),
    (
        "Hokodo",
        "hokodo.com",
        "hokodo.com/careers",
        "Fintech/Credit",
        "50-100",
        "COLD EMAIL. B2B trade credit and BNPL for European businesses — uses transaction data and ML for instant credit decisions. London, Series A. ~100 people. Data analyst roles in credit underwriting and risk analytics. Small team, CTO accessible.",
    ),
    (
        "Uncapped",
        "weareuncapped.com",
        "weareuncapped.com/careers",
        "Fintech",
        "50-100",
        "COLD EMAIL. Revenue-based financing for startups — analyses recurring revenue data to make funding decisions. London, Series B. ~60 people. Data analyst roles in underwriting and portfolio analytics. Small team, founders accessible.",
    ),
    (
        "Weavr",
        "weavr.io",
        "weavr.io/careers",
        "Fintech/Embedded",
        "50-100",
        "COLD EMAIL. Embedded finance APIs — lets software companies add financial products (cards, accounts) to their platforms. London, Series B. ~70 people. Data and ops analyst roles. Interesting infrastructure play, small team.",
    ),

    # ── UK Regtech / Compliance Data ──────────────────────────────────────────
    (
        "Napier AI",
        "napier.ai",
        "napier.ai/careers",
        "Regtech/Compliance",
        "100-200",
        "COLD EMAIL. AI-powered AML and financial crime compliance platform. London, Series B. ~150 people. Data analyst roles in transaction monitoring, typology analysis, compliance reporting. Strong analytical culture. CTO/Head of Data reachable.",
    ),
    (
        "ComplyAdvantage",
        "complyadvantage.com",
        "complyadvantage.com/careers",
        "Data/Compliance",
        "100-200",
        "COLD EMAIL (borderline). Financial crime intelligence data — AML screening, sanctions, adverse media for banks and fintechs. London, Series C. ~200 people. Data analyst and research analyst roles. Getting large but Head of Data still accessible via cold email.",
    ),

    # ── UK PropTech Data ──────────────────────────────────────────────────────
    (
        "Landtech",
        "land.tech",
        "land.tech/careers",
        "Data/PropTech",
        "50-100",
        "COLD EMAIL. Land and planning data analytics for property developers — site identification, planning constraints, ownership. London, Series B. ~70 people. Very data-focused product. Data analyst internship realistic. Small team, founder accessible.",
    ),
    (
        "Orbital Witness",
        "orbitalwitness.com",
        "orbitalwitness.com/careers",
        "AI/PropTech",
        "50-100",
        "COLD EMAIL. AI for property due diligence — automates analysis of land registry title documents. London, Series A (£7.5m, 2023). ~50 people. Document AI and property data. Unusual sector, strong analytical fit. CTO directly reachable at this size.",
    ),
    (
        "Sprift",
        "sprift.com",
        "sprift.com/careers",
        "Data/PropTech",
        "50-100",
        "COLD EMAIL. Property data intelligence — aggregates 30m+ property records, EPC ratings, planning data, sold prices. London, Series A. ~50 people. Core product is data analytics. Analyst internship directly relevant to the work.",
    ),

    # ── UK Analytics Platforms ────────────────────────────────────────────────
    (
        "Permutive",
        "permutive.com",
        "permutive.com/careers",
        "Data/AdTech",
        "100-200",
        "COLD EMAIL. Publisher audience data platform — privacy-first alternative to third-party cookies, used by major publishers. London, Series C. ~150 people. Data analyst roles in audience segmentation and publisher analytics. Python-heavy data culture.",
    ),
    (
        "Ometria",
        "ometria.com",
        "ometria.com/careers",
        "Data/Retail",
        "100-200",
        "COLD EMAIL. Retail customer data and analytics platform — CRM and marketing analytics for retailers. London, Series C ($71m). ~120 people. Data analyst roles in customer analytics, segmentation, campaign performance. Good Python/SQL data culture.",
    ),
    (
        "Pulsar",
        "pulsarplatform.com",
        "pulsarplatform.com/careers",
        "Data/Media",
        "100-200",
        "COLD EMAIL. Social audience intelligence — helps brands understand online communities and cultural trends through data. London. ~200 people. Research analyst and data analyst roles. Analytical output is literally their product. Head of Data worth a cold email.",
    ),
    (
        "Orgvue",
        "orgvue.com",
        "orgvue.com/careers",
        "Data/HR Analytics",
        "100-200",
        "COLD EMAIL. Organisational design and workforce analytics — models headcount, structure, and cost scenarios for enterprises. London, Series C. ~120 people. Data analyst roles core to the product. Analytical culture by design.",
    ),

    # ── Ireland Additional (No Visa — Common Travel Area) ─────────────────────
    (
        "Conjura",
        "conjura.com",
        "conjura.com/careers",
        "Data/Ecommerce",
        "50-100",
        "COLD EMAIL (Dublin, no visa). Ecommerce performance analytics — unifies Shopify, Amazon, Meta, and other channels into one analytics layer. Dublin, Series B. ~60 people. UK citizen needs no visa for Ireland. Data analyst roles core to the product. Founders accessible.",
    ),
    (
        "Corlytics",
        "corlytics.com",
        "corlytics.com/careers",
        "Data/Regtech",
        "100-200",
        "COLD EMAIL (Dublin/London, no visa). Regulatory intelligence — AI platform tracking and classifying regulatory change across 40+ jurisdictions. Dublin HQ, London office. Series B (backed by Verdane PE). ~150 people. UK citizen needs no visa for Ireland. Data analyst and research analyst roles.",
    ),

    # ── Canada Additional (IEC Working Holiday — no company sponsorship) ───────
    (
        "Klue",
        "klue.com",
        "klue.com/careers",
        "Data/Intelligence",
        "100-200",
        "COLD EMAIL (Vancouver, IEC visa — no sponsorship needed). Competitive intelligence platform — aggregates market signals and competitor data for sales and product teams. Vancouver, Series C. ~150 people. Data analyst and market research roles. Harry's data pipeline experience maps directly to what they build. IEC visa makes Harry an ordinary candidate.",
    ),
    (
        "Procurify",
        "procurify.com",
        "procurify.com/careers",
        "Data/Finance",
        "100-200",
        "COLD EMAIL (Vancouver, IEC visa — no sponsorship needed). Spend management and procurement analytics. Vancouver, Series C ($50m, managing $30B+ in spend). ~170 people. Data analyst and finance analytics roles. IEC visa.",
    ),
    (
        "Fundthrough",
        "fundthrough.com",
        "fundthrough.com/careers",
        "Fintech",
        "50-100",
        "COLD EMAIL (Toronto, IEC visa — no sponsorship needed). Invoice financing — uses invoice data and ML to provide same-day capital to SMEs. Toronto, Series B ($25m, 2025). ~60 people. Data analyst roles in credit and underwriting analytics. Harry's fintech and data pipeline background is a direct fit. IEC visa.",
    ),
    (
        "Properly",
        "properly.ca",
        "properly.ca/careers",
        "Data/PropTech",
        "50-100",
        "COLD EMAIL (Toronto, IEC visa — no sponsorship needed). Data-driven real estate — automated valuation models and analytics to streamline home buying. Toronto, Series B ($35m). ~90 people. Data analyst roles. IEC visa.",
    ),

    # ── Portal Only — Apply via Careers Page ──────────────────────────────────
    # These companies have formal HR processes.
    # Cold email to a technical lead won't move the needle.
    # Worth applying through the portal if relevant roles appear via job discovery.
    (
        "Monzo",
        "monzo.com",
        "monzo.com/careers",
        "Neobank",
        "1k+",
        "PORTAL ONLY. Data analyst roles appear regularly. Summer 2026 intern programme likely closed but worth watching for late openings.",
    ),
    (
        "Revolut",
        "revolut.com",
        "revolut.com/careers",
        "Neobank",
        "1k+",
        "PORTAL ONLY. Data analyst and product analyst roles. High volume hiring but formal process. Apply via portal.",
    ),
    (
        "Palantir",
        "palantir.com",
        "palantir.com/careers",
        "Data",
        "1k+",
        "PORTAL ONLY. Forward Deployed Engineer programme for analytically strong graduates. Apply via portal — cold email bypasses the structured FDE process.",
    ),
    (
        "Tractable",
        "tractable.ai",
        "tractable.ai/careers",
        "AI/Insurance",
        "200-500",
        "PORTAL ONLY. AI for accident damage assessment. London, Series E. Too large now for cold email to work reliably. Check careers page.",
    ),
    (
        "Featurespace",
        "featurespace.com",
        "featurespace.com/careers",
        "Fintech/ML",
        "200-500",
        "PORTAL ONLY. Adaptive behavioural analytics for fraud. Cambridge/London. Formal graduate recruitment process. Apply via portal.",
    ),
    (
        "Quantexa",
        "quantexa.com",
        "quantexa.com/careers",
        "AI/Data",
        "500-1k",
        "PORTAL ONLY. Context intelligence for financial crime. Series E, London. Too large for cold email. Data analyst roles appear on their board.",
    ),
    (
        "Multiverse",
        "multiverse.io",
        "multiverse.io/careers",
        "EdTech",
        "500-1k",
        "PORTAL ONLY. Apprenticeship platform. London, Series D. Data analyst roles in their analytics team. Apply via portal.",
    ),
    (
        "GoCardless",
        "gocardless.com",
        "gocardless.com/careers",
        "Fintech/Payments",
        "500-1k",
        "PORTAL ONLY. Bank-to-bank payments. London. Formal hiring process. Data engineering and analytics roles via portal.",
    ),

    # ── EU — Portal Only (require UK work permit, but have HR to handle it) ──────
    # Post-Brexit UK citizens need a work permit for EU countries.
    # These companies are large enough to have sponsorship infrastructure.
    # Check careers page explicitly for intern visa sponsorship language before applying.
    (
        "Dataiku",
        "dataiku.com",
        "dataiku.com/careers",
        "Data/AI",
        "500-1k",
        "PORTAL ONLY (Paris/London, EU visa required for Paris). Data science platform — enterprise MLOps and analytics. Paris HQ, London office. Series F ($400m). Has established intern programme. Check if London office roles avoid the visa issue entirely — prefer applying to London-based openings.",
    ),
    (
        "Mollie",
        "mollie.com",
        "mollie.com/careers",
        "Fintech/Payments",
        "500-1k",
        "PORTAL ONLY (Amsterdam, EU visa required). European payments API — Stripe equivalent for European SMEs. Amsterdam, Series B ($800m). Data analyst roles. Large enough to sponsor UK work permit but check careers page explicitly for sponsorship language. Strong fintech data culture.",
    ),
    (
        "Personio",
        "personio.com",
        "personio.com/careers",
        "HR/SaaS",
        "1k+",
        "PORTAL ONLY (Munich/London, prefer London opening). HR software for European SMEs. Munich HQ but London office growing. Series E. Data analyst roles. Apply to London-based roles to avoid visa question entirely.",
    ),
]


def seed_companies():
    """Load target companies into the DB. Skips companies already present."""
    count = 0
    for row in TARGET_COMPANIES:
        name, website, careers_url, sector, size, notes = row
        upsert_company(
            name=name,
            website=website,
            careers_url=careers_url,
            sector=sector,
            size=size,
            notes=notes,
        )
        count += 1
    return count


def get_by_sector(sector_keyword: str) -> list[tuple]:
    return [c for c in TARGET_COMPANIES if sector_keyword.lower() in c[3].lower()]


if __name__ == "__main__":
    n = seed_companies()
    print(f"Seeded {n} target companies into database.")
