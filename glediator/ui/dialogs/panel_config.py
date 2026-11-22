from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QWidget


class PanelConfigDialog(QDialog):
    """Configure logical matrix dimensions (pixels are always sent row-major)."""

    def __init__(self, parent: QWidget, width: int, height: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("LED Panel Config")
        form = QFormLayout(self)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(8, 512)
        self.width_spin.setValue(int(width))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(8, 512)
        self.height_spin.setValue(int(height))
        form.addRow("Matrix width", self.width_spin)
        form.addRow("Matrix height", self.height_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def dimensions(self) -> tuple[int, int]:
        return self.width_spin.value(), self.height_spin.value()
