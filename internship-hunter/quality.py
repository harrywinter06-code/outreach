"""Quality checks for generated cold emails and sector-tailored CVs.

Two layers:
  - Mechanical: deterministic regex / counting / catalog membership.
                Sub-millisecond, no API cost.
  - Semantic:   single Claude Haiku call returning a JSON array of verdicts.
                Only used for emails. CV checks are fully deterministic
                because the CV is built from a fixed bullet catalog.

Each check returns a Check(name, passed, reason). A CheckReport aggregates
them. Pass gate = 100%; anything less triggers regeneration (emails) or
surfaces a build error (CVs).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from anthropic.types import TextBlock

from config import ANTHROPIC_API_KEY, EXTRACT_MODEL

if TYPE_CHECKING:
    from build_cv import CVContent

__all__ = [
    "CV_CHECK_NAMES",
    "Check",
    "CheckReport",
    "check_cv",
    "check_email",
    "check_email_mechanical",
    "check_email_semantic",
    "SEMANTIC_CHECK_NAMES",
]


log = logging.getLogger(__name__)


# ── Banned content (mechanical) ───────────────────────────────────────────────

_BANNED_WORDS = [
    "leverage", "utilize", "facilitate", "delve", "showcase",
    "underscores", "augment", "embark", "robust", "seamless",
    "innovative", "transformative", "invaluable", "synergistic",
    "commendable", "vibrant", "landscape", "tapestry", "realm",
    "ecosystem", "implementation", "optimization", "institution",
    "thought-provoking",
]

_BANNED_PHRASES = [
    "hope this message finds you well",
    "worth noting", "important to note", "should be noted",
    "fast-paced",
    "as the world continues",
    "i am passionate about", "i am excited to", "i would love to",
    "in many cases", "generally speaking", "depending on the context",
    "that being said", "with that in mind", "at the end of the day",
    "feel free to reach out", "don't hesitate to", "i'd be happy to",
    "in conclusion", "to summarize", "to recap",
    "comprehensive overview",
]

_BANNED_TRANSITIONS = [
    "moreover", "furthermore", "additionally", "consequently",
    "subsequently", "nevertheless", "nonetheless", "henceforth",
]

_QUANT_JARGON = ["NSGA-III", "PPO", "DSR", "PBO", "CPCV"]

_ATTACHMENT_PHRASES = [
    "attached my cv", "attached is my", "please find attached",
    "find attached", "attachment", "see attached",
    "as attached", "attached you",
]

_URL_PATTERN = re.compile(
    r"https?://|www\.|github\.com|\b\w+\.(?:com|io|ai|co|net|org)\b",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"\b\w+(?:[''-]\w+)*\b")


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _word_present(text_lower: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word.lower())}\b", text_lower))


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class Check:
    name: str
    passed: bool
    reason: str = ""


@dataclass
class CheckReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, passed: bool, reason: str = "") -> None:
        self.checks.append(Check(name=name, passed=passed, reason=reason if not passed else ""))

    def extend(self, other: CheckReport) -> None:
        self.checks.extend(other.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def all_passed(self) -> bool:
        return self.total > 0 and self.passed_count == self.total

    @property
    def score(self) -> float:
        return self.passed_count / self.total if self.total else 0.0

    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        if self.all_passed:
            return f"PASS ({self.passed_count}/{self.total})"
        fails = "; ".join(f"{c.name}: {c.reason}" for c in self.failed())
        return f"FAIL ({self.passed_count}/{self.total}) — {fails}"


# ── Mechanical checks (14) ────────────────────────────────────────────────────


def check_email_mechanical(
    subject: str,
    body: str,
    contact_first: str,
) -> CheckReport:
    """Deterministic checks against subject and body strings.

    Assumes em-dashes have already been stripped from `body` by the caller
    (generate.py strips them post-hoc). Any surviving em-dash fails check 10.
    """
    report = CheckReport()
    contact_first_stripped = contact_first.strip()
    body_lower = body.lower()
    subject_stripped = subject.strip()

    # 1. Subject present
    report.add("subject_present", bool(subject_stripped), "Subject line missing.")

    # 2. Subject length 15–30 chars
    sub_len = len(subject_stripped)
    report.add(
        "subject_length",
        15 <= sub_len <= 30,
        f"Subject is {sub_len} chars; want 15-30.",
    )

    # 3. Subject is predominantly lowercase (proper-noun tolerant)
    word_initials = [w[0] for w in subject_stripped.split() if w and w[0].isalpha()]
    if word_initials:
        upper_ratio = sum(1 for c in word_initials if c.isupper()) / len(word_initials)
        report.add(
            "subject_lowercase",
            upper_ratio <= 0.4,
            f"Subject too capitalised ({upper_ratio:.0%} word-initial uppercase; want ≤40%).",
        )
    else:
        report.add("subject_lowercase", False, "Subject has no alphabetic words.")

    # 4. Body word count 60–90
    wc = _word_count(body)
    report.add(
        "body_word_count",
        60 <= wc <= 90,
        f"Body is {wc} words; want 60-90.",
    )

    # 5. Body starts with "Hi {first_name},"
    expected_greeting = f"Hi {contact_first_stripped}," if contact_first_stripped else ""
    greeting_ok = bool(expected_greeting) and body.lstrip().startswith(expected_greeting)
    report.add(
        "greeting_format",
        greeting_ok,
        f"Body must start with '{expected_greeting}'." if expected_greeting else "Contact first name missing.",
    )

    # 6. Sign-off
    body_rstripped = body.rstrip()
    has_signoff = body_rstripped.endswith("- Harry") or body_rstripped.endswith("— Harry")
    report.add("signoff_format", has_signoff, "Body must end with '- Harry' or '— Harry'.")

    # 7. No banned words
    bad_words = [w for w in _BANNED_WORDS if _word_present(body_lower, w)]
    report.add(
        "no_banned_words",
        not bad_words,
        f"Banned words: {', '.join(bad_words)}.",
    )

    # 8. No banned phrases
    bad_phrases = [p for p in _BANNED_PHRASES if p in body_lower]
    report.add(
        "no_banned_phrases",
        not bad_phrases,
        f"Banned phrases: {', '.join(bad_phrases)}.",
    )

    # 9. No banned transitions
    bad_transitions = [t for t in _BANNED_TRANSITIONS if _word_present(body_lower, t)]
    report.add(
        "no_banned_transitions",
        not bad_transitions,
        f"Banned transitions: {', '.join(bad_transitions)}.",
    )

    # 10. No em-dashes
    report.add("no_em_dashes", "—" not in body, "Em-dash found in body.")

    # 11. No URLs
    report.add("no_urls", not _URL_PATTERN.search(body), "URL found in body.")

    # 12. No quant jargon
    jargon = [j for j in _QUANT_JARGON if j in body or j.lower() in body_lower]
    report.add("no_quant_jargon", not jargon, f"Quant jargon: {', '.join(jargon)}.")

    # 13. No attachment language
    attach_hits = [a for a in _ATTACHMENT_PHRASES if a in body_lower]
    report.add(
        "no_attachment_claims",
        not attach_hits,
        f"Attachment language: {', '.join(attach_hits)}.",
    )

    # 14. At most 1 semicolon
    semis = body.count(";")
    report.add("max_one_semicolon", semis <= 1, f"Body has {semis} semicolons; max 1.")

    return report


# ── Semantic checks (7) via Claude Haiku ──────────────────────────────────────

SEMANTIC_CHECK_NAMES: list[str] = [
    "p1_company_specific",
    "p2_identity_concise",
    "p2_credential_matches_role",
    "p2_credential_defensible",
    "ask_is_conversation_not_job",
    "realism_rule",
    "ucl_alumni_opener",
]


_SEMANTIC_JUDGE_SYSTEM = """You are a strict judge of a cold email written by Harry Winter (UCL undergraduate seeking a summer 2026 internship).

You will be given the email and the company context Harry was working from. Apply each check below and return ONLY a JSON array. Each entry is an object with keys:
  - "name": exact check name from the list (string)
  - "passed": true or false
  - "reason": one short sentence (required if passed=false; "" if passed=true)

Checks to apply, in this order:

1. p1_company_specific
The first paragraph (after the "Hi X," greeting) must reference something concrete about THIS company — what they do, a product, a market they serve, a recent event. Generic openers ("innovative company", "exciting mission", "I came across your company") fail.

2. p2_identity_concise
Harry's self-introduction (start of paragraph 2) mentions at most TWO of: UCL, IMB / Information Management for Business, predicted First, penultimate year. Cramming three or four = fail.

3. p2_credential_matches_role
The credential cited in paragraph 2 matches the role type given in the input:
  - data / Python / pipeline / analytics / ML / quant → the trading system (live APIs, daily pipeline, paper trading)
  - product / strategy / business / client → the UCL Svitlo sprint or NatWest/JP Morgan IMB sprint
Mentioning BOTH projects in one email = fail.

4. p2_credential_defensible
The credential must be a real, concrete project Harry can defend in an interview. Vague claims ("I enjoy working with data", "I'm passionate about AI") fail. Formal ML theory or named algorithms (NSGA-III, PPO, DSR, PBO, CPCV) fail.

5. ask_is_conversation_not_job
The final paragraph asks for a conversation / call / chat / quick chat. Asking for an "internship", "role", "opportunity", or "position" = fail.

6. realism_rule
Any claim of familiarity with the company must be something Harry could credibly catch up on in 1-2 hours before a return call.
ALLOWED: read a blog post, looked at the homepage / docs, read about a funding round, "been following X" (vague), saw news coverage, read a single article.
BANNED: listened to entire podcast, watched all their talks, "I've been using your product", "as a customer", "your platform daily", deep product experience, "read all your papers / papers" plural.

7. ucl_alumni_opener
If the input says a UCL alumni context was provided, the OPENING of paragraph 1 references that shared connection (a named UCL alum at the company) rather than a generic company observation. If no UCL context was provided, pass this check by default.

Output ONLY the JSON array. No prose. No markdown fences."""


def _parse_judge_json(raw: str) -> list[dict]:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError as e:
        log.warning("Judge JSON parse failed: %s", e)
        return []
    return parsed if isinstance(parsed, list) else []


_client: anthropic.Anthropic | None = None


def _shared_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set — required for semantic checks.")
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def check_email_semantic(
    subject: str,
    body: str,
    role_type: str,
    company_context: str,
    has_ucl_alumni_context: bool,
    client: anthropic.Anthropic | None = None,
) -> CheckReport:
    """Run all 7 semantic checks via one Claude Haiku call."""
    report = CheckReport()
    judge = client or _shared_client()

    user_message = (
        f"ROLE TYPE: {role_type}\n"
        f"UCL ALUMNI CONTEXT PROVIDED: {'yes' if has_ucl_alumni_context else 'no'}\n\n"
        "COMPANY CONTEXT (what Harry was working from):\n"
        f"{company_context}\n\n"
        f"EMAIL SUBJECT: {subject}\n\n"
        "EMAIL BODY:\n"
        f"{body}\n\n"
        "Apply all 7 checks and return the JSON array."
    )

    try:
        response = judge.messages.create(
            model=EXTRACT_MODEL,
            max_tokens=700,
            system=[{
                "type": "text",
                "text": _SEMANTIC_JUDGE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        log.warning("Semantic judge call failed: %s", e)
        for name in SEMANTIC_CHECK_NAMES:
            report.add(name, False, f"Judge call failed: {e}")
        return report

    raw = next((b.text for b in response.content if isinstance(b, TextBlock)), "")
    parsed = _parse_judge_json(raw)

    seen: set[str] = set()
    for entry in parsed:
        name = (entry.get("name") or "").strip()
        if not name or name not in SEMANTIC_CHECK_NAMES:
            continue
        seen.add(name)
        report.add(
            name,
            bool(entry.get("passed", False)),
            (entry.get("reason") or "").strip(),
        )

    for name in SEMANTIC_CHECK_NAMES:
        if name not in seen:
            report.add(name, False, "Judge omitted this check.")

    return report


# ── Combined check ────────────────────────────────────────────────────────────


def check_email(
    subject: str,
    body: str,
    contact_first: str,
    role_type: str,
    company_context: str,
    has_ucl_alumni_context: bool = False,
    *,
    skip_semantic: bool = False,
    semantic_client: anthropic.Anthropic | None = None,
) -> CheckReport:
    """Run all 21 email checks (14 mechanical + 7 semantic).

    skip_semantic=True: useful in unit tests to avoid the Haiku call.
    semantic_client: inject a mocked client for tests.
    """
    combined = CheckReport()
    combined.extend(check_email_mechanical(subject, body, contact_first))
    if not skip_semantic:
        combined.extend(check_email_semantic(
            subject, body, role_type, company_context,
            has_ucl_alumni_context, client=semantic_client,
        ))
    return combined


# ── CV checks (10, all deterministic) ────────────────────────────────────────

CV_CHECK_NAMES: list[str] = [
    "word_count_within_budget",
    "all_sections_present",
    "no_banned_words",
    "no_em_dashes",
    "no_quant_jargon",
    "filename_has_sector_tag",
    "sector_relevant_bullet_present",
    "all_bullets_from_catalog",
    "lead_project_matches_sector",
    "skills_within_allowlist",
]

_CV_WORD_BUDGET = 850

# Skills technical content must consist only of tokens from this list.
# Anything else means a tool/skill not on the source profile leaked in.
_TECHNICAL_SKILL_ALLOWLIST: set[str] = {
    "python", "pandas", "numpy", "yfinance", "requests", "sqlite3",
    "streamlit", "anthropic", "sdk", "sql", "excel", "git",
}


def _strip_skills_punct(text: str) -> list[str]:
    """Lowercase tokens with light punctuation stripped — for skill-set comparison."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return cleaned.split()


def check_cv(content: CVContent, output_path: Path) -> CheckReport:
    """Run all 10 CV checks against the tailored content + filename.

    Imports CVContent locally to avoid a circular import at module load.
    """
    from build_cv import (  # local import
        ALLOWED_PROJECTS,
        BULLET_CATALOG,
        SECTOR_PROJECT_ORDER,
        SECTORS,
    )

    report = CheckReport()
    sector = content.sector

    if sector not in SECTORS:
        # Single failure that subsumes the rest — no point grading further.
        for name in CV_CHECK_NAMES:
            report.add(name, False, f"Unknown sector {sector!r}.")
        return report

    bullets = content.all_bullets()
    bullets_lower = [b.lower() for b in bullets]

    # 1. Word count
    word_count = content.total_word_count()
    report.add(
        "word_count_within_budget",
        word_count <= _CV_WORD_BUDGET,
        f"CV is {word_count} words; budget is {_CV_WORD_BUDGET}.",
    )

    # 2. All required sections present
    sections_ok = (
        bool(content.education_entries)
        and bool(content.project_entries)
        and bool(content.experience_entries)
        and bool(content.skills_technical)
        and bool(content.skills_additional)
    )
    missing = []
    if not content.education_entries:
        missing.append("education")
    if not content.project_entries:
        missing.append("projects")
    if not content.experience_entries:
        missing.append("experience")
    if not content.skills_technical:
        missing.append("skills_technical")
    if not content.skills_additional:
        missing.append("skills_additional")
    report.add(
        "all_sections_present",
        sections_ok,
        f"Missing: {', '.join(missing)}." if missing else "",
    )

    # 3. No banned words
    bad_words = sorted({
        w for b in bullets_lower for w in _BANNED_WORDS if _word_present(b, w)
    })
    report.add("no_banned_words", not bad_words, f"Banned words: {', '.join(bad_words)}.")

    # 4. No em-dashes
    em_dash_lines = [b for b in bullets if "—" in b]
    report.add("no_em_dashes", not em_dash_lines, f"{len(em_dash_lines)} bullet(s) contain em-dash.")

    # 5. No quant jargon
    jargon_hits = sorted({
        j for b in bullets for j in _QUANT_JARGON if j in b or j.lower() in b.lower()
    })
    report.add("no_quant_jargon", not jargon_hits, f"Quant jargon: {', '.join(jargon_hits)}.")

    # 6. Filename includes sector tag
    fname = output_path.name.lower()
    report.add(
        "filename_has_sector_tag",
        sector.lower() in fname,
        f"Sector tag {sector!r} not in filename {output_path.name!r}.",
    )

    # 7. At least one Projects bullet is tagged for this sector
    project_bullets_text: set[str] = set()
    for entry in content.project_entries:
        project_bullets_text.update(entry.bullets)
    sector_tagged = [
        b for b in BULLET_CATALOG
        if b.text in project_bullets_text and sector in b.sector_tags
    ]
    report.add(
        "sector_relevant_bullet_present",
        bool(sector_tagged),
        f"No project bullet is tagged for sector {sector!r}.",
    )

    # 8. Every bullet in the CV traces back to the catalog (or to the fixed
    # education entries — those are not in the catalog by design).
    catalog_texts = {b.text for b in BULLET_CATALOG}
    education_texts: set[str] = set()
    for entry in content.education_entries:
        education_texts.update(entry.bullets)
    foreign = [
        b for b in (project_bullets_text | {
            x for e in content.experience_entries for x in e.bullets
        })
        if b not in catalog_texts and b not in education_texts
    ]
    report.add(
        "all_bullets_from_catalog",
        not foreign,
        f"{len(foreign)} bullet(s) not in catalog (possible fabrication).",
    )

    # 9. Lead project (first in Projects section) matches the sector ordering.
    expected_lead = SECTOR_PROJECT_ORDER[sector][0]
    lead_text = content.project_entries[0].title if content.project_entries else ""
    project_id_for_lead = _project_id_for_title(lead_text, BULLET_CATALOG)
    report.add(
        "lead_project_matches_sector",
        project_id_for_lead == expected_lead,
        f"Lead project is {project_id_for_lead!r}; sector {sector!r} expects {expected_lead!r}.",
    )

    # 10. Skills technical line is within allow-list, and every project_id
    # referenced is one of the allowed projects (catches re-introduced
    # Investment Society / Pottermore by ID-not-in-allow-list).
    tech_tokens = set(_strip_skills_punct(content.skills_technical))
    extra = sorted(tech_tokens - _TECHNICAL_SKILL_ALLOWLIST)
    catalog_projects_in_use = {
        b.project for b in BULLET_CATALOG if b.text in (project_bullets_text | {
            x for e in content.experience_entries for x in e.bullets
        })
    }
    project_id_problems = sorted(catalog_projects_in_use - ALLOWED_PROJECTS)
    skills_ok = not extra and not project_id_problems
    reason_parts = []
    if extra:
        reason_parts.append(f"Skills outside allow-list: {', '.join(extra)}.")
    if project_id_problems:
        reason_parts.append(f"Disallowed projects: {', '.join(project_id_problems)}.")
    report.add("skills_within_allowlist", skills_ok, " ".join(reason_parts))

    return report


def _project_id_for_title(title: str, catalog: list) -> str:
    """Reverse-lookup the project_id whose header title matches the entry title.

    Used by check 9 to verify the lead project is the sector-correct one.
    """
    from build_cv import _PROJECT_HEADERS  # local import to dodge circular

    for project_id, (entry_title, _tech, _dates) in _PROJECT_HEADERS.items():
        if entry_title == title:
            return project_id
    return ""
