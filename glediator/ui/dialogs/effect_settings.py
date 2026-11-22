from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from glediator.ui.widgets.color_button import ColorButton


def create_param_editor(kind: str, default, minimum, maximum, step, value) -> QWidget:
    if kind == "str":
        return QLineEdit(str(value if value is not None else default))
    if kind == "color":
        return ColorButton(str(value if value is not None else default))
    if kind == "font":
        editor = QFontComboBox()
        editor.setCurrentFont(QFont(str(value if value is not None else default)))
        return editor
    if kind == "choice":
        editor = QComboBox()
        choices = minimum() if callable(minimum) else list(minimum)
        editor.addItems(list(choices))
        editor.setCurrentText(str(value if value is not None else default))
        return editor
    if kind == "int":
        editor = QSpinBox()
        editor.setRange(int(minimum), int(maximum))
        editor.setSingleStep(int(step))
        editor.setValue(int(value if value is not None else default))
        return editor
    editor = QDoubleSpinBox()
    editor.setRange(float(minimum), float(maximum))
    editor.setSingleStep(float(step))
    editor.setDecimals(3)
    editor.setValue(float(value if value is not None else default))
    return editor


def read_param_editor(editor: QWidget):
    if isinstance(editor, QLineEdit):
        return editor.text()
    if isinstance(editor, ColorButton):
        return editor.color_value
    if isinstance(editor, QFontComboBox):
        return editor.currentFont().family()
    if isinstance(editor, QComboBox):
        return editor.currentText()
    return editor.value()


class EffectSettingsDialog(QDialog):
    """Modal parameter editor generated from an effect/output settings schema."""

    def __init__(self, parent: QWidget, title: str, schema: dict, values: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        self.editors: dict[str, QWidget] = {}
        for key, spec in schema.items():
            kind, default, minimum, maximum, step = spec
            editor = create_param_editor(kind, default, minimum, maximum, step, values.get(key, default))
            self.editors[key] = editor
            label = {
                "bins": "Bin count (0 = panel width)",
                "bin_width": "Bin width (pixels)",
                "capture_fps": "Capture rate (FPS, max 30)",
            }.get(key, key.replace("_", " ").title())
            form.addRow(label, editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {key: read_param_editor(editor) for key, editor in self.editors.items()}
