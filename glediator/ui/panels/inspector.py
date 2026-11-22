from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from glediator.core.engine import RenderEngine
from glediator.core.filters import FILTER_NAMES, FILTER_SCHEMAS, sanitize_filter_params
from glediator.core.pipeline import MIX_MODES
from glediator.core.scene import MODULATION_SOURCES
from glediator.effects import default_effect_parameters, effect_descriptions, effect_settings
from glediator.ui.dialogs.effect_settings import FilePickerWidget, create_param_editor, read_param_editor
from glediator.ui.widgets.color_button import ColorButton


class ModulationDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        param_name: str,
        low: float,
        high: float,
        existing: dict | None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Modulate {param_name}")
        form = QFormLayout(self)
        self.enabled_chk = QCheckBox("Enable modulation")
        self.enabled_chk.setChecked(existing is not None)
        form.addRow(self.enabled_chk)

        self.source_combo = QComboBox()
        self.source_combo.addItems(list(MODULATION_SOURCES))
        if existing:
            self.source_combo.setCurrentText(str(existing.get("source", "bass")))
        form.addRow("Source", self.source_combo)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.0, 2.0)
        self.amount_spin.setSingleStep(0.1)
        self.amount_spin.setValue(float(existing.get("amount", 1.0)) if existing else 1.0)
        form.addRow("Amount", self.amount_spin)

        self.min_spin = QDoubleSpinBox()
        self.min_spin.setRange(float(low), float(high))
        self.min_spin.setDecimals(3)
        self.min_spin.setValue(float(existing.get("min", low)) if existing else float(low))
        form.addRow("Min", self.min_spin)

        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(float(low), float(high))
        self.max_spin.setDecimals(3)
        self.max_spin.setValue(float(existing.get("max", high)) if existing else float(high))
        form.addRow("Max", self.max_spin)

        self.smooth_spin = QDoubleSpinBox()
        self.smooth_spin.setRange(0.0, 0.98)
        self.smooth_spin.setSingleStep(0.05)
        self.smooth_spin.setValue(float(existing.get("smoothing", 0.3)) if existing else 0.3)
        form.addRow("Smoothing", self.smooth_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.param_name = param_name

    def result_entry(self) -> dict | None:
        if not self.enabled_chk.isChecked():
            return None
        return {
            "param": self.param_name,
            "source": self.source_combo.currentText(),
            "amount": float(self.amount_spin.value()),
            "min": float(self.min_spin.value()),
            "max": float(self.max_spin.value()),
            "smoothing": float(self.smooth_spin.value()),
        }


class LayerInspector(QWidget):
    parameters_committed = Signal(str, int, dict, dict)  # side, layer, before, after
    layer_options_changed = Signal()

    def __init__(self, engine: RenderEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self._side: str = "left"
        self._layer_index: int = -1
        self._gen_name: str = ""
        self._editors: dict[str, QWidget] = {}
        self._mod_buttons: dict[str, QPushButton] = {}
        self._before_params: dict = {}
        self._modulations: list[dict] = []
        self._filters: list[dict] = []
        self._syncing = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(50)
        self._debounce.timeout.connect(self._flush_params)

        self.setMinimumWidth(335)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        self.header_label = QLabel("No layer selected")
        self.header_label.setStyleSheet("font-weight:700;")
        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color:#8ea0b4; font-size:8.5pt;")
        outer.addWidget(self.header_label)
        outer.addWidget(self.desc_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        scroll.setWidget(self._content)
        outer.addWidget(scroll, 1)

        # Blend / Opacity / Brightness
        mix_box = QGroupBox("Layer Mixing")
        mix_form = QFormLayout(mix_box)
        self.blend_combo = QComboBox()
        self.blend_combo.addItems(list(MIX_MODES))
        self.blend_combo.currentTextChanged.connect(self._on_mix_changed)
        mix_form.addRow("Blend mode", self.blend_combo)

        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.valueChanged.connect(self._on_mix_changed)
        mix_form.addRow("Opacity", self.opacity_spin)

        self.brightness_spin = QSpinBox()
        self.brightness_spin.setRange(0, 100)
        self.brightness_spin.setSuffix(" %")
        self.brightness_spin.valueChanged.connect(self._on_mix_changed)
        mix_form.addRow("Brightness", self.brightness_spin)
        self._content_layout.addWidget(mix_box)

        # Effect Parameters
        self.params_box = QGroupBox("Effect Parameters")
        self.params_form = QFormLayout(self.params_box)
        self._content_layout.addWidget(self.params_box)

        self.reset_btn = QPushButton("Reset to defaults")
        self.reset_btn.clicked.connect(self._reset_defaults)
        self._content_layout.addWidget(self.reset_btn)

        # Filter Chain
        filter_box = QGroupBox("Filter Chain (max 3)")
        filter_layout = QVBoxLayout(filter_box)
        self.filter_list = QListWidget()
        self.filter_list.setMaximumHeight(90)
        self.filter_list.currentRowChanged.connect(self._rebuild_filter_params)
        filter_layout.addWidget(self.filter_list)

        f_actions = QHBoxLayout()
        self.filter_add_combo = QComboBox()
        self.filter_add_combo.addItems(list(FILTER_NAMES))
        add_f_btn = QPushButton("+ Add")
        add_f_btn.clicked.connect(self._add_filter)
        rem_f_btn = QPushButton("Remove")
        rem_f_btn.clicked.connect(self._remove_filter)
        f_actions.addWidget(self.filter_add_combo, 1)
        f_actions.addWidget(add_f_btn)
        f_actions.addWidget(rem_f_btn)
        filter_layout.addLayout(f_actions)

        self.filter_params_form = QFormLayout()
        filter_layout.addLayout(self.filter_params_form)
        self._content_layout.addWidget(filter_box)
        self._content_layout.addStretch(1)

        self.setEnabled(False)

    def inspect(self, side: str, layer_index: int) -> None:
        self._debounce.stop()
        self._side = side
        self._layer_index = layer_index
        if layer_index < 0:
            self.header_label.setText("No layer selected")
            self.desc_label.setText("")
            self.setEnabled(False)
            return

        snap = self.engine.scene_snapshot(side)
        layers = snap.get("layers", [])
        if not (0 <= layer_index < len(layers)) or not layers[layer_index].get("configured"):
            self.setEnabled(False)
            return

        layer = layers[layer_index]
        self._syncing = True
        self.setEnabled(True)
        self._gen_name = str(layer.get("generator", "Black"))
        side_label = "Source A" if side == "left" else "Source B"
        self.header_label.setText(f"{side_label} · Layer {layer_index + 1} · {self._gen_name}")
        self.desc_label.setText(effect_descriptions().get(self._gen_name, ""))

        self.blend_combo.setCurrentText(str(layer.get("mix_mode", "Add")))
        self.opacity_spin.setValue(int(layer.get("opacity", 100)))
        self.brightness_spin.setValue(int(layer.get("brightness", 100)))

        self._modulations = list(layer.get("modulations", []))
        self._filters = list(layer.get("filters", []))
        self._before_params = dict(default_effect_parameters(self._gen_name))
        self._before_params.update(layer.get("parameters", {}))

        self._rebuild_param_editors(self._before_params)
        self._refresh_filter_list()
        self._syncing = False

    def _clear_form(self, form: QFormLayout) -> None:
        while form.rowCount() > 0:
            form.removeRow(0)

    def _rebuild_param_editors(self, values: dict) -> None:
        self._clear_form(self.params_form)
        self._editors.clear()
        self._mod_buttons.clear()
        schema = effect_settings(self._gen_name)
        mod_map = {m["param"]: m for m in self._modulations}
        for key, spec in schema.items():
            kind, default, low, high, step = spec
            val = values.get(key, default)
            editor = create_param_editor(kind, default, low, high, step, val, key=key)
            self._editors[key] = editor
            self._wire_editor_signal(editor)

            label = {
                "bins": "Bin count (0 = panel width)",
                "bin_width": "Bin width (pixels)",
                "capture_fps": "Capture rate (FPS, max 30)",
            }.get(key, key.replace("_", " ").title())

            if kind in ("int", "float"):
                row_w = QWidget()
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(0, 0, 0, 0)
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setMinimumWidth(42)
                editor.setMinimumWidth(108)
                editor.setMaximumWidth(120)
                scale = 1 if kind == "int" else 1000
                slider.setRange(round(float(low) * scale), round(float(high) * scale))
                slider.setValue(round(float(val) * scale))
                slider.valueChanged.connect(
                    lambda sv, ed=editor, sc=scale: ed.setValue(round(sv / sc) if sc == 1 else sv / sc)
                )
                editor.valueChanged.connect(
                    lambda ev, sl=slider, sc=scale: (
                        sl.blockSignals(True),
                        sl.setValue(round(float(ev) * sc)),
                        sl.blockSignals(False),
                    )
                )
                mod_btn = QPushButton("~")
                mod_btn.setFixedWidth(28)
                mod_btn.setToolTip("Configure audio/LFO modulation")
                if key in mod_map:
                    mod_btn.setStyleSheet("background:#d97706; color:white; padding:2px 4px;")
                else:
                    mod_btn.setStyleSheet("padding:2px 4px;")
                mod_btn.clicked.connect(
                    lambda _c=False, k=key, lo=low, hi=high: self._edit_modulation(k, float(lo), float(hi))
                )
                self._mod_buttons[key] = mod_btn
                row_l.addWidget(slider, 1)
                row_l.addWidget(editor)
                row_l.addWidget(mod_btn)
                self.params_form.addRow(label, row_w)
            else:
                self.params_form.addRow(label, editor)

    def _wire_editor_signal(self, editor: QWidget) -> None:
        if isinstance(editor, QCheckBox):
            editor.toggled.connect(self._schedule_params)
        elif isinstance(editor, FilePickerWidget):
            editor.line_edit.textChanged.connect(self._schedule_params)
        elif isinstance(editor, QLineEdit):
            editor.textChanged.connect(self._schedule_params)
        elif isinstance(editor, ColorButton):
            editor.color_changed.connect(self._schedule_params)
        elif isinstance(editor, QComboBox):
            editor.currentTextChanged.connect(self._schedule_params)
        elif hasattr(editor, "valueChanged"):
            editor.valueChanged.connect(self._schedule_params)

    def _schedule_params(self, *_args) -> None:
        if self._syncing or self._layer_index < 0:
            return
        self._debounce.start()

    def _flush_params(self) -> None:
        if self._layer_index < 0:
            return
        new_params = {key: read_param_editor(ed) for key, ed in self._editors.items()}
        if new_params != self._before_params:
            self.engine.set_generator_parameters(self._side, self._layer_index, new_params)
            self.parameters_committed.emit(self._side, self._layer_index, self._before_params, new_params)
            self._before_params = dict(new_params)

    def _reset_defaults(self) -> None:
        if self._layer_index < 0:
            return
        defaults = default_effect_parameters(self._gen_name)
        self.engine.set_generator_parameters(self._side, self._layer_index, defaults)
        self.parameters_committed.emit(self._side, self._layer_index, self._before_params, defaults)
        self.inspect(self._side, self._layer_index)

    def _edit_modulation(self, param_name: str, low: float, high: float) -> None:
        if self._layer_index < 0:
            return
        existing = next((m for m in self._modulations if m.get("param") == param_name), None)
        dlg = ModulationDialog(self, param_name, low, high, existing)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._modulations = [m for m in self._modulations if m.get("param") != param_name]
        new_entry = dlg.result_entry()
        if new_entry is not None:
            self._modulations.append(new_entry)
        self.engine.set_layer_modulations(self._side, self._layer_index, self._modulations)
        btn = self._mod_buttons.get(param_name)
        if btn:
            btn.setStyleSheet(
                "background:#d97706; color:white; padding:2px 4px;" if new_entry else "padding:2px 4px;"
            )

    def _on_mix_changed(self, *_args) -> None:
        if self._syncing or self._layer_index < 0:
            return
        self.engine.set_layer_options(
            self._side,
            self._layer_index,
            brightness=self.brightness_spin.value(),
            opacity=self.opacity_spin.value(),
            mix_mode=self.blend_combo.currentText(),
        )
        self.layer_options_changed.emit()

    def _refresh_filter_list(self) -> None:
        self.filter_list.blockSignals(True)
        cur = self.filter_list.currentRow()
        self.filter_list.clear()
        for entry in self._filters:
            self.filter_list.addItem(str(entry.get("name", "")))
        if self._filters:
            self.filter_list.setCurrentRow(max(0, min(cur, len(self._filters) - 1)))
        self.filter_list.blockSignals(False)
        self._rebuild_filter_params(self.filter_list.currentRow())

    def _add_filter(self) -> None:
        if self._layer_index < 0 or len(self._filters) >= 3:
            return
        name = self.filter_add_combo.currentText()
        self._filters.append({"name": name, "params": sanitize_filter_params(name, {})})
        self.engine.set_layer_options(self._side, self._layer_index, filters=self._filters)
        self._refresh_filter_list()
        self.layer_options_changed.emit()

    def _remove_filter(self) -> None:
        row = self.filter_list.currentRow()
        if self._layer_index < 0 or not (0 <= row < len(self._filters)):
            return
        self._filters.pop(row)
        self.engine.set_layer_options(self._side, self._layer_index, filters=self._filters)
        self._refresh_filter_list()
        self.layer_options_changed.emit()

    def _rebuild_filter_params(self, row: int) -> None:
        self._clear_form(self.filter_params_form)
        if not (0 <= row < len(self._filters)):
            return
        entry = self._filters[row]
        name = entry.get("name", "")
        schema = FILTER_SCHEMAS.get(name, {})
        params = entry.get("params", {})
        for key, spec in schema.items():
            kind, default, low, high, step = spec
            ed = create_param_editor(kind, default, low, high, step, params.get(key, default))

            def _apply(_v=None, idx=row, k=key, editor=ed) -> None:
                if 0 <= idx < len(self._filters):
                    self._filters[idx]["params"][k] = read_param_editor(editor)
                    self.engine.set_layer_options(self._side, self._layer_index, filters=self._filters)

            if isinstance(ed, ColorButton):
                ed.color_changed.connect(_apply)
            elif isinstance(ed, QComboBox):
                ed.currentTextChanged.connect(_apply)
            elif hasattr(ed, "valueChanged"):
                ed.valueChanged.connect(_apply)
            self.filter_params_form.addRow(key.replace("_", " ").title(), ed)
