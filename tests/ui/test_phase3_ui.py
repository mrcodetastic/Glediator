from __future__ import annotations

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.ui.main_window import MainWindow


def test_inspector_undo_preview_and_docks(qtbot, monkeypatch):
    monkeypatch.setattr("glediator.network.discovery.DeviceDiscovery.start", lambda self: None)
    monkeypatch.setattr("glediator.network.discovery.DeviceDiscovery.stop", lambda self: None)
    monkeypatch.setattr(EngineConfig, "save", lambda self, path=None: None)

    config = EngineConfig(width=32, height=16)
    engine = RenderEngine(config)
    window = MainWindow(engine, config)
    qtbot.addWidget(window)

    # Add Wave via SourcePanel, then test Undo / Redo
    idx = window.source_a_panel.add_effect_by_name("Wave")
    assert idx == 1
    assert engine.scene_snapshot("left")["layers"][1]["generator"] == "Wave"

    window.undo_stack.undo()
    assert not engine.scene_snapshot("left")["layers"][1]["configured"]
    window.undo_stack.redo()
    assert engine.scene_snapshot("left")["layers"][1]["generator"] == "Wave"

    # Live inspector edit applies within 150ms and preserves QLineEdit focus while typing
    window.inspector.inspect("left", 1)
    speed_spin = window.inspector._editors["speed"]
    speed_spin.setValue(4.5)
    qtbot.wait(120)
    assert abs(engine.scene_snapshot("left")["layers"][1]["parameters"]["speed"] - 4.5) < 1e-3

    text_idx = window.source_a_panel.add_effect_by_name("Scrolling Text")
    assert text_idx == 2
    window.show()
    window.inspector_dock.show()
    window.inspector.inspect("left", text_idx)
    text_edit = window.inspector._editors["text"]
    text_edit.setFocus()
    text_edit.setText("")
    for ch in "MERRY":
        qtbot.keyClick(text_edit, ch)
        qtbot.wait(70)
    assert window.inspector._editors["text"] is text_edit
    assert text_edit.hasFocus()
    assert engine.scene_snapshot("left")["layers"][text_idx]["parameters"]["text"] == "MERRY"

    # Preview modes and Performance dock update cleanly
    window.mix_preview.set_mode("dots")
    window.mix_preview.set_frame(engine.step(0.1))
    window.mix_preview.set_mode("pixels")
    window.performance_dock.show()
    window.performance_panel.update_status(engine.status(), 60)

    # Playlist panel shows guidance when no scenes exist, then enables once saved
    assert window.playlist_panel.preset_combo.currentText() == window.playlist_panel.NO_SCENES_MSG
    assert not window.playlist_panel.new_btn.isEnabled()
    assert window.preset_bar.preset_combo.minimumWidth() >= 275

    window._save_preset("PresetOne")
    window.playlist_panel.refresh_presets()
    window.playlist_panel.refresh_playlists()
    assert window.playlist_panel.new_btn.isEnabled()
    window.config.playlists.append({"name": "SetA", "entries": [], "loop": True, "shuffle": False})
    window.playlist_panel.refresh_playlists()
    window.playlist_panel._add_entry()
    assert window.playlist_panel.entry_list.count() == 1

    # Edit menu exposes Copy A to B, Copy B to A, Swap A and B instead of FaderPanel buttons
    edit_menu = next(a.menu() for a in window.menuBar().actions() if "Edit" in a.text())
    edit_labels = {act.text() for act in edit_menu.actions()}
    assert {"Copy A to B", "Copy B to A", "Swap A and B"}.issubset(edit_labels)
    window.fader_panel.loop_hold_spin.setValue(1.5)
    window.fader_panel.loop_btn.setChecked(True)
    assert engine.loop_fader is True
    assert engine.loop_hold_s == 1.5
    window.fader_panel.loop_btn.setChecked(False)
    assert engine.loop_fader is False

    window.close()
    engine.stop()
