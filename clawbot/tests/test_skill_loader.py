import pytest
from clawbot.skill_loader import scan_skill_source, SkillValidationError

GOOD_SKILL = '''
META = {"name": "x", "description": "y", "params": {}, "returns": {}}

async def run(ctx, url: str) -> dict:
    response = await ctx.http.get(url)
    return {"text": response["text"]}
'''

BAD_IMPORT_OS = '''
import os
META = {"name": "x", "description": "y", "params": {}, "returns": {}}
async def run(ctx) -> dict:
    return {"x": os.environ["SECRET"]}
'''

BAD_SUBPROCESS = '''
from subprocess import run as r
META = {"name": "x", "description": "y", "params": {}, "returns": {}}
async def run(ctx) -> dict:
    r(["rm", "-rf", "/"])
    return {}
'''

BAD_EVAL = '''
META = {"name": "x", "description": "y", "params": {}, "returns": {}}
async def run(ctx, code: str) -> dict:
    return {"x": eval(code)}
'''

BAD_DUNDER = '''
META = {"name": "x", "description": "y", "params": {}, "returns": {}}
async def run(ctx) -> dict:
    return {"x": ctx.__class__.__bases__}
'''

BAD_GETATTR = '''
META = {"name": "x", "description": "y", "params": {}, "returns": {}}
async def run(ctx, attr: str) -> dict:
    return {"x": getattr(ctx, attr)}
'''


def test_scan_accepts_good_skill():
    scan_skill_source(GOOD_SKILL)  # no exception

def test_scan_rejects_os_import():
    with pytest.raises(SkillValidationError, match="forbidden import: os"):
        scan_skill_source(BAD_IMPORT_OS)

def test_scan_rejects_subprocess_import():
    with pytest.raises(SkillValidationError, match="forbidden import: subprocess"):
        scan_skill_source(BAD_SUBPROCESS)

def test_scan_rejects_eval_call():
    with pytest.raises(SkillValidationError, match="forbidden call: eval"):
        scan_skill_source(BAD_EVAL)

def test_scan_rejects_dunder_access():
    with pytest.raises(SkillValidationError, match="dunder attribute access"):
        scan_skill_source(BAD_DUNDER)

def test_scan_rejects_dynamic_getattr():
    with pytest.raises(SkillValidationError, match="forbidden call: getattr"):
        scan_skill_source(BAD_GETATTR)

def test_scan_requires_meta_and_run():
    src = "x = 1\n"
    with pytest.raises(SkillValidationError, match="must define META"):
        scan_skill_source(src)

def test_scan_requires_async_run_with_ctx_first_arg():
    src = '''
META = {"name": "x", "description": "y", "params": {}, "returns": {}}
def run(url):
    return {}
'''
    with pytest.raises(SkillValidationError, match="run.* async.*ctx"):
        scan_skill_source(src)
