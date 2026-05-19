"""
Z4 — registry of services the agent can sign itself up for.

The agent's `account_create_from_registry(service_key)` skill consults
this registry to know:
- The signup URL
- Service-specific browser-use task customisation (e.g. Bluesky needs a
  generated handle name; Hashnode asks for a display name)
- Whether the service requires CAPTCHA / phone (in which case we skip
  outright rather than waste cycles)
- How to extract the API key / app password POST-signup
- Which env var name the resulting secret should be stored as

Registry is hand-curated. New services need careful research of the
signup flow before being added — wrong instructions cause `_LiveAccounts`
to flail browser cycles.

Anti-fragility note: we deliberately favor services whose signup is
email-only and CAPTCHA-free, since headless-browser CAPTCHA solving is
either expensive (2Captcha) or unreliable. Per operator decision, we
do NOT carry a CAPTCHA budget; CAPTCHA-gated services stay
operator-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ServiceSpec:
    key: str                              # registry key (lowercase_snake)
    display_name: str                     # human-readable
    signup_url: str                       # where browser-use lands
    verification_type: str                # "email_link" | "email_code" | "none"
    requires_captcha: bool = False        # if True: skip (no budget)
    requires_phone: bool = False          # if True: skip
    signup_task_extra: str = ""           # extra instructions for browser-use
    # Post-signup credential extraction. browser-use is logged into the
    # account; this task instructs it where to find the API key/app password.
    api_key_extraction_task: str = ""
    # The secret name(s) to store the extracted value(s) under. If multiple,
    # the extraction task must return them as JSON in the browser output.
    secret_names: list[str] = field(default_factory=list)
    # Optional check: a URL that should return 200 when logged in. Used by
    # downstream skills to confirm the credential still works.
    health_check_url: str = ""
    notes: str = ""


_REGISTRY: dict[str, ServiceSpec] = {
    "bluesky": ServiceSpec(
        key="bluesky",
        display_name="Bluesky",
        signup_url="https://bsky.app/signup",
        verification_type="email_code",
        signup_task_extra=(
            "Bluesky asks for a handle name; pick `clawbot-{rand4}` where "
            "{rand4} is 4 random lowercase letters and digits. Pick a year "
            "of birth in the 1990s. The verification is a 6-character code "
            "emailed to the address you provided."
        ),
        api_key_extraction_task=(
            "Navigate to https://bsky.app/settings/app-passwords. Click "
            "'Add App Password'. Name it 'clawbot-publisher'. Copy the "
            "generated password (format `xxxx-xxxx-xxxx-xxxx`). Return "
            "ONLY the password as JSON: {\"app_password\": \"<the password>\"}."
        ),
        secret_names=["BSKY_HANDLE", "BSKY_APP_PASSWORD"],
        health_check_url="https://bsky.app/profile/me",
        notes="Email-only signup, no CAPTCHA at sign-up. App-password "
              "model means we never store the master password long-term.",
    ),
    "mastodon_uk": ServiceSpec(
        key="mastodon_uk",
        display_name="Mastodon (mastodon.uk instance)",
        signup_url="https://mastodon.uk/auth/sign_up",
        verification_type="email_link",
        signup_task_extra=(
            "mastodon.uk needs username + email + password. Pick username "
            "`clawbot{rand3}` where {rand3} is 3 digits. Agree to server "
            "rules checkbox. After submit, expect a 'check your email' page; "
            "verification is a link in the email — click it to confirm."
        ),
        api_key_extraction_task=(
            "Navigate to https://mastodon.uk/settings/applications. Click "
            "'New application'. Name: 'clawbot-publisher'. Scopes: tick "
            "'write:statuses'. Submit. On the resulting application page, "
            "copy the 'Your access token' value. Return as JSON: "
            "{\"access_token\": \"<the token>\"}."
        ),
        secret_names=["MASTODON_INSTANCE", "MASTODON_ACCESS_TOKEN"],
        health_check_url="https://mastodon.uk/api/v1/accounts/verify_credentials",
        notes="mastodon.uk is a UK-focused instance, lower bot-detection "
              "than mastodon.social (which is approval-gated). Access tokens "
              "don't expire by default.",
    ),
    "devto": ServiceSpec(
        key="devto",
        display_name="Dev.to",
        signup_url="https://dev.to/enter",
        verification_type="email_link",
        signup_task_extra=(
            "Dev.to's primary signup paths are OAuth (GitHub, Twitter, "
            "Google, Apple, Forem). Click the 'Continue with email' option "
            "if present; otherwise click 'Continue with GitHub' as a "
            "fallback. The email path needs username + email + password; "
            "verification is via emailed link."
        ),
        api_key_extraction_task=(
            "Navigate to https://dev.to/settings/extensions. Scroll to 'DEV "
            "Community API Keys'. Enter description 'clawbot' and click "
            "'Generate API Key'. Copy the generated key. Return as JSON: "
            "{\"api_key\": \"<the key>\"}."
        ),
        secret_names=["DEVTO_API_KEY"],
        health_check_url="https://dev.to/api/users/me",
        notes="Email signup path may not always be available. If signup "
              "lands on OAuth-only, mark zombie with reason='oauth_required' "
              "so the operator can decide whether to provide a GitHub account.",
    ),
    "hashnode": ServiceSpec(
        key="hashnode",
        display_name="Hashnode",
        signup_url="https://hashnode.com/signup",
        verification_type="email_link",
        signup_task_extra=(
            "Hashnode signup needs name + email + password + username. Pick "
            "username `clawbot{rand4}`. Verification is a link in the welcome "
            "email. After verification, Hashnode asks you to create a "
            "publication — name it after the business niche and set the "
            "domain to '{username}.hashnode.dev'."
        ),
        api_key_extraction_task=(
            "Navigate to https://hashnode.com/settings/developer. Click "
            "'Generate New Token'. Name it 'clawbot-publisher'. Copy the "
            "Personal Access Token (PAT). Then navigate to your publication "
            "settings and copy the publication ID (visible in the URL or "
            "publication dashboard as a 24-char hex string). Return as "
            "JSON: {\"pat\": \"<token>\", \"publication_id\": \"<id>\"}."
        ),
        secret_names=["HASHNODE_PAT", "HASHNODE_PUBLICATION_ID"],
        health_check_url="https://api.hashnode.com/",
        notes="Hashnode's GraphQL API needs both a PAT and a publication ID. "
              "Publication creation is part of the signup flow; the API key "
              "extraction step assumes it exists.",
    ),
}


def get_service(key: str) -> ServiceSpec | None:
    return _REGISTRY.get(key)


def list_services(*, skip_blocked: bool = True) -> list[ServiceSpec]:
    """Return all services, optionally excluding those we can't automate
    (CAPTCHA or phone-gated)."""
    out = list(_REGISTRY.values())
    if skip_blocked:
        out = [s for s in out if not s.requires_captcha and not s.requires_phone]
    return out


def is_supported_channel(channel: str) -> bool:
    """True if `channel` (a genome.channels entry) maps to a registry entry
    the agent can auto-sign-up for."""
    return _channel_to_service_key(channel) is not None


def _channel_to_service_key(channel: str) -> str | None:
    """Map a genome.channels token to a registry key. Genome uses tokens like
    'bluesky', 'mastodon', 'dev_to' — registry uses 'bluesky', 'mastodon_uk',
    'devto'. This is the only place we paper over the mismatch; cleaning up
    the genome vocabulary is a Z5+ concern."""
    c = channel.lower().replace("-", "_")
    if c in _REGISTRY:
        return c
    aliases = {
        "mastodon": "mastodon_uk",
        "dev_to": "devto",
        "dev.to": "devto",
    }
    return aliases.get(c)


def channels_to_service_keys(channels: list[str]) -> list[str]:
    """Resolve a genome's channel list to registry keys. Unknown channels
    are silently dropped; caller can compare lengths to detect mismatches."""
    out = []
    seen = set()
    for ch in channels:
        key = _channel_to_service_key(ch)
        if key and key not in seen:
            out.append(key)
            seen.add(key)
    return out
