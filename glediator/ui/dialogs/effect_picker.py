from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class EffectPickerDialog(QDialog):
    """Searchable, category-filterable generator list; double-click an entry to choose it."""

    def __init__(
        self,
        parent: QWidget,
        names: list[str],
        descriptions: dict[str, str] | None = None,
        categories: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add effect")
        self.setMinimumSize(640, 480)
        self.resize(740, 560)
        self._names = list(names)
        self._descriptions = descriptions or {}
        self._categories = categories or {}
        self.selected_effect: str | None = None

        layout = QVBoxLayout(self)
        hint = QLabel("Double-click an effect to add it to this source.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search effects…")
        self.search_input.textChanged.connect(self._populate)
        self.category_combo = QComboBox()
        self.category_combo.addItem("All categories")
        for category in sorted({self._categories.get(name, "General") for name in self._names}):
            self.category_combo.addItem(category)
        self.category_combo.currentTextChanged.connect(self._populate)
        filter_row.addWidget(self.search_input, 1)
        filter_row.addWidget(self.category_combo)
        layout.addLayout(filter_row)

        self.effects = QTableWidget(0, 3)
        self.effects.setHorizontalHeaderLabels(("Effect", "Category", "Description"))
        for column in range(3):
            header_item = self.effects.horizontalHeaderItem(column)
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            header_font = header_item.font()
            header_font.setBold(True)
            header_item.setFont(header_font)
        self.effects.horizontalHeader().setStyleSheet("QHeaderView::section { font-weight: 700; text-align: left; }")
        self.effects.verticalHeader().setVisible(False)
        self.effects.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.effects.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.effects.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.effects.setWordWrap(True)
        self.effects.setShowGrid(True)
        self.effects.setStyleSheet("QTableWidget { gridline-color: #2b3642; }")
        self.effects.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.effects.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.effects.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.effects.itemDoubleClicked.connect(self._choose)
        layout.addWidget(self.effects, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

    def _populate(self) -> None:
        query = self.search_input.text().strip().casefold()
        selected_cat = self.category_combo.currentText()
        filtered = [
            name
            for name in self._names
            if (selected_cat == "All categories" or self._categories.get(name, "General") == selected_cat)
            and (
                not query
                or query in name.casefold()
                or query in self._descriptions.get(name, "").casefold()
                or query in self._categories.get(name, "").casefold()
            )
        ]
        self.effects.setRowCount(len(filtered))
        for row, name in enumerate(filtered):
            self.effects.setItem(row, 0, QTableWidgetItem(name))
            self.effects.setItem(row, 1, QTableWidgetItem(self._categories.get(name, "General")))
            self.effects.setItem(row, 2, QTableWidgetItem(self._descriptions.get(name, "")))
            self.effects.setRowHeight(row, 34)
        if filtered:
            self.effects.selectRow(0)

    def _choose(self, item: QTableWidgetItem) -> None:
        self.selected_effect = self.effects.item(item.row(), 0).text()
        self.accept()

    def _accept_selected(self) -> None:
        row = self.effects.currentRow()
        if row >= 0 and self.effects.item(row, 0) is not None:
            self.selected_effect = self.effects.item(row, 0).text()
            self.accept()
