# internship-hunter

Automated internship application pipeline for the UK summer 2026 market. Discovers relevant roles across five sources, generates tailored cover letters and cold outreach using Claude, manages an email queue with Hunter.io address lookup, and tracks the entire pipeline through a Streamlit dashboard backed by SQLite.

## Architecture

```
discover → filter → generate → review → send → track
```

**Discovery** polls Remotive (remote jobs API), Greenhouse and Lever ATS public boards (~40 UK/global company slugs), Reed.co.uk, and six funding news RSS feeds (Sifted, TechCrunch UK/CA/EU, BetaKit, EU Startups). Funding news is routed through Claude Haiku for structured extraction — newly funded startups are added as cold outreach targets automatically.

**Generate** uses Claude Sonnet with prompt caching on the candidate profile. Cover letters, cold emails, LinkedIn DMs, and three-stage follow-up sequences are all generated from a single cached system prompt — subsequent generations in the same session cost ~10% of the first.

**Track** stores everything in a local SQLite database: jobs (source, location, salary, description), applications, email queue (pending → approved → sent), and a company table with UCL alumni flags that trigger a different opening line in generated outreach.

**Send** uses Gmail SMTP with a 90-second inter-email delay and a 20/day hard limit to avoid spam flags.

## Tech stack

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.32-FF4B4B?logo=streamlit&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![Anthropic](https://img.shields.io/badge/Anthropic-Claude_Sonnet-D97706)

| Layer | Tools |
|-------|-------|
| LLM | Claude Sonnet 4.6 (cover letters, cold emails), Claude Haiku (funding lead extraction) |
| Discovery | Remotive API · Greenhouse/Lever public ATS APIs · Reed.co.uk API · RSS via BeautifulSoup |
| Email lookup | Hunter.io domain search + pattern inference |
| Frontend | Streamlit — six-tab dashboard |
| Storage | SQLite via `sqlite3` (no ORM) |
| HTTP | `requests`, `curl_cffi` (TLS fingerprint spoofing for feed fetching) |

## Setup

```bash
git clone https://github.com/harrywinter06-code/internship-hunter
cd internship-hunter
pip install -r requirements.txt
cp .env.example .env
# edit .env with your keys
```

### API keys

| Variable | Where to get | Cost |
|----------|-------------|------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | ~$0.01/cover letter with caching |
| `HUNTER_API_KEY` | [hunter.io](https://hunter.io) | Free: 25 searches/month |
| `REED_API_KEY` | [reed.co.uk/developers](https://www.reed.co.uk/developers/jobseeker) | Free |
| `GMAIL_ADDRESS` | Your Gmail address | — |
| `GMAIL_APP_PASSWORD` | Google Account → Security → App Passwords | — |

Hunter.io and Reed are optional — the system degrades gracefully if those keys are absent.

## Usage

```bash
python main.py dashboard    # Streamlit dashboard (default)
python main.py discover     # Run job discovery from CLI
python main.py generate     # Interactive cover letter generator
python main.py stats        # Print application stats
python main.py seed         # Load target company list into DB
```

## Project structure

```
internship-hunter/
├── discover.py      # Job discovery: Remotive, ATS boards, Reed, funding RSS feeds
├── generate.py      # Claude generation: cover letters, cold emails, follow-ups, LinkedIn DMs
├── dashboard.py     # Streamlit dashboard (Email Queue, Jobs, Applications, Generate, Companies, Stats)
├── tracker.py       # SQLite R/W: jobs, applications, email queue, companies
├── research.py      # Batch company research: Hunter.io + scraping + Claude
├── emailfinder.py   # Email address lookup and domain pattern inference
├── sender.py        # Gmail SMTP batch sender with rate limiting
├── companies.py     # Target company seed list
├── config.py        # Config loaded from .env
├── profile.md       # Candidate profile (loaded as Claude cached system prompt)
├── main.py          # CLI entry point
└── .env.example     # API key template
```
