from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from glediator.core.engine import EngineStatus, RenderEngine
from glediator.core.fader import TRANSITION_KINDS


class FaderPanel(QGroupBox):
    copy_scene_requested = Signal(str, str)
    swap_scenes_requested = Signal()

    def __init__(self, engine: RenderEngine, parent: QWidget | None = None) -> None:
        super().__init__("FINAL OUTPUT · MASTER", parent)
        self.engine = engine

        layout = QVBoxLayout(self)

        fader_line = QHBoxLayout()
        fader_line.addWidget(QLabel("A"))
        self.fader_slider = QSlider(Qt.Orientation.Horizontal)
        self.fader_slider.setRange(0, 100)
        self.fader_slider.setValue(round(self.engine.fader * 100))
        self.fader_slider.valueChanged.connect(lambda v: self.engine.set_fader(v / 100.0))
        fader_line.addWidget(self.fader_slider, 1)
        fader_line.addWidget(QLabel("B"))
        layout.addLayout(fader_line)

        scene_ops_row = QHBoxLayout()
        a_to_b = QPushButton("A → B")
        a_to_b.clicked.connect(lambda: self.copy_scene_requested.emit("left", "right"))
        swap_btn = QPushButton("Swap A ↔ B")
        swap_btn.clicked.connect(self.swap_scenes_requested.emit)
        b_to_a = QPushButton("B → A")
        b_to_a.clicked.connect(lambda: self.copy_scene_requested.emit("right", "left"))
        scene_ops_row.addWidget(a_to_b)
        scene_ops_row.addWidget(swap_btn)
        scene_ops_row.addWidget(b_to_a)
        layout.addLayout(scene_ops_row)

        trans_row = QHBoxLayout()
        self.transition_combo = QComboBox()
        self.transition_combo.addItems(list(TRANSITION_KINDS))
        self.transition_combo.currentTextChanged.connect(self.engine.set_transition_kind)
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 30.0)
        self.duration_spin.setSingleStep(0.5)
        self.duration_spin.setValue(2.0)
        self.duration_spin.setSuffix(" s")
        self.auto_btn = QPushButton("Auto A ↔ B")
        self.auto_btn.clicked.connect(self._start_auto_transition)
        trans_row.addWidget(self.transition_combo, 1)
        trans_row.addWidget(self.duration_spin)
        trans_row.addWidget(self.auto_btn)
        layout.addLayout(trans_row)

        master_row = QHBoxLayout()
        self.blackout_btn = QPushButton("Blackout")
        self.blackout_btn.setCheckable(True)
        self.blackout_btn.toggled.connect(self._on_blackout_toggled)
        self.freeze_btn = QPushButton("Freeze")
        self.freeze_btn.setCheckable(True)
        self.freeze_btn.toggled.connect(self._on_freeze_toggled)
        self.tap_btn = QPushButton("Tap BPM")
        self.tap_btn.clicked.connect(self._on_tap)
        self.bpm_label = QLabel("-- BPM")
        self.bpm_label.setMinimumWidth(78)
        master_row.addWidget(self.blackout_btn)
        master_row.addWidget(self.freeze_btn)
        master_row.addWidget(self.tap_btn)
        master_row.addWidget(self.bpm_label)
        layout.addLayout(master_row)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(0, 400)
        self.speed_slider.setValue(100)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.speed_label = QLabel("1.00×")
        self.speed_label.setMinimumWidth(46)
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_label)
        layout.addLayout(speed_row)

        self._refresh_toggle_styles()

    def _start_auto_transition(self) -> None:
        target = 1.0 if self.engine.fader < 0.5 else 0.0
        self.engine.start_transition(
            target,
            float(self.duration_spin.value()),
            kind=self.transition_combo.currentText(),
        )

    def _on_blackout_toggled(self, checked: bool) -> None:
        self.engine.set_master(blackout=checked)
        self._refresh_toggle_styles()

    def _on_freeze_toggled(self, checked: bool) -> None:
        self.engine.set_master(freeze=checked)
        self._refresh_toggle_styles()

    def _on_speed_changed(self, value: int) -> None:
        spd = value / 100.0
        self.speed_label.setText(f"{spd:.2f}×")
        self.engine.set_master(speed=spd)

    def _on_tap(self) -> None:
        bpm = self.engine.tap_tempo()
        if bpm > 0:
            self.bpm_label.setText(f"{bpm:.0f} BPM")

    def _refresh_toggle_styles(self) -> None:
        if self.blackout_btn.isChecked():
            self.blackout_btn.setStyleSheet("background:#dc2626; color:white; font-weight:700;")
        else:
            self.blackout_btn.setStyleSheet("")
        if self.freeze_btn.isChecked():
            self.freeze_btn.setStyleSheet("background:#d97706; color:white; font-weight:700;")
        else:
            self.freeze_btn.setStyleSheet("")

    def sync_from_engine(self) -> None:
        self.fader_slider.blockSignals(True)
        self.fader_slider.setValue(round(self.engine.fader * 100))
        self.fader_slider.blockSignals(False)

    def sync_from_status(self, status: EngineStatus) -> None:
        if not self.fader_slider.isSliderDown():
            val = round(status.fader * 100)
            if self.fader_slider.value() != val:
                self.fader_slider.blockSignals(True)
                self.fader_slider.setValue(val)
                self.fader_slider.blockSignals(False)
        if self.blackout_btn.isChecked() != status.blackout:
            self.blackout_btn.blockSignals(True)
            self.blackout_btn.setChecked(status.blackout)
            self.blackout_btn.blockSignals(False)
            self._refresh_toggle_styles()
        if self.freeze_btn.isChecked() != status.freeze:
            self.freeze_btn.blockSignals(True)
            self.freeze_btn.setChecked(status.freeze)
            self.freeze_btn.blockSignals(False)
            self._refresh_toggle_styles()
        if status.bpm > 0:
            tag = "tap" if status.bpm_source == "tap" else "auto"
            self.bpm_label.setText(f"{status.bpm:.0f} BPM ({tag})")
        else:
            self.bpm_label.setText("-- BPM")
