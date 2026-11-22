from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton, QWidget


class ColorButton(QPushButton):
    color_changed = Signal(str)

    def __init__(self, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color_value = value
        self.clicked.connect(self._choose_color)
        self._update_swatch()

    def set_color(self, value: str) -> None:
        self.color_value = value
        self._update_swatch()

    def _update_swatch(self) -> None:
        self.setText(self.color_value.upper())
        qcol = QColor(self.color_value)
        luminance = 0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue() if qcol.isValid() else 128
        fg = "#101820" if luminance >= 130 else "#f4f7fb"
        self.setStyleSheet(f"background:{self.color_value}; color:{fg}; border:1px solid #647486; padding:6px;")

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.color_value), self, "Choose effect color")
        if color.isValid():
            self.color_value = color.name(QColor.NameFormat.HexRgb)
            self._update_swatch()
            self.color_changed.emit(self.color_value)
