from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from glediator.core.engine import RenderEngine


class FaderPanel(QGroupBox):
    def __init__(self, engine: RenderEngine, parent: QWidget | None = None) -> None:
        super().__init__("FINAL OUTPUT", parent)
        self.engine = engine
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Crossfade between Source A and Source B"))
        fader_line = QHBoxLayout()
        fader_line.addWidget(QLabel("A"))
        self.fader_slider = QSlider(Qt.Orientation.Horizontal)
        self.fader_slider.setRange(0, 100)
        self.fader_slider.setValue(round(self.engine.fader * 100))
        self.fader_slider.valueChanged.connect(lambda v: self.engine.set_fader(v / 100))
        fader_line.addWidget(self.fader_slider, 1)
        fader_line.addWidget(QLabel("B"))
        layout.addLayout(fader_line)

    def sync_from_engine(self) -> None:
        self.fader_slider.blockSignals(True)
        self.fader_slider.setValue(round(self.engine.fader * 100))
        self.fader_slider.blockSignals(False)
