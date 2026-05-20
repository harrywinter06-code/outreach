"""Shared Anthropic SDK client.

A single client instance is reused for the lifetime of the process so the
underlying HTTP connection pool and credential is shared across modules.
"""

from __future__ import annotations

import anthropic

from config import require_env

__all__ = ["get_anthropic_client"]


_client: anthropic.Anthropic | None = None


def get_anthropic_client() -> anthropic.Anthropic:
    """Return the process-wide Anthropic client, constructing it on first use."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY", "Claude API calls"))
    return _client
