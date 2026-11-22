from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from glediator.control.actions import DEFAULT_SHORTCUTS, ActionRegistry
from glediator.control.osc import OscController
from glediator.core.config import EngineConfig


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget, bindings: dict[str, str], registry: ActionRegistry) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(480, 400)
        layout = QVBoxLayout(self)
        labels = {a.id: a.label for a in registry.actions()}
        merged = {**DEFAULT_SHORTCUTS, **bindings}
        table = QTableWidget(len(merged), 2)
        table.setHorizontalHeaderLabels(("Key", "Action"))
        for row, (key, action_id) in enumerate(merged.items()):
            table.setItem(row, 0, QTableWidgetItem(key))
            table.setItem(row, 1, QTableWidgetItem(f"{labels.get(action_id, action_id)} ({action_id})"))
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ControlsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        config: EngineConfig,
        osc: OscController,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("OSC Control Settings")
        self.resize(460, 220)
        self.config = config
        self.osc = osc

        layout = QVBoxLayout(self)

        osc_box = QGroupBox("OSC Server")
        osc_form = QFormLayout(osc_box)
        osc_cfg = config.controls.get("osc", {})
        self.osc_enabled = QCheckBox("Enable OSC UDP listener")
        self.osc_enabled.setChecked(bool(osc_cfg.get("enabled", False)))
        self.osc_port = QSpinBox()
        self.osc_port.setRange(1024, 65535)
        self.osc_port.setValue(int(osc_cfg.get("port", 9000)))
        osc_form.addRow(self.osc_enabled)
        osc_form.addRow("UDP Port", self.osc_port)
        osc_form.addRow("Address format", QLabel("/glediator/<action/id/with/slashes> [0..1]"))
        layout.addWidget(osc_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        self.config.controls["osc"] = {
            "enabled": self.osc_enabled.isChecked(),
            "port": self.osc_port.value(),
        }
        if self.osc_enabled.isChecked():
            self.osc.start(port=self.osc_port.value())
        else:
            self.osc.stop()
        self.accept()
