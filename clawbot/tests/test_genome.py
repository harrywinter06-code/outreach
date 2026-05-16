import pytest
import tempfile
from pathlib import Path
from clawbot.genome import (
    read_soul, write_soul, extract_mutable, replace_mutable,
    mutate_soul, section_names,
)

SAMPLE_SOUL = """\
## IMMUTABLE

I am the CFO. I track money.

## MUTABLE

### current_thesis
Revenue via consulting.

### recent_observations
Nothing yet.
"""


def _soul_file(content: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def test_read_soul():
    p = _soul_file(SAMPLE_SOUL)
    assert "I am the CFO" in read_soul(p)


def test_write_soul_is_atomic(tmp_path):
    p = tmp_path / "SOUL.md"
    write_soul(p, SAMPLE_SOUL)
    assert p.read_text(encoding="utf-8") == SAMPLE_SOUL


def test_write_soul_overwrites_existing(tmp_path):
    p = tmp_path / "SOUL.md"
    write_soul(p, "old content")
    write_soul(p, SAMPLE_SOUL)
    assert p.read_text(encoding="utf-8") == SAMPLE_SOUL


def test_write_soul_no_temp_file_left_behind(tmp_path):
    p = tmp_path / "SOUL.md"
    write_soul(p, SAMPLE_SOUL)
    temp_files = list(tmp_path.glob(".soul_tmp_*"))
    assert temp_files == []


def test_extract_mutable_returns_mutable_section():
    mutable = extract_mutable(SAMPLE_SOUL)
    assert mutable.startswith("## MUTABLE")
    assert "I am the CFO" not in mutable
    assert "current_thesis" in mutable


def test_extract_mutable_raises_on_no_mutable_section():
    with pytest.raises(ValueError, match="no ## MUTABLE section"):
        extract_mutable("## IMMUTABLE\n\nOnly immutable content here.")


def test_replace_mutable_preserves_immutable():
    new_mutable = "## MUTABLE\n\n### current_thesis\nNew thesis.\n"
    result = replace_mutable(SAMPLE_SOUL, new_mutable)
    assert "I am the CFO" in result
    assert "New thesis." in result
    assert "Revenue via consulting" not in result


def test_mutate_soul_writes_new_mutable(tmp_path):
    p = tmp_path / "SOUL.md"
    write_soul(p, SAMPLE_SOUL)
    new_mutable = "## MUTABLE\n\n### current_thesis\nPivot to SaaS.\n"
    mutate_soul(p, new_mutable)
    result = p.read_text(encoding="utf-8")
    assert "Pivot to SaaS" in result
    assert "I am the CFO" in result  # immutable preserved


def test_section_names_finds_all_headers():
    names = section_names(SAMPLE_SOUL)
    assert "IMMUTABLE" in names
    assert "MUTABLE" in names
    assert "current_thesis" in names
    assert "recent_observations" in names


def test_write_soul_retries_on_permission_error(tmp_path, monkeypatch):
    """Windows os.replace can raise PermissionError if target file is open by
    another process. write_soul must retry rather than crash the scheduler."""
    import os
    p = tmp_path / "SOUL.md"
    p.write_text("original", encoding="utf-8")

    attempt = {"count": 0}
    real_replace = os.replace

    def flaky_replace(src, dst):
        attempt["count"] += 1
        if attempt["count"] < 3:
            raise PermissionError("locked by another process")
        return real_replace(src, dst)

    monkeypatch.setattr("clawbot.genome.os.replace", flaky_replace)
    write_soul(p, "new content after retries")
    assert p.read_text(encoding="utf-8") == "new content after retries"
    assert attempt["count"] == 3


def test_write_soul_raises_after_max_retries(tmp_path, monkeypatch):
    """If every retry fails, the original PermissionError propagates."""
    p = tmp_path / "SOUL.md"
    p.write_text("original", encoding="utf-8")
    monkeypatch.setattr(
        "clawbot.genome.os.replace",
        lambda src, dst: (_ for _ in ()).throw(PermissionError("never resolves")),
    )
    with pytest.raises(PermissionError):
        write_soul(p, "wont land")
