from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from glediator.core.engine import RenderEngine
from glediator.effects import (
    default_effect_parameters,
    effect_categories,
    effect_descriptions,
    effect_settings,
    picker_effect_names,
)
from glediator.ui.dialogs.effect_picker import EffectPickerDialog
from glediator.ui.dialogs.effect_settings import EffectSettingsDialog


class SourcePanel(QGroupBox):
    status_message = Signal(str)
    layer_selected = Signal(str, int)

    def __init__(self, label: str, side: str, engine: RenderEngine, parent: QWidget | None = None) -> None:
        super().__init__(f"SOURCE {label}", parent)
        self.side = side
        self.engine = engine

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(125)
        self.list_widget.setMaximumHeight(175)
        self.list_widget.setToolTip("Select an effect to edit it; double-click to open its detailed settings.")
        self.list_widget.currentItemChanged.connect(lambda _c, _p: self.sync_controls())
        self.list_widget.itemChanged.connect(self._effect_item_changed)
        self.list_widget.itemDoubleClicked.connect(
            lambda item: self.show_generator_settings(int(item.data(Qt.ItemDataRole.UserRole)))
        )
        layout.addWidget(self.list_widget)

        actions = QHBoxLayout()
        self.add_button = QPushButton("+ Add effect")
        self.add_button.clicked.connect(self.add_effect)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_effect)
        self.up_button = QPushButton("↑")
        self.up_button.setToolTip("Move selected effect up")
        self.up_button.clicked.connect(lambda: self.move_effect(-1))
        self.down_button = QPushButton("↓")
        self.down_button.setToolTip("Move selected effect down")
        self.down_button.clicked.connect(lambda: self.move_effect(1))
        actions.addWidget(self.add_button, 1)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.up_button)
        actions.addWidget(self.down_button)
        layout.addLayout(actions)

        form = QFormLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["None", "Invert", "Monochrome", "Threshold"])
        self.filter_combo.currentTextChanged.connect(
            lambda name: self._update_selected_layer(filter_name=name)
        )
        form.addRow("Filter", self.filter_combo)

        self.blend_combo = QComboBox()
        self.blend_combo.addItems(["Add", "Subtract", "Multiply", "Difference", "Screen", "Maximum"])
        self.blend_combo.currentTextChanged.connect(lambda name: self._update_selected_layer(mix_mode=name))
        form.addRow("Layer blend", self.blend_combo)

        self.brightness_spin = QSpinBox()
        self.brightness_spin.setRange(0, 100)
        self.brightness_spin.setValue(100)
        self.brightness_spin.setSuffix(" %")
        self.brightness_spin.valueChanged.connect(lambda value: self._update_selected_layer(brightness=value))
        form.addRow("Brightness", self.brightness_spin)

        self.settings_button = QPushButton("Effect settings…")
        self.settings_button.clicked.connect(self._edit_selected_effect)
        form.addRow(self.settings_button)
        layout.addLayout(form)

        self.refresh_effect_list()

    def selected_layer(self) -> int | None:
        item = self.list_widget.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def sync_controls(self) -> None:
        scene = self.engine.scene_snapshot(self.side)
        layers = scene.get("layers", [])
        item = self.list_widget.currentItem()
        layer_index = int(item.data(Qt.ItemDataRole.UserRole)) if item else None
        self.add_button.setEnabled(sum(1 for layer in layers if layer.get("configured")) < 5)
        self.remove_button.setEnabled(item is not None)
        self.settings_button.setEnabled(item is not None)
        row = self.list_widget.currentRow()
        self.up_button.setEnabled(item is not None and row > 0)
        self.down_button.setEnabled(item is not None and row < self.list_widget.count() - 1)
        if layer_index is None or not (0 <= layer_index < len(layers)):
            self.filter_combo.setEnabled(False)
            self.blend_combo.setEnabled(False)
            self.brightness_spin.setEnabled(False)
            self.layer_selected.emit(self.side, -1)
            return
        layer = layers[layer_index]
        for widget, value in (
            (self.filter_combo, layer.get("filter", "None")),
            (self.blend_combo, layer.get("mix_mode", "Add")),
        ):
            widget.blockSignals(True)
            widget.setCurrentText(str(value))
            widget.blockSignals(False)
            widget.setEnabled(True)
        self.brightness_spin.blockSignals(True)
        self.brightness_spin.setValue(int(layer.get("brightness", 100)))
        self.brightness_spin.blockSignals(False)
        self.brightness_spin.setEnabled(True)
        self.layer_selected.emit(self.side, layer_index)

    def refresh_effect_list(self, selected_layer: int | None = None) -> None:
        scene = self.engine.scene_snapshot(self.side)
        layers = scene.get("layers", [])
        if selected_layer is None and self.list_widget.currentItem():
            selected_layer = int(self.list_widget.currentItem().data(Qt.ItemDataRole.UserRole))
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        row_to_select = 0
        for layer_index, layer in enumerate(layers):
            if not layer.get("configured"):
                continue
            item = QListWidgetItem(f"Layer {layer_index + 1}  ·  {layer.get('generator', 'Black')}")
            item.setData(Qt.ItemDataRole.UserRole, layer_index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if layer.get("enabled", True) else Qt.CheckState.Unchecked
            )
            self.list_widget.addItem(item)
            if layer_index == selected_layer:
                row_to_select = self.list_widget.count() - 1
        if self.list_widget.count():
            self.list_widget.setCurrentRow(row_to_select)
        self.list_widget.blockSignals(False)
        self.sync_controls()

    def _effect_item_changed(self, item: QListWidgetItem) -> None:
        layer_index = int(item.data(Qt.ItemDataRole.UserRole))
        self.engine.set_layer_enabled(self.side, layer_index, item.checkState() == Qt.CheckState.Checked)

    def _update_selected_layer(self, **options) -> None:
        index = self.selected_layer()
        if index is not None:
            self.engine.set_layer_options(self.side, index, **options)

    def add_effect_by_name(self, name: str) -> int | None:
        index = self.engine.add_layer(self.side, name)
        if index is not None:
            self.refresh_effect_list(index)
        return index

    def add_effect(self) -> None:
        scene = self.engine.scene_snapshot(self.side)
        if sum(1 for layer in scene.get("layers", []) if layer.get("configured")) >= 5:
            return
        picker = EffectPickerDialog(
            self,
            picker_effect_names(),
            effect_descriptions(),
            effect_categories(),
        )
        if picker.exec() != QDialog.DialogCode.Accepted or picker.selected_effect is None:
            return
        self.add_effect_by_name(picker.selected_effect)

    def remove_effect(self) -> None:
        index = self.selected_layer()
        if index is None:
            return
        self.engine.remove_layer(self.side, index)
        self.refresh_effect_list()

    def move_effect(self, direction: int) -> None:
        row = self.list_widget.currentRow()
        target_row = row + direction
        if row < 0 or not 0 <= target_row < self.list_widget.count():
            return
        source = int(self.list_widget.item(row).data(Qt.ItemDataRole.UserRole))
        target = int(self.list_widget.item(target_row).data(Qt.ItemDataRole.UserRole))
        self.engine.move_layer(self.side, source, target)
        self.refresh_effect_list(target)

    def _edit_selected_effect(self) -> None:
        index = self.selected_layer()
        if index is not None:
            self.show_generator_settings(index)

    def show_generator_settings(self, layer_index: int) -> None:
        scene = self.engine.scene_snapshot(self.side)
        layers = scene.get("layers", [])
        if not (0 <= layer_index < len(layers)):
            return
        layer = layers[layer_index]
        gen_name = layer.get("generator", "Black")
        schema = effect_settings(gen_name)
        if not schema:
            QMessageBox.information(self, "Effect settings", f"{gen_name} has no adjustable parameters.")
            return
        values = default_effect_parameters(gen_name)
        values.update(layer.get("parameters", {}))
        dialog = EffectSettingsDialog(
            self,
            f"{gen_name} settings · {self.side.upper()} / Layer {layer_index + 1}",
            schema,
            values,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.engine.set_generator_parameters(self.side, layer_index, dialog.values())
        self.status_message.emit(f"Updated {gen_name} settings")
