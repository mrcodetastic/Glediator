from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from glediator.core.engine import RenderEngine
from glediator.core.pipeline import LEGACY_FILTERS, MIX_MODES
from glediator.effects import (
    effect_categories,
    effect_descriptions,
    picker_effect_names,
)
from glediator.ui.dialogs.effect_picker import EffectPickerDialog


class SourcePanel(QGroupBox):
    status_message = Signal(str)
    layer_selected = Signal(str, int)
    inspect_requested = Signal(str, int)
    scene_mutated = Signal(str, dict, dict, str)

    def __init__(self, label: str, side: str, engine: RenderEngine, parent: QWidget | None = None) -> None:
        super().__init__(f"SOURCE {label}", parent)
        self.side = side
        self.engine = engine

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(125)
        self.list_widget.setMaximumHeight(175)
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_widget.setToolTip("Select an effect to inspect; drag to reorder; double-click to focus inspector.")
        self.list_widget.currentItemChanged.connect(lambda _c, _p: self.sync_controls())
        self.list_widget.itemChanged.connect(self._effect_item_changed)
        self.list_widget.itemDoubleClicked.connect(
            lambda item: self.inspect_requested.emit(self.side, int(item.data(Qt.ItemDataRole.UserRole)))
        )
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
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
        self.filter_combo.addItems(list(LEGACY_FILTERS))
        self.filter_combo.currentTextChanged.connect(lambda name: self._update_selected_layer(filter_name=name))
        form.addRow("Quick filter", self.filter_combo)

        self.blend_combo = QComboBox()
        self.blend_combo.addItems(list(MIX_MODES))
        self.blend_combo.currentTextChanged.connect(lambda name: self._update_selected_layer(mix_mode=name))
        form.addRow("Layer blend", self.blend_combo)

        self.brightness_spin = QSpinBox()
        self.brightness_spin.setRange(0, 100)
        self.brightness_spin.setValue(100)
        self.brightness_spin.setSuffix(" %")
        self.brightness_spin.valueChanged.connect(lambda value: self._update_selected_layer(brightness=value))
        form.addRow("Brightness", self.brightness_spin)

        self.settings_button = QPushButton("Inspect layer…")
        self.settings_button.clicked.connect(self._inspect_selected)
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
            item.setCheckState(Qt.CheckState.Checked if layer.get("enabled", True) else Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
            if layer_index == selected_layer:
                row_to_select = self.list_widget.count() - 1
        if self.list_widget.count():
            self.list_widget.setCurrentRow(row_to_select)
        self.list_widget.blockSignals(False)
        self.sync_controls()

    def _effect_item_changed(self, item: QListWidgetItem) -> None:
        layer_index = int(item.data(Qt.ItemDataRole.UserRole))
        before = self.engine.scene_snapshot(self.side)
        self.engine.set_layer_enabled(self.side, layer_index, item.checkState() == Qt.CheckState.Checked)
        after = self.engine.scene_snapshot(self.side)
        self.scene_mutated.emit(self.side, before, after, "Toggle layer")

    def _update_selected_layer(self, **options) -> None:
        index = self.selected_layer()
        if index is not None:
            before = self.engine.scene_snapshot(self.side)
            self.engine.set_layer_options(self.side, index, **options)
            after = self.engine.scene_snapshot(self.side)
            self.scene_mutated.emit(self.side, before, after, "Update layer options")
            self.layer_selected.emit(self.side, index)

    def add_effect_by_name(self, name: str) -> int | None:
        before = self.engine.scene_snapshot(self.side)
        index = self.engine.add_layer(self.side, name)
        if index is not None:
            after = self.engine.scene_snapshot(self.side)
            self.scene_mutated.emit(self.side, before, after, f"Add {name}")
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

    def duplicate_effect(self) -> None:
        index = self.selected_layer()
        if index is None:
            return
        before = self.engine.scene_snapshot(self.side)
        new_idx = self.engine.duplicate_layer(self.side, index)
        if new_idx is None:
            self.status_message.emit("All 5 layer slots are in use")
            return
        after = self.engine.scene_snapshot(self.side)
        self.scene_mutated.emit(self.side, before, after, "Duplicate layer")
        self.refresh_effect_list(new_idx)

    def remove_effect(self) -> None:
        index = self.selected_layer()
        if index is None:
            return
        before = self.engine.scene_snapshot(self.side)
        self.engine.remove_layer(self.side, index)
        after = self.engine.scene_snapshot(self.side)
        self.scene_mutated.emit(self.side, before, after, "Remove layer")
        self.refresh_effect_list()

    def move_effect(self, direction: int) -> None:
        row = self.list_widget.currentRow()
        target_row = row + direction
        if row < 0 or not 0 <= target_row < self.list_widget.count():
            return
        source = int(self.list_widget.item(row).data(Qt.ItemDataRole.UserRole))
        target = int(self.list_widget.item(target_row).data(Qt.ItemDataRole.UserRole))
        before = self.engine.scene_snapshot(self.side)
        self.engine.move_layer(self.side, source, target)
        after = self.engine.scene_snapshot(self.side)
        self.scene_mutated.emit(self.side, before, after, "Reorder layer")
        self.refresh_effect_list(target)

    def _on_rows_moved(self, _parent, start: int, _end: int, _dest, dest_row: int) -> None:
        # Apply drag-and-drop reorder to the underlying scene slots
        target_row = dest_row - 1 if dest_row > start else dest_row
        if target_row == start or not (0 <= target_row < self.list_widget.count()):
            return
        new_order = [
            int(self.list_widget.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.list_widget.count())
        ]
        before = self.engine.scene_snapshot(self.side)
        old_layers = before.get("layers", [])
        rebuilt = [old_layers[idx] for idx in new_order] + [
            layer for i, layer in enumerate(old_layers) if i not in new_order
        ]
        after_state = dict(before, layers=rebuilt)
        self.engine.load_scene_state(self.side, after_state)
        after = self.engine.scene_snapshot(self.side)
        self.scene_mutated.emit(self.side, before, after, "Drag reorder layer")
        self.refresh_effect_list(target_row)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        has_sel = self.selected_layer() is not None
        dup_act = QAction("Duplicate layer", menu)
        dup_act.setEnabled(has_sel)
        dup_act.triggered.connect(self.duplicate_effect)
        up_act = QAction("Move up", menu)
        up_act.setEnabled(self.up_button.isEnabled())
        up_act.triggered.connect(lambda: self.move_effect(-1))
        down_act = QAction("Move down", menu)
        down_act.setEnabled(self.down_button.isEnabled())
        down_act.triggered.connect(lambda: self.move_effect(1))
        rem_act = QAction("Remove", menu)
        rem_act.setEnabled(has_sel)
        rem_act.triggered.connect(self.remove_effect)
        rename_act = QAction("Rename source…", menu)
        rename_act.triggered.connect(self._rename_source)
        menu.addAction(dup_act)
        menu.addAction(up_act)
        menu.addAction(down_act)
        menu.addAction(rem_act)
        menu.addSeparator()
        menu.addAction(rename_act)
        menu.exec(self.list_widget.mapToGlobal(pos))

    def _rename_source(self) -> None:
        snap = self.engine.scene_snapshot(self.side)
        name, ok = QInputDialog.getText(self, "Rename Source", "Source name:", text=str(snap.get("name", "")))
        if ok and name.strip():
            self.engine.rename_scene(self.side, name.strip())

    def _inspect_selected(self) -> None:
        index = self.selected_layer()
        if index is not None:
            self.inspect_requested.emit(self.side, index)
