import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from clawbot.coder import (
    CTOCoder, _parse_file_blocks, _is_protected, _sha256,
    PROTECTED_FILES, PROTECTED_GLOBS, MAX_FILE_LINES, CHARTER_PATH,
)


def _mock_pool(response: str = "===FILE: src/clawbot/example.py===\n# new\n===END===") -> MagicMock:
    pool = MagicMock()
    pool.complete = AsyncMock(return_value=response)
    return pool


def _mock_bus() -> MagicMock:
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.read_and_ack = AsyncMock(return_value=[])
    bus.publish = AsyncMock()
    return bus


def _req(files: list[str], description: str = "Add a comment") -> dict:
    return {
        "description": description,
        "files": files,
        "motivation": "test",
        "requested_by": "ceo",
    }


# ── Protected file guard ────────────────────────────────────────────────────


def test_protected_files_includes_safety_critical_modules():
    """Hardened set: evolution, genome, fitness, board, scheduler, agent_registry."""
    assert "src/clawbot/evolution.py" in PROTECTED_FILES
    assert "src/clawbot/genome.py" in PROTECTED_FILES
    assert "src/clawbot/fitness.py" in PROTECTED_FILES
    assert "src/clawbot/board.py" in PROTECTED_FILES
    assert "src/clawbot/scheduler.py" in PROTECTED_FILES
    assert "src/clawbot/agent_registry.py" in PROTECTED_FILES
    assert "CORPORATE_CHARTER.md" in PROTECTED_FILES


def test_is_protected_matches_explicit_set():
    assert _is_protected("src/clawbot/monitor.py") is True
    assert _is_protected("src/clawbot/coder.py") is True
    assert _is_protected("CORPORATE_CHARTER.md") is True


def test_is_protected_matches_soul_glob():
    assert _is_protected("agents/ceo/SOUL.md") is True
    assert _is_protected("agents/content-writer-001/SOUL.md") is True
    assert _is_protected("agents/cto/SOUL.candidate.md") is True


def test_is_protected_handles_windows_path_separators():
    assert _is_protected("src\\clawbot\\monitor.py") is True
    assert _is_protected("agents\\ceo\\SOUL.md") is True


def test_is_protected_false_for_writable_file():
    assert _is_protected("src/clawbot/llm_pool.py") is False
    assert _is_protected("src/clawbot/example.py") is False


def test_protected_globs_includes_soul_files():
    assert "agents/**/SOUL.md" in PROTECTED_GLOBS


# ── Request handling ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_protected_file_rejected_in_request(tmp_path):
    pool = _mock_pool()
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["src/clawbot/monitor.py"]))

    pool.complete.assert_not_called()
    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "protected" in result["detail"].lower()


@pytest.mark.asyncio
async def test_evolution_py_is_rejected(tmp_path):
    """Defeating the meta-evaluator via CTOCoder must fail."""
    pool = _mock_pool()
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["src/clawbot/evolution.py"]))

    result = bus.publish.call_args.args[1]
    assert result["success"] is False


@pytest.mark.asyncio
async def test_soul_md_is_rejected(tmp_path):
    """SOUL.md mutation is the meta-evaluator's job, not the coder's."""
    pool = _mock_pool()
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["agents/ceo/SOUL.md"]))

    result = bus.publish.call_args.args[1]
    assert result["success"] is False


@pytest.mark.asyncio
async def test_large_file_rejected(tmp_path):
    large = tmp_path / "src" / "clawbot" / "big.py"
    large.parent.mkdir(parents=True, exist_ok=True)
    large.write_text(("\n" * (MAX_FILE_LINES + 1)), encoding="utf-8")

    pool = _mock_pool()
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["src/clawbot/big.py"]))

    pool.complete.assert_not_called()
    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "line limit" in result["detail"].lower()


@pytest.mark.asyncio
async def test_llm_output_targeting_protected_file_rejected(tmp_path):
    """If LLM emits a ===FILE=== block for a protected path the operator didn't request, reject."""
    pool = _mock_pool(
        "===FILE: src/clawbot/example.py===\n# legitimate\n===END===\n"
        "===FILE: src/clawbot/monitor.py===\n# malicious\n===END==="
    )
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["src/clawbot/example.py"]))

    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "protected" in result["detail"].lower()


@pytest.mark.asyncio
async def test_successful_change_writes_file_and_commits(tmp_path):
    target = tmp_path / "src" / "clawbot" / "example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# old content", encoding="utf-8")

    pool = _mock_pool("===FILE: src/clawbot/example.py===\n# new content\n===END===")
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    with patch.object(coder, "_run_tests", return_value=True), \
         patch.object(coder, "_git_commit") as mock_commit:
        await coder._handle_request(_req(["src/clawbot/example.py"]))

    assert target.read_text(encoding="utf-8") == "# new content\n"
    mock_commit.assert_called_once()
    result = bus.publish.call_args.args[1]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_failed_tests_reverts_and_reports_failure(tmp_path):
    target = tmp_path / "src" / "clawbot" / "example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# old", encoding="utf-8")

    pool = _mock_pool("===FILE: src/clawbot/example.py===\n# broken\n===END===")
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    with patch.object(coder, "_run_tests", return_value=False), \
         patch.object(coder, "_git_revert") as mock_revert:
        await coder._handle_request(_req(["src/clawbot/example.py"]))

    mock_revert.assert_called_once()
    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "reverted" in result["detail"].lower()


@pytest.mark.asyncio
async def test_charter_hash_mismatch_after_passing_tests_triggers_revert(tmp_path):
    """If the charter file is somehow modified during a change, revert even though tests passed."""
    (tmp_path / CHARTER_PATH).write_text("Original charter contents", encoding="utf-8")
    target = tmp_path / "src" / "clawbot" / "example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# old", encoding="utf-8")

    pool = _mock_pool("===FILE: src/clawbot/example.py===\n# new\n===END===")
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    def _modify_charter_during_tests() -> bool:
        # Simulate a side effect that mutates the charter — should trigger revert.
        (tmp_path / CHARTER_PATH).write_text("TAMPERED", encoding="utf-8")
        return True

    with patch.object(coder, "_run_tests", side_effect=_modify_charter_during_tests), \
         patch.object(coder, "_git_revert") as mock_revert, \
         patch.object(coder, "_git_commit") as mock_commit:
        await coder._handle_request(_req(["src/clawbot/example.py"]))

    mock_commit.assert_not_called()
    mock_revert.assert_called_once()
    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "CORPORATE_CHARTER" in result["detail"]


@pytest.mark.asyncio
async def test_git_commit_failure_publishes_result_and_reverts(tmp_path):
    """If git commit raises (pre-commit hook, identity not set), the caller must
    still see a code.change_result message and the files must be reverted."""
    import subprocess
    target = tmp_path / "src" / "clawbot" / "example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# old", encoding="utf-8")

    pool = _mock_pool("===FILE: src/clawbot/example.py===\n# new\n===END===")
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    fail = subprocess.CalledProcessError(returncode=1, cmd=["git", "commit"], stderr=b"pre-commit hook failed")
    with patch.object(coder, "_run_tests", return_value=True), \
         patch.object(coder, "_git_commit", side_effect=fail), \
         patch.object(coder, "_git_revert") as mock_revert:
        await coder._handle_request(_req(["src/clawbot/example.py"]))

    mock_revert.assert_called_once()
    bus.publish.assert_called()  # critical — caller must hear back even on git failure
    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "git commit failed" in result["detail"].lower()


@pytest.mark.asyncio
async def test_llm_no_file_blocks_reports_failure(tmp_path):
    pool = _mock_pool("I couldn't figure out the change, sorry.")
    bus = _mock_bus()
    coder = CTOCoder(pool=pool, bus=bus, repo_root=tmp_path)

    await coder._handle_request(_req(["src/clawbot/example.py"]))

    result = bus.publish.call_args.args[1]
    assert result["success"] is False
    assert "parseable" in result["detail"].lower()


# ── Block parser ────────────────────────────────────────────────────────────


def test_parse_file_blocks_single():
    response = "===FILE: src/foo.py===\nprint('hello')\n===END==="
    result = _parse_file_blocks(response)
    assert result == {"src/foo.py": "print('hello')\n"}


def test_parse_file_blocks_multiple():
    response = (
        "===FILE: a.py===\nprint('a')\n===END===\n"
        "===FILE: b.py===\nprint('b')\n===END==="
    )
    result = _parse_file_blocks(response)
    assert set(result.keys()) == {"a.py", "b.py"}


def test_parse_file_blocks_no_match():
    assert _parse_file_blocks("no markers here") == {}


# ── SHA256 helper ───────────────────────────────────────────────────────────


def test_sha256_matches_stdlib(tmp_path):
    f = tmp_path / "x"
    f.write_text("hello", encoding="utf-8")
    assert _sha256(f) == hashlib.sha256(b"hello").hexdigest()


# ── Governance split ─────────────────────────────────────────────────────────


def test_coder_unaffected_by_skill_dir_changes():
    """Writes to agents/skills/, agents/workers/, workspace/, data/ never reach coder.

    Coder only consumes code.change_request bus messages. Skill writes happen
    via fs.write skill or direct file authorship — they never publish to
    code.change_request, so coder is not on the path. This test confirms.
    """
    from clawbot.coder import _is_protected
    # Skill files are NOT protected — they're a different governance surface
    assert _is_protected("agents/skills/_builtin/http_fetch.py") is False
    assert _is_protected("agents/skills/weather_check.py") is False
    # agents/**/SOUL.md now uses fnmatch so all depths are protected
    assert _is_protected("agents/ceo/SOUL.md") is True
    assert _is_protected("agents/workers/researcher-001/SOUL.md") is True
    assert _is_protected("workspace/scratch.txt") is False
    assert _is_protected("data/observations.jsonl") is False

    # Source code remains protected via the existing list
    assert _is_protected("src/clawbot/monitor.py") is True
    assert _is_protected("src/clawbot/coder.py") is True
