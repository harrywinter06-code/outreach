import pytest
from pathlib import Path
from clawbot.scheduler import _maybe_widget_update
from clawbot.metrics import MetricsStore


@pytest.mark.asyncio
async def test_widget_update_from_valid_json(tmp_path):
    response = '''{
      "action": "grow email list",
      "dashboard_widget": {
        "id": "ceo_focus",
        "type": "text",
        "title": "CEO Focus",
        "content": "Grow email list to 500 subscribers"
      }
    }'''
    await _maybe_widget_update(response, "ceo", tmp_path)
    widgets = MetricsStore(metrics_dir=tmp_path).get_widgets()
    assert len(widgets) == 1
    assert widgets[0].id == "ceo_focus"
    assert widgets[0].agent == "ceo"
    assert "email list" in widgets[0].content


@pytest.mark.asyncio
async def test_widget_update_no_widget_field_is_noop(tmp_path):
    await _maybe_widget_update('{"action": "do something"}', "ceo", tmp_path)
    assert MetricsStore(metrics_dir=tmp_path).get_widgets() == []


@pytest.mark.asyncio
async def test_widget_update_invalid_json_is_noop(tmp_path):
    await _maybe_widget_update("not json at all", "ceo", tmp_path)
    assert MetricsStore(metrics_dir=tmp_path).get_widgets() == []


@pytest.mark.asyncio
async def test_widget_update_missing_id_is_noop(tmp_path):
    response = '{"dashboard_widget": {"type": "text", "title": "T", "content": "c"}}'
    await _maybe_widget_update(response, "ceo", tmp_path)
    assert MetricsStore(metrics_dir=tmp_path).get_widgets() == []


@pytest.mark.asyncio
async def test_widget_update_sets_agent_from_arg(tmp_path):
    response = '{"dashboard_widget": {"id": "cfo_risk", "type": "metric", "title": "Risk", "value": 3.0, "unit": "flags"}}'
    await _maybe_widget_update(response, "cfo", tmp_path)
    widgets = MetricsStore(metrics_dir=tmp_path).get_widgets()
    assert widgets[0].agent == "cfo"


@pytest.mark.asyncio
async def test_widget_update_overwrites_same_id(tmp_path):
    r1 = '{"dashboard_widget": {"id": "ceo_focus", "type": "text", "title": "T", "content": "old"}}'
    r2 = '{"dashboard_widget": {"id": "ceo_focus", "type": "text", "title": "T", "content": "new"}}'
    await _maybe_widget_update(r1, "ceo", tmp_path)
    await _maybe_widget_update(r2, "ceo", tmp_path)
    widgets = MetricsStore(metrics_dir=tmp_path).get_widgets()
    assert len(widgets) == 1
    assert widgets[0].content == "new"
