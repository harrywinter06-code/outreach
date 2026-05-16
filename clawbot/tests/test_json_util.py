import pytest
from clawbot.json_util import extract_json


def test_extracts_plain_json():
    result = extract_json('{"action": "hire", "priority": "high"}')
    assert result == {"action": "hire", "priority": "high"}


def test_strips_markdown_json_fence():
    text = '```json\n{"action": "wait"}\n```'
    result = extract_json(text)
    assert result == {"action": "wait"}


def test_strips_plain_code_fence():
    text = '```\n{"x": 1}\n```'
    result = extract_json(text)
    assert result == {"x": 1}


def test_extracts_json_from_surrounding_text():
    text = 'Here is my decision: {"action": "hire"} — that is all.'
    result = extract_json(text)
    assert result == {"action": "hire"}


def test_raises_on_no_json_object():
    with pytest.raises(ValueError, match="no JSON object found"):
        extract_json("no json here at all")


def test_raises_on_malformed_json():
    with pytest.raises(Exception):
        extract_json('{"broken": }')


def test_returns_last_complete_object():
    """When text has surrounding content, gets the outermost object."""
    text = 'thinking... {"result": "done", "count": 3} end'
    result = extract_json(text)
    assert result["result"] == "done"
    assert result["count"] == 3
