from __future__ import annotations

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.output.websocket_output import OutputStatus
from glediator.ui.main_window import MainWindow


def test_network_panel_shows_mismatch_banner_and_applies_device_size(qtbot, monkeypatch):
    monkeypatch.setattr("glediator.network.discovery.DeviceDiscovery.start", lambda self: None)
    monkeypatch.setattr("glediator.network.discovery.DeviceDiscovery.stop", lambda self: None)
    monkeypatch.setattr(EngineConfig, "save", lambda self, path=None: None)

    config = EngineConfig(width=32, height=16)
    engine = RenderEngine(config)
    window = MainWindow(engine, config)
    qtbot.addWidget(window)

    window.network_panel.handle_discovery_events([
        ("device", {"address": "192.168.1.50", "name": "panel-1", "w": 64, "h": 32, "port": 12345, "v": 2})
    ])
    fake_status = {
        "192.168.1.50:12345": OutputStatus(
            state="mismatch",
            protocol="v2",
            device={"name": "panel-1", "w": 64, "h": 32, "caps": ["delta", "ack", "brightness"]},
            last_error="Device is 64×32, app is 32×16",
        )
    }
    window.network_panel.update_controls(fake_status)
    assert not window.network_panel.mismatch_banner.isHidden()
    assert not window.network_panel.device_brightness_row.isHidden()

    window.network_panel.mismatch_apply_btn.click()
    assert config.width == 64
    assert config.height == 32
    assert window.network_panel.mismatch_banner.isHidden()
    window.close()
    engine.stop()


def test_network_panel_ignores_untouched_localhost(qtbot, monkeypatch):
    monkeypatch.setattr("glediator.network.discovery.DeviceDiscovery.start", lambda self: None)
    monkeypatch.setattr("glediator.network.discovery.DeviceDiscovery.stop", lambda self: None)
    monkeypatch.setattr(EngineConfig, "save", lambda self, path=None: None)

    config = EngineConfig(
        width=32,
        height=16,
        devices=[{"id": "dev-1", "name": "", "host": "127.0.0.1", "port": 12345, "auto_connect": False}],
    )
    engine = RenderEngine(config)
    window = MainWindow(engine, config)
    qtbot.addWidget(window)

    assert window.network_panel.device_list.count() == 0
    window.network_panel.sync_endpoint_to_config()
    assert config.devices == []
    window.close()
    engine.stop()
