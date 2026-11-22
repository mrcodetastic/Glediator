from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from glediator.generators.palettes import palette_names
from glediator.ui.widgets.color_button import ColorButton


class FilePickerWidget(QWidget):
    def __init__(self, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.line_edit = QLineEdit(value)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.browse_btn)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose media file",
            self.line_edit.text(),
            "Media Files (*.mp4 *.mov *.mkv *.avi *.webm *.gif *.png *.jpg *.jpeg *.bmp);;All Files (*)",
        )
        if path:
            self.line_edit.setText(path)

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, value: str) -> None:
        self.line_edit.setText(value)


def create_param_editor(kind: str, default, minimum, maximum, step, value, *, key: str = "") -> QWidget:
    if kind == "bool":
        editor = QCheckBox()
        editor.setChecked(bool(default if value is None else value))
        return editor
    if kind == "file":
        return FilePickerWidget(str(default if value is None else value))
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
        if key == "palette":
            choices = list(palette_names())
            if isinstance(minimum, (list, tuple)):
                for item in minimum:
                    if item not in choices:
                        choices.append(item)
        else:
            choices = list(minimum() if callable(minimum) else minimum)
        editor.addItems(choices)
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
    if isinstance(editor, QCheckBox):
        return editor.isChecked()
    if isinstance(editor, FilePickerWidget):
        return editor.text()
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
            editor = create_param_editor(
                kind, default, minimum, maximum, step, values.get(key, default), key=key
            )
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
