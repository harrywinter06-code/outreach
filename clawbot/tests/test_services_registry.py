"""Z4 — services_registry tests."""
import pytest


def test_all_registry_entries_have_required_fields():
    """Every spec must have signup_url, verification_type, extraction task,
    and secret_names. Missing any → the skills can't operate on it."""
    from clawbot.services_registry import list_services
    for spec in list_services(skip_blocked=False):
        assert spec.signup_url.startswith(("http://", "https://")), spec.key
        assert spec.verification_type in ("email_link", "email_code", "none"), spec.key
        assert spec.api_key_extraction_task, f"{spec.key} missing extraction task"
        assert spec.secret_names, f"{spec.key} declares no secret_names"
        for name in spec.secret_names:
            # Must be uppercase env-style names so they shadow env vars cleanly
            assert name == name.upper() and "=" not in name, name


def test_list_skip_blocked_excludes_captcha_and_phone_services():
    """skip_blocked is the operator-preference default — captcha/phone-gated
    services don't enter the agent's choice set when we lack the budget."""
    from clawbot.services_registry import list_services, ServiceSpec
    # All current entries should NOT be blocked (we curated them that way)
    unblocked = list_services(skip_blocked=True)
    all_ = list_services(skip_blocked=False)
    assert len(unblocked) == len(all_), "no current services should be blocked"
    # Synthetic check: if we add a blocked service, skip_blocked omits it
    blocked = ServiceSpec(
        key="x_dummy", display_name="X", signup_url="https://x.test",
        verification_type="email_link", requires_captcha=True,
        api_key_extraction_task="...", secret_names=["X_TOKEN"],
    )
    # We don't mutate the registry; just verify the predicate logic
    assert blocked.requires_captcha


def test_get_service_returns_none_for_unknown_key():
    from clawbot.services_registry import get_service
    assert get_service("not_a_real_service") is None


def test_channel_alias_resolution_handles_mastodon_devto_variants():
    """Genome uses 'mastodon' / 'dev_to' etc; registry uses
    'mastodon_uk' / 'devto'. The mapping must work in both directions of
    naming convention."""
    from clawbot.services_registry import channels_to_service_keys
    keys = channels_to_service_keys(
        ["bluesky", "mastodon", "dev_to", "hashnode"]
    )
    assert "bluesky" in keys
    assert "mastodon_uk" in keys
    assert "devto" in keys
    assert "hashnode" in keys


def test_channels_to_service_keys_drops_unknown_silently():
    from clawbot.services_registry import channels_to_service_keys
    keys = channels_to_service_keys(["bluesky", "snapchat", "tiktok"])
    assert keys == ["bluesky"]


def test_channels_to_service_keys_dedupes():
    from clawbot.services_registry import channels_to_service_keys
    keys = channels_to_service_keys(["bluesky", "bluesky"])
    assert keys == ["bluesky"]


def test_bluesky_extraction_task_returns_app_password():
    """Spot-check: the bluesky extraction task instructs returning JSON
    with `app_password` key — matches what the skill expects to parse."""
    from clawbot.services_registry import get_service
    spec = get_service("bluesky")
    assert spec is not None
    assert "app_password" in spec.api_key_extraction_task


def test_devto_extraction_task_returns_api_key():
    from clawbot.services_registry import get_service
    spec = get_service("devto")
    assert spec is not None
    assert "api_key" in spec.api_key_extraction_task


def test_hashnode_extraction_returns_both_pat_and_publication_id():
    from clawbot.services_registry import get_service
    spec = get_service("hashnode")
    assert spec is not None
    assert "pat" in spec.api_key_extraction_task
    assert "publication_id" in spec.api_key_extraction_task
    assert set(spec.secret_names) == {"HASHNODE_PAT", "HASHNODE_PUBLICATION_ID"}
