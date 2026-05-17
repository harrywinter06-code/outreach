"""Per-service Playwright storage_state persistence."""
import json
from pathlib import Path

import pytest

from clawbot.profile_store import ProfileStore


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(root=str(tmp_path / "profiles"))


def test_save_and_load_roundtrip(store: ProfileStore):
    state = {"cookies": [{"name": "session", "value": "abc"}], "origins": []}
    store.save("substack", state)
    loaded = store.load("substack")
    assert loaded == state


def test_load_missing_returns_none(store: ProfileStore):
    assert store.load("never_saved") is None


def test_exists_reflects_saved_state(store: ProfileStore):
    assert store.exists("medium") is False
    store.save("medium", {"cookies": []})
    assert store.exists("medium") is True


def test_save_overwrites_existing(store: ProfileStore):
    store.save("s", {"cookies": [{"name": "old"}]})
    store.save("s", {"cookies": [{"name": "new"}]})
    loaded = store.load("s")
    assert loaded == {"cookies": [{"name": "new"}]}


def test_service_name_path_traversal_rejected(store: ProfileStore):
    """A service name with .. or / must not escape the root."""
    with pytest.raises(ValueError):
        store.save("../etc/passwd", {"cookies": []})
    with pytest.raises(ValueError):
        store.save("foo/bar", {"cookies": []})
