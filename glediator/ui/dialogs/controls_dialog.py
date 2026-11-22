from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from glediator.control.actions import DEFAULT_SHORTCUTS, ActionRegistry
from glediator.control.midi import MidiController
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
        registry: ActionRegistry,
        midi: MidiController,
        osc: OscController,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MIDI & OSC Control")
        self.resize(560, 480)
        self.config = config
        self.registry = registry
        self.midi = midi
        self.osc = osc

        layout = QVBoxLayout(self)

        midi_box = QGroupBox("MIDI Control")
        midi_layout = QVBoxLayout(midi_box)
        port_row = QHBoxLayout()
        self.midi_port_combo = QComboBox()
        ports, err = MidiController.available_ports()
        self.midi_port_combo.addItem("(None)")
        self.midi_port_combo.addItems(ports)
        self.midi_connect_btn = QPushButton("Open Port")
        self.midi_connect_btn.clicked.connect(self._open_midi)
        port_row.addWidget(QLabel("Input port"))
        port_row.addWidget(self.midi_port_combo, 1)
        port_row.addWidget(self.midi_connect_btn)
        midi_layout.addLayout(port_row)
        if err:
            midi_layout.addWidget(QLabel(err))

        learn_row = QHBoxLayout()
        self.action_combo = QComboBox()
        for act in registry.actions():
            self.action_combo.addItem(f"{act.label} ({act.id})", act.id)
        self.learn_btn = QPushButton("Learn MIDI")
        self.learn_btn.clicked.connect(self._learn_midi)
        learn_row.addWidget(self.action_combo, 1)
        learn_row.addWidget(self.learn_btn)
        midi_layout.addLayout(learn_row)

        self.midi_list = QListWidget()
        self._refresh_midi_list()
        midi_layout.addWidget(self.midi_list)
        layout.addWidget(midi_box)

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

    def _refresh_midi_list(self) -> None:
        self.midi_list.clear()
        for m in self.config.controls.get("midi", []):
            self.midi_list.addItem(
                f"{m.get('type')} ch {m.get('channel')} #{m.get('number')} -> {m.get('action')}"
            )

    def _open_midi(self) -> None:
        port = self.midi_port_combo.currentText()
        if port == "(None)":
            self.midi.stop()
        else:
            self.midi.start(port)

    def _learn_midi(self) -> None:
        action_id = self.action_combo.currentData()
        self.learn_btn.setText("Move MIDI control…")

        def _captured(event_dict: dict) -> None:
            entry = {**event_dict, "action": action_id, "mode": "continuous"}
            self.config.controls.setdefault("midi", []).append(entry)
            self.midi.set_mappings(self.config.controls["midi"])

        self.midi.start_learn(_captured)

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
