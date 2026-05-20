"""Tests for sector-tailored CV building + CV quality checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from build_cv import (
    ALLOWED_PROJECTS,
    BULLET_CATALOG,
    SECTOR_PROJECT_ORDER,
    SECTORS,
    Entry,
    build,
    tailor_for_sector,
)
from quality import CV_CHECK_NAMES, check_cv

# ── Catalog / static-data sanity ──────────────────────────────────────────────


def test_every_catalog_bullet_uses_allowed_project() -> None:
    bad = sorted({b.project for b in BULLET_CATALOG} - ALLOWED_PROJECTS)
    assert not bad, f"Catalog contains disallowed project ids: {bad}"


def test_every_sector_has_a_project_order() -> None:
    for sector in SECTORS:
        assert sector in SECTOR_PROJECT_ORDER, f"Missing project order for {sector}"
        order = SECTOR_PROJECT_ORDER[sector]
        assert order, f"Empty project order for {sector}"
        for project_id in order:
            assert project_id in ALLOWED_PROJECTS, (
                f"Project {project_id!r} in order for {sector!r} not allowed"
            )


def test_no_excluded_items_in_catalog() -> None:
    """cv_content.md: Investment Society, Pottermore, Zester, Investment Fund must not appear."""
    forbidden = ("investment society", "pottermore", "zester", "investment fund", "uk deal insights")
    all_text = " ".join(b.text.lower() for b in BULLET_CATALOG)
    found = [w for w in forbidden if w in all_text]
    assert not found, f"Excluded items present in catalog text: {found}"


# ── Sector tailoring ──────────────────────────────────────────────────────────


def test_unknown_sector_rejected() -> None:
    with pytest.raises(ValueError):
        tailor_for_sector("not_a_sector")


@pytest.mark.parametrize("sector", SECTORS)
def test_tailor_returns_complete_content_for_every_sector(sector: str) -> None:
    content = tailor_for_sector(sector)
    assert content.sector == sector
    assert content.education_entries, "Education must be populated"
    assert len(content.project_entries) >= 2, "At least 2 project entries"
    assert content.experience_entries, "Experience must be populated"
    assert content.skills_technical
    assert content.skills_additional


def test_tailor_lead_project_matches_sector_order() -> None:
    for sector in SECTORS:
        content = tailor_for_sector(sector)
        expected_lead = SECTOR_PROJECT_ORDER[sector][0]
        # Look up the project_id corresponding to the first project's title.
        from build_cv import _PROJECT_HEADERS
        title_to_id = {title: pid for pid, (title, _t, _d) in _PROJECT_HEADERS.items()}
        actual_lead = title_to_id.get(content.project_entries[0].title, "")
        assert actual_lead == expected_lead, (
            f"Sector {sector}: lead is {actual_lead!r}, expected {expected_lead!r}"
        )


def test_tailor_lead_project_has_more_bullets_than_second() -> None:
    """Lead project should occupy more visual real estate."""
    for sector in SECTORS:
        content = tailor_for_sector(sector)
        lead_bullets = len(content.project_entries[0].bullets)
        second_bullets = len(content.project_entries[1].bullets)
        assert lead_bullets >= second_bullets, (
            f"Sector {sector}: lead has {lead_bullets} bullets, second has {second_bullets}"
        )


def test_ai_ml_sector_leads_with_llm_tool() -> None:
    content = tailor_for_sector("ai_ml")
    assert content.project_entries[0].title == "Job Market Intelligence Tool"


def test_data_analytics_sector_leads_with_trading_system() -> None:
    content = tailor_for_sector("data_analytics")
    assert content.project_entries[0].title == "Algorithmic Trading System"


# ── End-to-end build ──────────────────────────────────────────────────────────


def test_build_writes_docx_with_sector_tag_in_filename(tmp_path: Path) -> None:
    output = tmp_path / "cv_test.docx"
    saved = build("data_analytics", output)
    assert saved == output
    assert output.exists()
    assert output.stat().st_size > 1000  # docx isn't tiny


def test_default_output_includes_sector_tag() -> None:
    from build_cv import default_output_path

    path = default_output_path("fintech_lending")
    assert "fintech_lending" in path.name


# ── CV quality checks ────────────────────────────────────────────────────────


def test_quality_check_passes_for_tailored_data_analytics_cv() -> None:
    content = tailor_for_sector("data_analytics")
    output_path = Path("Harry_Winter_CV_2026_data_analytics.docx")
    report = check_cv(content, output_path)
    assert report.all_passed, report.summary()
    assert report.total == len(CV_CHECK_NAMES)


@pytest.mark.parametrize("sector", SECTORS)
def test_quality_check_passes_for_every_sector(sector: str) -> None:
    content = tailor_for_sector(sector)
    output_path = Path(f"Harry_Winter_CV_2026_{sector}.docx")
    report = check_cv(content, output_path)
    assert report.all_passed, f"Sector {sector}: {report.summary()}"


def test_word_budget_check_fails_when_blown(monkeypatch: pytest.MonkeyPatch) -> None:
    from quality import _CV_WORD_BUDGET

    content = tailor_for_sector("data_analytics")
    # Inject a giant bullet to blow the budget.
    huge = Entry(title="x", org="y", dates="z", bullets=("word " * (_CV_WORD_BUDGET + 100),))
    content.project_entries.append(huge)
    report = check_cv(content, Path("Harry_Winter_CV_2026_data_analytics.docx"))
    failed = {c.name for c in report.failed()}
    assert "word_count_within_budget" in failed


def test_missing_section_fails() -> None:
    content = tailor_for_sector("data_analytics")
    content.experience_entries = []  # wipe experience
    report = check_cv(content, Path("Harry_Winter_CV_2026_data_analytics.docx"))
    failed = {c.name for c in report.failed()}
    assert "all_sections_present" in failed


def test_em_dash_in_bullet_fails() -> None:
    content = tailor_for_sector("data_analytics")
    bad = Entry(title="bad", org="x", dates="2026", bullets=("Em-dash here — like this",))
    content.project_entries.append(bad)
    report = check_cv(content, Path("Harry_Winter_CV_2026_data_analytics.docx"))
    # Will fail both em_dash check AND fabrication check (bullet not in catalog)
    failed = {c.name for c in report.failed()}
    assert "no_em_dashes" in failed
    assert "all_bullets_from_catalog" in failed


def test_quant_jargon_in_bullet_fails() -> None:
    content = tailor_for_sector("data_analytics")
    bad = Entry(title="bad", org="x", dates="2026", bullets=("Implementation uses NSGA-III for search",))
    content.project_entries.append(bad)
    report = check_cv(content, Path("Harry_Winter_CV_2026_data_analytics.docx"))
    failed = {c.name for c in report.failed()}
    assert "no_quant_jargon" in failed


def test_filename_without_sector_tag_fails() -> None:
    content = tailor_for_sector("data_analytics")
    report = check_cv(content, Path("Harry_Winter_CV.docx"))
    failed = {c.name for c in report.failed()}
    assert "filename_has_sector_tag" in failed


def test_lead_project_mismatch_fails() -> None:
    """If we swap project order so the wrong one leads, check 9 catches it."""
    content = tailor_for_sector("data_analytics")
    # data_analytics expects trading_system to lead; swap order
    content.project_entries.reverse()
    report = check_cv(content, Path("Harry_Winter_CV_2026_data_analytics.docx"))
    failed = {c.name for c in report.failed()}
    assert "lead_project_matches_sector" in failed


def test_off_catalog_bullet_fails_fabrication_check() -> None:
    content = tailor_for_sector("data_analytics")
    bad = Entry(
        title="Algorithmic Trading System",
        org="x", dates="2026",
        bullets=("Used proprietary in-house framework not in any catalog",),
    )
    content.project_entries[0] = bad
    report = check_cv(content, Path("Harry_Winter_CV_2026_data_analytics.docx"))
    failed = {c.name for c in report.failed()}
    assert "all_bullets_from_catalog" in failed


def test_extra_technical_skill_fails_allowlist() -> None:
    content = tailor_for_sector("data_analytics")
    content.skills_technical = content.skills_technical + "  ·  Rust  ·  Kubernetes"
    report = check_cv(content, Path("Harry_Winter_CV_2026_data_analytics.docx"))
    failed = {c.name for c in report.failed()}
    assert "skills_within_allowlist" in failed
