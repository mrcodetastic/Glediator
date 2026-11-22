from __future__ import annotations

from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from glediator.generators.palettes import PALETTES, parse_hex_color
from glediator.ui.widgets.color_button import ColorButton


class GradientPreview(QWidget):
    def __init__(self, stops: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stops = list(stops)
        self.setMinimumHeight(28)

    def set_stops(self, stops: list[str]) -> None:
        self._stops = list(stops)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        grad = QLinearGradient(0, 0, self.width(), 0)
        if len(self._stops) >= 2:
            for idx, hex_col in enumerate(self._stops):
                grad.setColorAt(idx / (len(self._stops) - 1), QColor(hex_col))
        else:
            grad.setColorAt(0.0, QColor("#000000"))
            grad.setColorAt(1.0, QColor("#ffffff"))
        painter.fillRect(self.rect(), grad)
        painter.end()


class PaletteEditorDialog(QDialog):
    def __init__(self, parent: QWidget, custom_palettes: dict[str, list[str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom Palette Editor")
        self.resize(480, 320)
        self.palettes: dict[str, list[str]] = {
            k: list(v) for k, v in custom_palettes.items() if isinstance(v, list) and len(v) >= 2
        }

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.currentTextChanged.connect(self._load_selected)
        new_btn = QPushButton("New…")
        new_btn.clicked.connect(self._new_palette)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_palette)
        top.addWidget(QLabel("Palette"))
        top.addWidget(self.combo, 1)
        top.addWidget(new_btn)
        top.addWidget(del_btn)
        layout.addLayout(top)

        self.preview = GradientPreview(["#000000", "#ffffff"])
        layout.addWidget(self.preview)

        self.stops_row = QHBoxLayout()
        layout.addLayout(self.stops_row)

        stop_actions = QHBoxLayout()
        add_stop_btn = QPushButton("+ Add stop")
        add_stop_btn.clicked.connect(self._add_stop)
        rem_stop_btn = QPushButton("- Remove stop")
        rem_stop_btn.clicked.connect(self._remove_stop)
        stop_actions.addWidget(add_stop_btn)
        stop_actions.addWidget(rem_stop_btn)
        stop_actions.addStretch(1)
        layout.addLayout(stop_actions)

        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_combo()

    def _refresh_combo(self, select: str | None = None) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for name in sorted(self.palettes):
            self.combo.addItem(name)
        if select:
            self.combo.setCurrentText(select)
        self.combo.blockSignals(False)
        self._load_selected()

    def _clear_stops_ui(self) -> None:
        while self.stops_row.count():
            item = self.stops_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _load_selected(self) -> None:
        self._clear_stops_ui()
        name = self.combo.currentText()
        stops = self.palettes.get(name, [])
        self.preview.set_stops(stops)
        for idx, hex_col in enumerate(stops):
            btn = ColorButton(hex_col)
            btn.color_changed.connect(lambda c, n=name, i=idx: self._update_stop(n, i, c))
            self.stops_row.addWidget(btn)

    def _update_stop(self, name: str, idx: int, hex_col: str) -> None:
        if name in self.palettes and 0 <= idx < len(self.palettes[name]):
            self.palettes[name][idx] = hex_col
            self.preview.set_stops(self.palettes[name])

    def _new_palette(self) -> None:
        name, ok = QInputDialog.getText(self, "New Palette", "Palette name:")
        name = name.strip()
        if not ok or not name or name in PALETTES:
            return
        if name not in self.palettes:
            rgb_stops = PALETTES["Aurora"]
            self.palettes[name] = [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in rgb_stops[:3]]
        self._refresh_combo(name)

    def _delete_palette(self) -> None:
        name = self.combo.currentText()
        if name in self.palettes:
            self.palettes.pop(name)
            self._refresh_combo()

    def _add_stop(self) -> None:
        name = self.combo.currentText()
        stops = self.palettes.get(name)
        if not stops or len(stops) >= 16:
            return
        col = parse_hex_color(stops[-1])
        stops.append(f"#{int(col[0]):02x}{int(col[1]):02x}{int(col[2]):02x}")
        self._load_selected()

    def _remove_stop(self) -> None:
        name = self.combo.currentText()
        stops = self.palettes.get(name)
        if not stops or len(stops) <= 2:
            return
        stops.pop()
        self._load_selected()
