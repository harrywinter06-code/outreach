"""Cold-email variant whose ask is a self-funded micro-internship, not 'a chat'.

The default cold email asks "would you have 15 minutes?" Founders decline
calls easily — they cost time and yield uncertain value. They have a
much harder time declining a specific 7-day commitment of free work with
a concrete deliverable.

Asymmetric ask: zero cost / cap-ex to the company, a defined output Harry
will produce regardless, no expectation of an offer at the end.

If 5% of recipients accept a free deliverable (well above the call-reply
rate), and Harry produces real value, conversion to offer is much higher
than from a generic call. Same target list, different ask.

This module is additive — it does NOT replace generate.generate_cold_email.
It uses generate._call when available and falls back to its own thin
caller otherwise (so it works even if generate.py changes).

Usage:
    from micro_intern import generate_micro_intern_email
    raw, usage, report = generate_micro_intern_email(
        company="Volt",
        sector="fintech_payments",
        company_context="Open banking payment network across thirty markets.",
        contact_first="Sarah",
        deliverable_hint="failure-rate analysis of cross-border routing decisions",
    )
"""

from __future__ import annotations

import logging

import anthropic
from anthropic.types import TextBlock

from config import ANTHROPIC_API_KEY, GENERATE_MODEL, PROFILE_PATH
from quality import CheckReport, check_email_mechanical

__all__ = [
    "DELIVERABLE_HINTS_BY_SECTOR",
    "MAX_REGEN_ATTEMPTS",
    "MICRO_INTERN_SYSTEM_TEMPLATE",
    "generate_micro_intern_email",
    "parse_micro_intern_output",
]


log = logging.getLogger(__name__)

MAX_REGEN_ATTEMPTS = 3


# Suggested deliverables to seed the prompt with when the caller doesn't
# supply one. These are general enough to be a starting point Claude can
# specialise from. Keep each one defensible — Harry can actually produce
# the output described.
DELIVERABLE_HINTS_BY_SECTOR: dict[str, str] = {
    "data_analytics":      "a tightly-scoped Python notebook analysing one specific data flow in their product",
    "fintech_payments":    "a routing-failure-rate analysis pulling their public docs / homepage data",
    "fintech_lending":     "an underwriting feature-set audit benchmarked against publicly-disclosed defaults",
    "quant_trading":       "an out-of-sample backtest of one strategy on their reported asset class",
    "ai_ml":               "an evaluation harness for one of their models against a public benchmark",
    "regtech_compliance":  "a typology coverage audit against published AML/FATF guidance",
    "bioai":               "a literature review pulling 20 papers on one specific problem they're solving",
    "climate_esg":         "a scope-3 data-source mapping for one of their customer industries",
    "proptech":            "a data-quality audit across their public dataset",
    "consulting_strategy": "a competitive-landscape memo on one segment they serve",
}


MICRO_INTERN_SYSTEM_TEMPLATE = """You write cold emails for Harry Winter (UCL undergraduate, summer 2026 internship search) where the ask is a self-funded 7-day deliverable, not a call.

THE ASK FRAMING — non-negotiable:
The email proposes specific free work. Harry will spend 7 days producing a defined output for the company. No expectation of an offer at the end. No equity. No payment. The recipient says yes by replying with "send it when it's done" — no commitment beyond a reply.

This is asymmetric on purpose. A 15-minute call is easy to decline. A 7-day analysis with a concrete deliverable is not.

REALISM RULE: every claim of familiarity with the company must be something Harry could catch up on in 1-2 hours before a call.
Allowed: read their blog, looked at homepage, read about their funding round, saw their docs, read a news article.
Banned: "I listened to your podcast", "I've been using your product", "as a customer", "watched all your talks", "read all your papers".

VOICE RULES — never use:
- Banned words: leverage, utilize, facilitate, delve, showcase, underscores, augment, embark, robust, seamless, innovative, transformative, invaluable, synergistic, commendable, vibrant, landscape, tapestry, realm, ecosystem, implementation, optimization, institution, thought-provoking.
- Banned phrases: "I hope this message finds you well", "It's worth noting", "fast-paced", "I am passionate about", "I am excited to", "I would love to", "Feel free to reach out", "Don't hesitate to", "In conclusion", "comprehensive overview".
- Banned transitions: moreover, furthermore, additionally, consequently, subsequently, nevertheless, nonetheless, henceforth.

NO em dashes (—). Use periods or commas.
NO URLs in the body. NO "please find attached", NO attachment language.
NO quant jargon (NSGA-III, PPO, DSR, PBO, CPCV).
At most 1 semicolon.

SUBJECT: 15-30 characters, lowercase (proper nouns excepted), 3-5 words. Reference what they do, not Harry. No em-dash.

BODY: exactly 3 short paragraphs, 80-120 words total between greeting and sign-off. This is slightly longer than the default cold email because the ask carries more substance.

Greeting: "Hi [first_name]," on its own line.

Paragraph 1 — them, 1 sentence:
What the company does, plus one genuine reaction tied to the deliverable Harry is about to propose. Specific, not generic.

Paragraph 2 — Harry + the offer, 2-3 sentences:
- Who Harry is: UCL, IMB, predicted First, penultimate year. Use AT MOST TWO of these.
- The credential matching the role-type given. Data/Python → trading system. Product/strategy → Svitlo or NatWest/JPM sprint. Never both.
- The deliverable: spell it out concretely. "I'd like to spend the next 7 days [DELIVERABLE] and send you what I find." Be specific about the output (a notebook, a 3-page memo, a benchmark report).

Paragraph 3 — the ask, 1 sentence:
"No expectation of an offer at the end. Reply 'yes' if you'd find it useful and I'll start tomorrow."
Or a one-line variant that keeps two properties: explicit "no offer expected" + low-friction yes signal.

Close: "— Harry" only.

If a UCL alumni context is provided, the opening references that shared connection.

If a previous attempt is provided with failed checks, fix only those without breaking passing checks.

OUTPUT FORMAT — exactly these two blocks, nothing else:
Subject: [subject line]
---
[email body]

HARRY'S PROFILE:
{profile}
"""


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY not set — required to generate micro-intern emails."
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _strip_em_dashes(text: str) -> str:
    """Replace em dashes with periods (before uppercase) or commas (lowercase)."""
    import re
    text = re.sub(r"—\s*Harry\s*$", "- Harry", text.rstrip())
    text = re.sub(r"\s*—\s+([A-Z])", lambda m: ". " + m.group(1), text)
    text = re.sub(r"\s*—\s+", ", ", text)
    return text.replace("—", ", ")


def parse_micro_intern_output(raw: str) -> tuple[str, str]:
    """Split 'Subject: X\\n---\\nbody' → (subject, body)."""
    if "---" in raw:
        head, _, tail = raw.partition("---")
        subject = head.replace("Subject:", "").strip()
        body = tail.strip()
    else:
        subject = ""
        body = raw.strip()
    return subject, body


def _call(system_prompt: str, user_message: str, max_tokens: int = 500) -> tuple[str, dict[str, int]]:
    """Self-contained Claude call so this module doesn't depend on generate.py."""
    client = _get_client()
    response = client.messages.create(
        model=GENERATE_MODEL,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_message}],
    )
    text = next((b.text for b in response.content if isinstance(b, TextBlock)), "")
    usage = {
        "input_tokens":  int(response.usage.input_tokens),
        "output_tokens": int(response.usage.output_tokens),
        "cache_read":    int(getattr(response.usage, "cache_read_input_tokens", 0) or 0),
        "cache_write":   int(getattr(response.usage, "cache_creation_input_tokens", 0) or 0),
    }
    return text.strip(), usage


# Mechanical checks for THIS email mode. Same rules as the default cold
# email except for the wider word budget — the ask is substantive.
_MICRO_INTERN_BODY_MIN = 80
_MICRO_INTERN_BODY_MAX = 120


def _check_mechanical_micro(
    subject: str,
    body: str,
    contact_first: str,
) -> CheckReport:
    """Reuse quality.check_email_mechanical but override the word budget."""
    report = check_email_mechanical(subject, body, contact_first)
    # Replace the body_word_count check with our wider budget.
    word_count_idx = next(
        (i for i, c in enumerate(report.checks) if c.name == "body_word_count"),
        None,
    )
    if word_count_idx is not None:
        from quality import Check
        wc = len([w for w in body.split() if w])
        ok = _MICRO_INTERN_BODY_MIN <= wc <= _MICRO_INTERN_BODY_MAX
        report.checks[word_count_idx] = Check(
            name="body_word_count",
            passed=ok,
            reason=(
                "" if ok
                else f"Body is {wc} words; micro-intern budget is "
                     f"{_MICRO_INTERN_BODY_MIN}-{_MICRO_INTERN_BODY_MAX}."
            ),
        )
    return report


def _resolve_deliverable(sector: str, deliverable_hint: str) -> str:
    if deliverable_hint.strip():
        return deliverable_hint.strip()
    return DELIVERABLE_HINTS_BY_SECTOR.get(
        sector, "a focused 1-week analysis of one specific problem in their product"
    )


def _build_user_message(
    company: str,
    sector: str,
    company_context: str,
    contact_first: str,
    deliverable: str,
    role_or_area: str,
    has_ucl_alumni_context: bool,
    previous_attempt: tuple[str, str] | None,
    failed_checks: list[tuple[str, str]] | None,
) -> str:
    base = (
        f"Write the micro-internship cold email for:\n\n"
        f"Company: {company}\n"
        f"Sector: {sector}\n"
        f"Contact first name: {contact_first}\n"
        f"Target area: {role_or_area}\n"
        f"Company context (use for P1 opener): {company_context}\n\n"
        f"Proposed deliverable for the 7-day commitment: {deliverable}\n"
        f"UCL alumni context present: {'yes' if has_ucl_alumni_context else 'no'}\n\n"
        "Output in the specified format."
    )
    if previous_attempt and failed_checks:
        prev_subject, prev_body = previous_attempt
        failure_lines = "\n".join(f"  - {name}: {reason}" for name, reason in failed_checks)
        return (
            base
            + "\n\nPREVIOUS ATTEMPT failed these checks. Fix them, do not break passing checks.\n\n"
            f"Previous subject: {prev_subject}\n"
            f"Previous body:\n{prev_body}\n\n"
            f"Failed checks:\n{failure_lines}"
        )
    return base


def generate_micro_intern_email(
    company: str,
    sector: str,
    company_context: str,
    contact_first: str,
    *,
    deliverable_hint: str = "",
    role_or_area: str = "data / analyst / ML internship",
    has_ucl_alumni_context: bool = False,
    max_regen_attempts: int = MAX_REGEN_ATTEMPTS,
) -> tuple[str, dict[str, int], CheckReport]:
    """Generate a micro-internship cold email, gated on mechanical checks.

    Returns (raw_text, aggregated_usage, mechanical_check_report). The semantic
    judge is NOT run by default — this is a different ask shape so the email
    quality.check_email_semantic checks (which assume the conversation-ask
    structure) would mis-fire. Mechanical voice/length checks still apply.
    """
    if not contact_first:
        raise ValueError("contact_first is required.")

    profile = PROFILE_PATH.read_text(encoding="utf-8")
    system_prompt = MICRO_INTERN_SYSTEM_TEMPLATE.format(profile=profile)
    deliverable = _resolve_deliverable(sector, deliverable_hint)

    total_usage = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0}
    best: tuple[str, CheckReport] | None = None
    previous_attempt: tuple[str, str] | None = None
    failed_checks: list[tuple[str, str]] | None = None

    for attempt in range(1, max_regen_attempts + 1):
        user_message = _build_user_message(
            company, sector, company_context, contact_first, deliverable,
            role_or_area, has_ucl_alumni_context, previous_attempt, failed_checks,
        )
        raw, usage = _call(system_prompt, user_message, max_tokens=600)
        for key in total_usage:
            total_usage[key] += usage.get(key, 0)

        subject, body = parse_micro_intern_output(raw)
        body = _strip_em_dashes(body)
        normalised = f"Subject: {subject}\n---\n{body}"
        report = _check_mechanical_micro(subject, body, contact_first)

        if best is None or report.passed_count > best[1].passed_count:
            best = (normalised, report)

        if report.all_passed:
            log.info("Micro-intern email passed checks on attempt %d", attempt)
            return normalised, total_usage, report

        log.warning(
            "Micro-intern attempt %d failed checks: %s", attempt, report.summary()
        )
        previous_attempt = (subject, body)
        failed_checks = [(c.name, c.reason) for c in report.failed()]

    assert best is not None
    best_text, best_report = best
    log.warning(
        "Micro-intern did not reach 100%% pass after %d attempts. Best: %s",
        max_regen_attempts, best_report.summary(),
    )
    return best_text, total_usage, best_report
