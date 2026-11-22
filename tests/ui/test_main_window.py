from __future__ import annotations

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.ui.main_window import MainWindow


def test_main_window_adds_effect_through_source_panel(qtbot, monkeypatch):
    monkeypatch.setattr("glediator.network.discovery.DeviceDiscovery.start", lambda self: None)
    monkeypatch.setattr("glediator.network.discovery.DeviceDiscovery.stop", lambda self: None)
    monkeypatch.setattr(EngineConfig, "save", lambda self, path=None: None)

    config = EngineConfig(width=32, height=16)
    engine = RenderEngine(config)
    window = MainWindow(engine, config)
    qtbot.addWidget(window)

    before_count = window.source_a_panel.list_widget.count()
    idx = window.source_a_panel.add_effect_by_name("Wave")
    assert idx is not None
    assert window.source_a_panel.list_widget.count() == before_count + 1
    window.close()
    engine.stop()
