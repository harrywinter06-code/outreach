"""Quality-check tests.

Mechanical checks are pure functions — no mocking needed.
Semantic checks are tested by injecting a fake Anthropic client so no
network call is made.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from anthropic.types import TextBlock

from quality import (
    SEMANTIC_CHECK_NAMES,
    CheckReport,
    check_email,
    check_email_mechanical,
    check_email_semantic,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_GOOD_BODY = (
    "Hi Sarah,\n\n"
    "Volt's open banking payment network across thirty markets is a serious data "
    "routing problem, and the throughput numbers on your homepage caught my eye.\n\n"
    "I'm a UCL student in my penultimate year. I built an automated trading "
    "pipeline that ingests live macro and equity data daily with no manual touch, "
    "and I'm hoping to spend summer working on a real data problem.\n\n"
    "Would it be worth a quick chat? Happy to fit around you.\n\n"
    "- Harry"
)

_GOOD_SUBJECT = "open banking, ucl student"


def _fake_judge_response(verdicts: list[dict[str, Any]]) -> MagicMock:
    """Build a response object whose content[0] passes isinstance(b, TextBlock)."""
    block = TextBlock(type="text", text=json.dumps(verdicts))
    msg = MagicMock()
    msg.content = [block]
    return msg


def _fake_client_returning(verdicts: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = _fake_judge_response(verdicts)
    return client


# ── CheckReport ───────────────────────────────────────────────────────────────


def test_empty_report_does_not_count_as_passed() -> None:
    report = CheckReport()
    assert not report.all_passed
    assert report.score == 0.0


def test_report_passes_when_all_checks_pass() -> None:
    report = CheckReport()
    report.add("a", True)
    report.add("b", True)
    assert report.all_passed
    assert report.score == 1.0
    assert report.failed() == []


def test_report_score_is_fraction() -> None:
    report = CheckReport()
    report.add("a", True)
    report.add("b", False, "bad")
    report.add("c", True)
    report.add("d", False, "bad")
    assert report.passed_count == 2
    assert report.total == 4
    assert report.score == 0.5


# ── Mechanical checks ─────────────────────────────────────────────────────────


def test_mechanical_passes_on_good_email() -> None:
    report = check_email_mechanical(_GOOD_SUBJECT, _GOOD_BODY, "Sarah")
    assert report.all_passed, report.summary()


def test_subject_too_short_fails() -> None:
    report = check_email_mechanical("hi", _GOOD_BODY, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "subject_length" in failed_names


def test_subject_too_long_fails() -> None:
    report = check_email_mechanical("a" * 50, _GOOD_BODY, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "subject_length" in failed_names


def test_body_too_short_fails() -> None:
    short_body = "Hi Sarah,\n\nShort body here.\n\n- Harry"
    report = check_email_mechanical(_GOOD_SUBJECT, short_body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "body_word_count" in failed_names


def test_body_too_long_fails() -> None:
    long_body = "Hi Sarah,\n\n" + ("word " * 100) + "\n\n- Harry"
    report = check_email_mechanical(_GOOD_SUBJECT, long_body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "body_word_count" in failed_names


def test_wrong_greeting_fails() -> None:
    body = _GOOD_BODY.replace("Hi Sarah,", "Dear Sarah,")
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "greeting_format" in failed_names


def test_missing_signoff_fails() -> None:
    body = _GOOD_BODY.replace("- Harry", "Cheers,\nHarry")
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "signoff_format" in failed_names


def test_banned_word_fails() -> None:
    body = _GOOD_BODY.replace("data routing problem", "innovative data routing problem")
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "no_banned_words" in failed_names


def test_banned_phrase_fails() -> None:
    body = _GOOD_BODY.replace("Hi Sarah,", "Hi Sarah, I hope this message finds you well.")
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "no_banned_phrases" in failed_names


def test_em_dash_fails() -> None:
    body = _GOOD_BODY.replace("a real data problem", "a real — data problem")
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "no_em_dashes" in failed_names


def test_url_fails() -> None:
    body = _GOOD_BODY.replace("- Harry", "github.com/harrywinter\n\n- Harry")
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "no_urls" in failed_names


def test_quant_jargon_fails() -> None:
    body = _GOOD_BODY.replace("ingests live macro", "ingests live PPO macro")
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "no_quant_jargon" in failed_names


def test_attachment_claim_fails() -> None:
    body = _GOOD_BODY.replace("- Harry", "Please find attached my CV.\n\n- Harry")
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "no_attachment_claims" in failed_names


def test_multiple_semicolons_fail() -> None:
    body = _GOOD_BODY.replace(
        "a serious data routing problem, and",
        "a serious data; routing; problem; and",
    )
    report = check_email_mechanical(_GOOD_SUBJECT, body, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "max_one_semicolon" in failed_names


def test_uppercase_subject_fails() -> None:
    report = check_email_mechanical("Open Banking UCL Student", _GOOD_BODY, "Sarah")
    failed_names = {c.name for c in report.failed()}
    assert "subject_lowercase" in failed_names


# ── Semantic checks (mocked judge) ────────────────────────────────────────────


def _all_pass_verdicts() -> list[dict[str, Any]]:
    return [{"name": n, "passed": True, "reason": ""} for n in SEMANTIC_CHECK_NAMES]


def test_semantic_all_pass_when_judge_says_so() -> None:
    client = _fake_client_returning(_all_pass_verdicts())
    report = check_email_semantic(
        subject=_GOOD_SUBJECT,
        body=_GOOD_BODY,
        role_type="data",
        company_context="Open banking API.",
        has_ucl_alumni_context=False,
        client=client,
    )
    assert report.all_passed
    assert report.total == len(SEMANTIC_CHECK_NAMES)
    client.messages.create.assert_called_once()


def test_semantic_records_failures() -> None:
    verdicts = _all_pass_verdicts()
    verdicts[0]["passed"] = False
    verdicts[0]["reason"] = "Opening was generic."
    client = _fake_client_returning(verdicts)
    report = check_email_semantic(
        subject=_GOOD_SUBJECT,
        body=_GOOD_BODY,
        role_type="data",
        company_context="Open banking API.",
        has_ucl_alumni_context=False,
        client=client,
    )
    assert not report.all_passed
    failures = {c.name: c.reason for c in report.failed()}
    assert "p1_company_specific" in failures
    assert failures["p1_company_specific"] == "Opening was generic."


def test_semantic_marks_missing_checks_as_failed() -> None:
    # Judge returns only the first 3 verdicts; the remaining 4 must be marked failed.
    partial = _all_pass_verdicts()[:3]
    client = _fake_client_returning(partial)
    report = check_email_semantic(
        subject=_GOOD_SUBJECT,
        body=_GOOD_BODY,
        role_type="data",
        company_context="Open banking API.",
        has_ucl_alumni_context=False,
        client=client,
    )
    failures = {c.name for c in report.failed()}
    assert "ucl_alumni_opener" in failures
    assert "realism_rule" in failures


def test_semantic_handles_judge_exception_loudly() -> None:
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("network down")
    report = check_email_semantic(
        subject=_GOOD_SUBJECT,
        body=_GOOD_BODY,
        role_type="data",
        company_context="",
        has_ucl_alumni_context=False,
        client=client,
    )
    assert report.total == len(SEMANTIC_CHECK_NAMES)
    assert not report.all_passed
    for check in report.checks:
        assert "Judge call failed" in check.reason


# ── Combined check ────────────────────────────────────────────────────────────


def test_check_email_combines_mechanical_and_semantic() -> None:
    client = _fake_client_returning(_all_pass_verdicts())
    report = check_email(
        subject=_GOOD_SUBJECT,
        body=_GOOD_BODY,
        contact_first="Sarah",
        role_type="data",
        company_context="Open banking API.",
        semantic_client=client,
    )
    assert report.total == 14 + len(SEMANTIC_CHECK_NAMES)
    assert report.all_passed


def test_check_email_skip_semantic() -> None:
    report = check_email(
        subject=_GOOD_SUBJECT,
        body=_GOOD_BODY,
        contact_first="Sarah",
        role_type="data",
        company_context="Open banking API.",
        skip_semantic=True,
    )
    assert report.total == 14
    assert report.all_passed


# ── Generate.py integration: confirm 3-tuple shape ───────────────────────────

def test_generate_cold_email_returns_three_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    """The function must always return (text, usage, report). The actual
    Claude call is mocked so this test has no network or API-key dependency.
    """
    import generate

    def _fake_call(_system: str, _user: str, max_tokens: int = 1000) -> tuple[str, dict]:
        return (
            f"Subject: {_GOOD_SUBJECT}\n---\n{_GOOD_BODY}",
            {"input_tokens": 100, "output_tokens": 50, "cache_read": 0, "cache_write": 0},
        )

    monkeypatch.setattr(generate, "_call", _fake_call)

    raw, usage, report = generate.generate_cold_email(
        "Volt",
        "data analytics internship",
        "Open banking payment network across thirty markets.",
        "Sarah Smith",
        skip_semantic_check=True,
    )
    assert isinstance(raw, str)
    assert raw.startswith("Subject:")
    assert isinstance(usage, dict)
    assert usage["input_tokens"] >= 100
    assert isinstance(report, CheckReport)
    assert report.all_passed, report.summary()


def test_generate_cold_email_regenerates_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the first attempt fails, regeneration kicks in. Test by serving a
    bad body then a good body and confirming we get the good one with 2 calls."""
    import generate

    calls: list[int] = []
    bad_body = "Hi Sarah,\n\nShort body.\n\n- Harry"   # fails body_word_count
    good = f"Subject: {_GOOD_SUBJECT}\n---\n{_GOOD_BODY}"
    bad = f"Subject: {_GOOD_SUBJECT}\n---\n{bad_body}"

    def _fake_call(_system: str, _user: str, max_tokens: int = 1000) -> tuple[str, dict]:
        calls.append(len(calls) + 1)
        text = bad if len(calls) == 1 else good
        return text, {"input_tokens": 100, "output_tokens": 50, "cache_read": 0, "cache_write": 0}

    monkeypatch.setattr(generate, "_call", _fake_call)

    raw, usage, report = generate.generate_cold_email(
        "Volt", "data internship", "Some context.", "Sarah Smith",
        skip_semantic_check=True, max_regen_attempts=3,
    )

    assert len(calls) == 2, "Should have regenerated exactly once after first failure."
    assert report.all_passed
    assert usage["input_tokens"] == 200  # both attempts summed
