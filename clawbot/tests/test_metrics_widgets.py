import pytest
from pathlib import Path
from clawbot.metrics import MetricsStore, DashboardWidget


def _store(tmp_path: Path) -> MetricsStore:
    return MetricsStore(metrics_dir=tmp_path)


def test_get_widgets_empty(tmp_path):
    assert _store(tmp_path).get_widgets() == []


def test_upsert_widget_stores_and_retrieves(tmp_path):
    store = _store(tmp_path)
    w = DashboardWidget(id="ceo_focus", type="text", title="CEO Focus",
                        agent="ceo", content="Grow IR35 revenue")
    store.upsert_widget(w)
    widgets = store.get_widgets()
    assert len(widgets) == 1
    assert widgets[0].id == "ceo_focus"
    assert widgets[0].content == "Grow IR35 revenue"
    assert widgets[0].agent == "ceo"


def test_upsert_widget_overwrites_same_id(tmp_path):
    store = _store(tmp_path)
    store.upsert_widget(DashboardWidget(id="ceo_focus", type="text", title="Old", agent="ceo", content="old"))
    store.upsert_widget(DashboardWidget(id="ceo_focus", type="text", title="New", agent="ceo", content="new"))
    widgets = store.get_widgets()
    assert len(widgets) == 1
    assert widgets[0].content == "new"


def test_remove_widget_deletes_by_id(tmp_path):
    store = _store(tmp_path)
    store.upsert_widget(DashboardWidget(id="w1", type="text", title="T", agent="ceo", content="x"))
    store.upsert_widget(DashboardWidget(id="w2", type="text", title="T", agent="cfo", content="y"))
    store.remove_widget("w1")
    ids = [w.id for w in store.get_widgets()]
    assert ids == ["w2"]


def test_remove_nonexistent_widget_is_noop(tmp_path):
    store = _store(tmp_path)
    store.remove_widget("does_not_exist")  # must not raise


def test_widget_updated_at_is_set(tmp_path):
    store = _store(tmp_path)
    store.upsert_widget(DashboardWidget(id="w", type="text", title="T", agent="ceo", content="c"))
    assert store.get_widgets()[0].updated_at != ""


def test_get_widgets_returns_dataclasses(tmp_path):
    store = _store(tmp_path)
    store.upsert_widget(DashboardWidget(id="w", type="metric", title="Rev",
                        agent="cfo", value=42.0, unit="GBP"))
    w = store.get_widgets()[0]
    assert isinstance(w, DashboardWidget)
    assert w.value == 42.0
    assert w.unit == "GBP"
