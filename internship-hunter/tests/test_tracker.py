"""Schema creation, round-trip persistence, and idempotency."""

from __future__ import annotations

import tracker


def test_schema_creates_expected_tables() -> None:
    tracker.init_db()
    with tracker.get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = {row["name"] for row in rows}
    expected = {"applications", "companies", "domain_patterns", "email_queue", "jobs"}
    assert expected.issubset(names), f"missing tables: {expected - names}"


def test_insert_job_round_trip() -> None:
    job_id, is_new = tracker.insert_job(
        title="Data Intern",
        company="Acme",
        location="London",
        url="https://example.test/jobs/data-intern",
        source="UnitTest",
        description="Build data pipelines.",
        salary="£30k",
    )
    assert is_new is True
    assert job_id > 0

    jobs = [j for j in tracker.get_jobs() if j["id"] == job_id]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Data Intern"
    assert job["company"] == "Acme"
    assert job["status"] == "new"


def test_insert_job_idempotent_by_url() -> None:
    url = "https://example.test/jobs/dup"
    first_id, first_new = tracker.insert_job(
        title="First Title", company="Acme", location="London",
        url=url, source="UnitTest", description="", salary="",
    )
    second_id, second_new = tracker.insert_job(
        title="Different Title", company="Acme", location="London",
        url=url, source="UnitTest", description="", salary="",
    )
    assert first_new is True
    assert second_new is False
    assert first_id == second_id


def test_upsert_company_returns_same_id_when_existing() -> None:
    first_id  = tracker.upsert_company("DupCo", website="dup.co", sector="Data")
    second_id = tracker.upsert_company("DupCo", website="ignored.co", sector="Other")
    assert first_id == second_id


def test_queue_email_idempotent_while_active() -> None:
    company_id = tracker.upsert_company("QueueCo")
    first = tracker.queue_email(
        company="QueueCo",
        contact_name="Alice Doe",
        contact_email="alice@queue.co",
        subject="hello",
        body="body",
        company_id=company_id,
    )
    second = tracker.queue_email(
        company="QueueCo",
        contact_name="Alice Doe",
        contact_email="alice@queue.co",
        subject="hello",
        body="body",
        company_id=company_id,
    )
    assert first == second


def test_update_queue_item_changes_fields() -> None:
    queue_id = tracker.queue_email(
        company="UpdateCo",
        contact_name="Bob",
        contact_email="bob@update.co",
        subject="s",
        body="b",
    )
    tracker.update_queue_item(queue_id, subject="new-subject", body="new-body")
    queued = [q for q in tracker.get_email_queue() if q["id"] == queue_id]
    assert queued[0]["subject"] == "new-subject"
    assert queued[0]["body"] == "new-body"


def test_approve_email_sets_status() -> None:
    queue_id = tracker.queue_email(
        company="ApproveCo",
        contact_name="Carol",
        contact_email="carol@approve.co",
        subject="s", body="b",
    )
    tracker.approve_email(queue_id)
    approved = tracker.get_email_queue(status="approved")
    assert any(row["id"] == queue_id for row in approved)


def test_score_company_returns_lowest_tier_for_empty_dict() -> None:
    score, tier = tracker.score_company({})
    assert 0 <= score < 90
    assert tier in {"D", "C", "B"}


def test_score_company_rewards_ucl_alumni_and_seniority() -> None:
    weak, weak_tier = tracker.score_company({"name": "Weak"})
    strong, strong_tier = tracker.score_company({
        "name": "Strong",
        "has_ucl_alumni": True,
        "contact_first": "Jane",
        "contact_title": "Founder",
        "contact_email": "jane@strong.co",
        "contact_confidence": 95,
        "sector": "quant trading",
        "size": "11-50",
        "research_context": "Builds risk models.",
    })
    assert strong > weak
    assert strong_tier in {"S", "A"}
    assert weak_tier in {"D", "C"}


def test_domain_pattern_cache_roundtrip() -> None:
    tracker.cache_domain_pattern("example.test", "{first}.{last}@example.test")
    assert tracker.get_cached_pattern("example.test") == "{first}.{last}@example.test"
    assert tracker.get_cached_pattern("missing.test") == ""


def test_log_application_marks_job_applied() -> None:
    job_id, _ = tracker.insert_job(
        title="Analyst",
        company="ApplyCo",
        location="London",
        url="https://example.test/jobs/apply",
        source="UnitTest",
    )
    app_id = tracker.log_application(job_id, "ApplyCo", "Analyst")
    assert app_id > 0
    job = next(j for j in tracker.get_jobs() if j["id"] == job_id)
    assert job["status"] == "applied"
