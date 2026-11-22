from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QInputDialog, QLabel, QPushButton, QWidget

from glediator.core.config import EngineConfig


class PresetBar(QWidget):
    preset_loaded = Signal(str)
    preset_saved = Signal(str)
    preset_deleted = Signal(str)

    def __init__(self, config: EngineConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("LOAD / SAVE SCENE"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(275)
        layout.addWidget(self.preset_combo)

        save_btn = QPushButton("Save as preset…")
        save_btn.clicked.connect(self._save_preset)
        load_btn = QPushButton("Load preset")
        load_btn.clicked.connect(self._load_preset)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._delete_preset)
        layout.addWidget(save_btn)
        layout.addWidget(load_btn)
        layout.addWidget(delete_btn)
        layout.addStretch(1)
        self.refresh()

    def refresh(self, selected: str | None = None) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for preset in self.config.presets:
            self.preset_combo.addItem(preset["name"])
        if selected:
            index = self.preset_combo.findText(selected)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

    def _save_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save scene preset", "Preset name:")
        name = name.strip()
        if not accepted or not name:
            return
        self.preset_saved.emit(name)

    def _load_preset(self) -> None:
        name = self.preset_combo.currentText()
        if name:
            self.preset_loaded.emit(name)

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        if name:
            self.preset_deleted.emit(name)
