"""Pure-logic + fire-and-forget contract for research.py."""

from __future__ import annotations

import pytest

import research
from emailfinder import HunterCreditsExhausted
from research import ResearchResult, _title_score, research_company


def test_title_score_recognises_founder_and_cto() -> None:
    assert _title_score("Founder") == 10
    assert _title_score("Co-Founder") == 10
    assert _title_score("CTO") == 9
    assert _title_score("Chief Technology Officer") == 9


def test_title_score_penalises_hr_and_unknown() -> None:
    assert _title_score("Talent Partner") == 1
    assert _title_score("Office Manager") == 1


def test_title_score_is_case_insensitive() -> None:
    assert _title_score("head of data") == _title_score("Head of Data") == 8


def test_research_result_construction_defaults() -> None:
    result = ResearchResult(company="Acme", domain="acme.test")
    assert result.company == "Acme"
    assert result.domain == "acme.test"
    assert result.contact_email == ""
    assert result.success == "partial"


def test_research_company_never_raises_on_hunter_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*_a: object, **_kw: object) -> dict:
        from emailfinder import HunterError
        raise HunterError("simulated network failure")

    monkeypatch.setattr(research, "get_domain_pattern", _fail)
    monkeypatch.setattr(research, "_scrape_homepage", lambda *_a, **_kw: "")
    monkeypatch.setattr(
        research,
        "_claude_synthesize",
        lambda *_a, **_kw: {
            "contact_first": "", "contact_last": "", "contact_title": "", "context": "",
        },
    )
    result = research_company("NoCo", "noco.test")
    assert isinstance(result, ResearchResult)
    assert result.success in {"failed", "partial"}
    assert "Hunter error" in result.notes


def test_research_company_never_raises_on_claude_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        research,
        "get_domain_pattern",
        lambda *_a, **_kw: {"pattern": "", "emails": [], "organization": "", "credits_used": 1},
    )
    monkeypatch.setattr(research, "_scrape_homepage", lambda *_a, **_kw: "")

    def _claude_fail(*_a: object, **_kw: object) -> dict:
        raise RuntimeError("claude went down")

    monkeypatch.setattr(research, "_claude_synthesize", _claude_fail)

    result = research_company("ClaudeDownCo", "claudedown.test")
    assert isinstance(result, ResearchResult)
    assert "Claude error" in result.notes


def test_research_company_propagates_credits_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    def _exhausted(*_a: object, **_kw: object) -> dict:
        raise HunterCreditsExhausted("out of credits")

    monkeypatch.setattr(research, "get_domain_pattern", _exhausted)
    monkeypatch.setattr(research, "_scrape_homepage", lambda *_a, **_kw: "")
    monkeypatch.setattr(
        research,
        "_claude_synthesize",
        lambda *_a, **_kw: {"contact_first": "", "contact_last": "", "contact_title": "", "context": ""},
    )
    with pytest.raises(HunterCreditsExhausted):
        research_company("BrokeCo", "broke.test")


def test_research_company_full_success_when_everything_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        research,
        "get_domain_pattern",
        lambda *_a, **_kw: {
            "pattern": "{first}@target.test",
            "emails": [
                {"first": "Jane", "last": "Doe", "position": "CTO",
                 "email": "jane@target.test", "confidence": 95},
            ],
            "organization": "TargetCo",
            "credits_used": 1,
        },
    )
    monkeypatch.setattr(research, "_scrape_homepage", lambda *_a, **_kw: "TargetCo builds payment APIs.")
    monkeypatch.setattr(
        research,
        "_claude_synthesize",
        lambda *_a, **_kw: {
            "contact_first": "Jane",
            "contact_last":  "Doe",
            "contact_title": "CTO",
            "context":       "Builds payment APIs in London.",
        },
    )
    result = research_company("TargetCo", "target.test")
    assert result.success == "full"
    assert result.contact_email == "jane@target.test"
    assert result.email_confidence == 95
    assert result.email_method == "hunter_list"
