"""Builtin dev/infra pack — pack-load + representative call tests, plus ctx.dev surface checks."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from clawbot.skill_registry import SkillRegistry
from clawbot.skill_ctx import (
    make_noop_ctx, _LiveDev, _NoopDev,
    _DEV_ALLOWED_COMMANDS,
)

BUILTIN_DIR = Path(__file__).parent.parent / "agents" / "skills" / "_builtin"


def _registry() -> SkillRegistry:
    reg = SkillRegistry(skills_dir=BUILTIN_DIR)
    reg.discover()
    return reg


DEV_SKILLS = {
    "github_create_repo", "github_create_release", "github_star_repo",
    "github_search_issues",
    "npm_publish", "pypi_publish", "docker_build_and_push",
    "dns_set_record", "dns_verify_propagation", "ssl_check_expiry",
    "domain_check_availability", "domain_register",
    "cloudflare_purge_cache", "cloudflare_deploy_pages_site",
}


def test_dev_pack_loads():
    reg = _registry()
    loaded = set(reg.list_names())
    missing = DEV_SKILLS - loaded
    assert not missing, f"missing dev skills: {missing}"


def test_github_create_repo_routes_to_http():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0.0)
    ctx.http.post = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 201,
        "text": json.dumps({
            "clone_url": "https://github.com/owner/repo.git",
            "html_url": "https://github.com/owner/repo",
        }),
        "headers": {},
    })
    record = asyncio.run(reg.call("github_create_repo", {
        "name": "repo", "description": "test", "private": False,
    }, ctx))
    assert record.ok is True
    assert record.result["clone_url"].endswith("repo.git")


def test_dns_verify_propagation_matches():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0.0)
    ctx.http.get = AsyncMock(return_value={  # type: ignore[method-assign]
        "status": 200,
        "text": json.dumps({"Answer": [{"data": "203.0.113.1"}]}),
        "headers": {},
    })
    record = asyncio.run(reg.call("dns_verify_propagation", {
        "name": "example.com", "record_type": "A",
        "expected_value": "203.0.113.1",
    }, ctx))
    assert record.ok is True
    assert record.result["matches"] is True
    assert "203.0.113.1" in record.result["answers"]


def test_domain_register_requires_approval_meta():
    reg = _registry()
    meta = reg.get_meta("domain_register")
    assert meta is not None
    assert meta.requires_approval is True


def test_npm_publish_routes_to_dev_exec():
    reg = _registry()
    ctx = make_noop_ctx(caller_id="cto", budget_usd=0.0)
    ctx.dev.exec_allowed_command = AsyncMock(return_value={  # type: ignore[method-assign]
        "stdout": "+ pkg@1.2.3", "stderr": "", "returncode": 0,
    })
    record = asyncio.run(reg.call("npm_publish", {
        "cwd": "/some/build/dir", "extra_args": ["--access", "public"],
    }, ctx))
    assert record.ok is True
    assert record.result["returncode"] == 0
    kwargs = ctx.dev.exec_allowed_command.call_args.kwargs
    assert kwargs["cmd_name"] == "npm_publish"
    assert kwargs["args"] == ["--access", "public"]


def test_dev_allowlist_rejects_unknown_command(tmp_path):
    dev = _LiveDev(allowed_root=str(tmp_path))
    with pytest.raises(PermissionError, match="not in allowlist"):
        asyncio.run(dev.exec_allowed_command(
            cmd_name="rm_rf", args=["/"], cwd=str(tmp_path),
        ))


def test_dev_allowlist_rejects_cwd_outside_root(tmp_path):
    dev = _LiveDev(allowed_root=str(tmp_path))
    # Pick a path that we know exists but is outside tmp_path.
    outside = os.path.abspath(os.sep)
    with pytest.raises(PermissionError, match="cwd outside"):
        asyncio.run(dev.exec_allowed_command(
            cmd_name="npm_publish", args=[], cwd=outside,
        ))


def test_noop_dev_returns_zeroed_payload():
    dev = _NoopDev()
    result = asyncio.run(dev.exec_allowed_command(
        cmd_name="npm_publish", args=[], cwd="/anything",
    ))
    assert result["returncode"] == 0
    assert result["stdout"] == ""


def test_allowed_commands_match_documented_set():
    expected = {
        "npm_publish", "pip_wheel", "twine_upload",
        "docker_build", "docker_push", "docker_tag",
        "git_push", "git_clone",
    }
    assert _DEV_ALLOWED_COMMANDS == expected
