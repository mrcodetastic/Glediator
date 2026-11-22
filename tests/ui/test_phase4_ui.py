from __future__ import annotations

from pathlib import Path

from glediator.control.actions import ActionRegistry
from glediator.control.osc import OscController
from glediator.core.config import EngineConfig
from glediator.effects import effect_categories, effect_descriptions, picker_effect_names
from glediator.ui.dialogs.controls_dialog import ControlsDialog, ShortcutsDialog
from glediator.ui.dialogs.effect_picker import EffectPickerDialog
from glediator.ui.dialogs.effect_settings import EffectSettingsDialog
from glediator.ui.dialogs.palette_editor import PaletteEditorDialog
from glediator.ui.dialogs.panel_config import PanelConfigDialog
from glediator.ui.dialogs.user_guide import UserGuideDialog


def test_all_dialogs_construct_and_filter_cleanly(qtbot):
    picker = EffectPickerDialog(None, picker_effect_names(), effect_descriptions(), effect_categories())
    qtbot.addWidget(picker)
    assert picker.effects.rowCount() > 30
    picker.search_input.setText("Wave")
    assert picker.effects.rowCount() >= 1

    panel_dlg = PanelConfigDialog(None, 64, 32)
    qtbot.addWidget(panel_dlg)
    assert panel_dlg.dimensions() == (64, 32)

    settings_dlg = EffectSettingsDialog(
        None,
        "Test",
        {"flag": ("bool", True, False, True, 1), "count": ("int", 3, 1, 10, 1)},
        {"flag": False, "count": 5},
    )
    qtbot.addWidget(settings_dlg)
    assert settings_dlg.values() == {"flag": False, "count": 5}

    pal_dlg = PaletteEditorDialog(None, {"Warm": ["#ff0000", "#ffff00"]})
    qtbot.addWidget(pal_dlg)
    assert "Warm" in pal_dlg.palettes

    reg = ActionRegistry()
    shortcuts_dlg = ShortcutsDialog(None, {}, reg)
    qtbot.addWidget(shortcuts_dlg)
    controls_dlg = ControlsDialog(None, EngineConfig(), OscController(reg))
    qtbot.addWidget(controls_dlg)

    guide_dlg = UserGuideDialog(None)
    qtbot.addWidget(guide_dlg)
    assert "Glediator User Guide" in guide_dlg.browser.toPlainText()

    root = Path(__file__).resolve().parents[2]
    assert (root / "glediator" / "assets" / "icon.png").is_file()
    assert (root / "glediator" / "assets" / "icon.ico").is_file()
    assert (root / "docs" / "user-guide.md").read_text(encoding="utf-8") == (
        root / "glediator" / "assets" / "user-guide.md"
    ).read_text(encoding="utf-8")
