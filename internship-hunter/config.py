import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
HUNTER_API_KEY     = os.getenv("HUNTER_API_KEY", "")
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
# Free API key at: https://www.reed.co.uk/developers/jobseeker
# Auth uses the key as the HTTP Basic Auth username, password left blank.
REED_API_KEY       = os.getenv("REED_API_KEY", "")

# Sending cadence — 90s between emails prevents spam flagging
EMAIL_SEND_DELAY_SECONDS = 90
EMAIL_DAILY_MAX = 20
GENERATE_MODEL = "claude-sonnet-4-6"  # quality over cost — this is your career
EXTRACT_MODEL  = "claude-haiku-4-5-20251001"  # classification / extraction tasks
DB_PATH = BASE_DIR / "data" / "applications.db"
OUTPUT_DIR = BASE_DIR / "output"
COVER_LETTER_DIR = OUTPUT_DIR / "cover_letters"
OUTREACH_DIR = OUTPUT_DIR / "outreach"
PROFILE_PATH = BASE_DIR / "profile.md"

# Job discovery filters
TARGET_KEYWORDS = [
    "data analyst", "data science", "machine learning", "ML", "AI",
    "quant", "quantitative", "python", "analytics", "research analyst",
    "operations analyst", "product analyst", "fintech", "trading"
]
TARGET_LOCATIONS = [
    # UK
    "london", "uk", "united kingdom", "england",
    # Remote / hybrid (location-agnostic)
    "remote", "hybrid", "worldwide", "anywhere",
    # Ireland — Common Travel Area, no visa
    "dublin", "ireland",
    # Canada — IEC working holiday visa (~£150, no company sponsorship needed)
    "toronto", "montreal", "vancouver", "canada",
    # EU — portal-only targets, but worth discovering roles
    "amsterdam", "netherlands", "paris", "france", "berlin", "germany",
]
EXCLUDE_KEYWORDS = ["senior", "lead", "manager", "director", "head of", "principal", "staff", "10+ years", "8+ years"]

# Set True to treat jobs with no location as location-agnostic (worldwide).
# False (default) skips them — Lever boards often omit location on irrelevant global roles.
ACCEPT_LOCATION_UNKNOWN = False

CANDIDATE_NAME = "Harry Winter"
CANDIDATE_EMAIL = "harrywinter.uk@gmail.com"
