from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from glediator.control.actions import DEFAULT_SHORTCUTS, ActionRegistry, register_engine_actions
from glediator.control.midi import MidiController
from glediator.control.osc import OscController
from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.core.project import (
    AUTOSAVE_PATH,
    apply_project_to_config,
    build_project_payload,
    load_project,
    merge_imported_presets,
    save_project,
)
from glediator.effects.registry import USER_EFFECTS_DIR, plugin_warnings
from glediator.network.discovery import DeviceDiscovery
from glediator.ui.commands import (
    RestoreProjectStateCommand,
    RestoreSceneCommand,
    SetParametersCommand,
)
from glediator.ui.dialogs.controls_dialog import ControlsDialog, ShortcutsDialog
from glediator.ui.dialogs.palette_editor import PaletteEditorDialog
from glediator.ui.dialogs.panel_config import PanelConfigDialog
from glediator.ui.panels.fader_panel import FaderPanel
from glediator.ui.panels.inspector import LayerInspector
from glediator.ui.panels.network_panel import NetworkPanel
from glediator.ui.panels.performance_panel import PerformancePanel
from glediator.ui.panels.playlist_panel import PlaylistPanel
from glediator.ui.panels.preset_bar import PresetBar
from glediator.ui.panels.source_panel import SourcePanel
from glediator.ui.preview import FramePreview
from glediator.ui.style import build_stylesheet


class MainWindow(QMainWindow):
    def __init__(self, engine: RenderEngine, config: EngineConfig) -> None:
        super().__init__()
        self.engine, self.config = engine, config
        self._project_path: Path | None = None
        self._dirty = False
        self._recent_projects: list[str] = []
        self._qsettings = QSettings("Glediator", "Glediator")

        self.undo_stack = QUndoStack(self)
        self.action_registry = ActionRegistry()
        self.midi_controller = MidiController(self.action_registry)
        self.osc_controller = OscController(self.action_registry)
        self._shortcuts: list[QShortcut] = []

        self._build_ui()
        self._setup_controls()
        self._build_menu()
        self._apply_theme(self.config.ui.get("theme", "dark"))
        self._restore_window_state()
        self._update_title()

        self.beacon_status = QLabel("Listening for CODETASTIC beacons on UDP 20586")
        self.beacon_status.setObjectName("beaconStatus")
        self.beacon_status.setContentsMargins(0, 0, 4, 0)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setContentsMargins(4, 2, 4, 6)
        self.statusBar().addPermanentWidget(self.beacon_status)

        self.discovery = DeviceDiscovery()
        self.discovery.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(33)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start(60_000)

        warnings = plugin_warnings()
        if self.config.load_warning:
            self.statusBar().showMessage(self.config.load_warning, 6000)
        elif warnings:
            self.statusBar().showMessage(warnings[0], 6000)

    def _update_title(self) -> None:
        proj = self._project_path.name if self._project_path else "Untitled"
        star = "*" if self._dirty else ""
        self.setWindowTitle(f"Glediator — {proj}{star}")

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _setup_controls(self) -> None:
        register_engine_actions(
            self.action_registry,
            self.engine,
            self.config,
            load_preset_cb=self._load_preset,
            toggle_playlist_cb=self.playlist_panel.toggle_play,
        )
        self.midi_controller.set_mappings(self.config.controls.get("midi", []))
        osc_cfg = self.config.controls.get("osc", {})
        if osc_cfg.get("enabled"):
            self.osc_controller.start(port=int(osc_cfg.get("port", 9000)))
        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        for sc in self._shortcuts:
            sc.setParent(None)
        self._shortcuts.clear()
        bindings = {**DEFAULT_SHORTCUTS, **self.config.controls.get("keyboard", {})}
        for key, action_id in bindings.items():
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda aid=action_id: self.action_registry.invoke(aid))
            self._shortcuts.append(sc)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        new_act = file_menu.addAction("New Project")
        new_act.setShortcut("Ctrl+N")
        new_act.triggered.connect(self._new_project)
        open_act = file_menu.addAction("Open Project…")
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._open_project)
        save_proj_act = file_menu.addAction("Save Project")
        save_proj_act.setShortcut("Ctrl+S")
        save_proj_act.triggered.connect(self._save_project)
        save_as_act = file_menu.addAction("Save Project As…")
        save_as_act.setShortcut("Ctrl+Shift+S")
        save_as_act.triggered.connect(self._save_project_as)
        self.recent_menu = file_menu.addMenu("Recent Projects")
        self._refresh_recent_menu()
        file_menu.addSeparator()
        imp_presets = file_menu.addAction("Import Presets…")
        imp_presets.triggered.connect(self._import_presets)
        exp_presets = file_menu.addAction("Export Presets…")
        exp_presets.triggered.connect(self._export_presets)
        file_menu.addSeparator()
        panel_config_action = file_menu.addAction("LED Panel Config…")
        panel_config_action.triggered.connect(self._show_panel_config)
        save_settings_act = file_menu.addAction("Save Settings")
        save_settings_act.triggered.connect(self._save_settings)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)

        edit_menu = self.menuBar().addMenu("&Edit")
        undo_act = self.undo_stack.createUndoAction(self, "Undo")
        undo_act.setShortcut("Ctrl+Z")
        redo_act = self.undo_stack.createRedoAction(self, "Redo")
        redo_act.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        edit_menu.addAction(undo_act)
        edit_menu.addAction(redo_act)
        edit_menu.addSeparator()
        pal_act = edit_menu.addAction("Custom Palettes…")
        pal_act.triggered.connect(self._open_palette_editor)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.inspector_dock.toggleViewAction())
        view_menu.addAction(self.playlist_dock.toggleViewAction())
        view_menu.addAction(self.performance_dock.toggleViewAction())
        theme_menu = view_menu.addMenu("Theme")
        for theme_id, label in (("dark", "Dark"), ("light", "Light")):
            t_act = QAction(label, theme_menu)
            t_act.triggered.connect(lambda _c=False, tid=theme_id: self._apply_theme(tid))
            theme_menu.addAction(t_act)

        control_menu = self.menuBar().addMenu("&Control")
        midi_osc_action = control_menu.addAction("MIDI & OSC Settings…")
        midi_osc_action.triggered.connect(self._show_controls_dialog)

        help_menu = self.menuBar().addMenu("&Help")
        effects_dir_act = help_menu.addAction("Open Effects Folder")
        effects_dir_act.triggered.connect(self._open_effects_folder)
        shortcuts_action = help_menu.addAction("Keyboard Shortcuts…")
        shortcuts_action.triggered.connect(self._show_shortcuts)
        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self._show_about)

    def _apply_theme(self, theme: str) -> None:
        self.config.ui["theme"] = theme
        self.setStyleSheet(build_stylesheet(theme))
        for preview in (self.left_preview, self.right_preview, self.mix_preview):
            preview.apply_theme(theme)

    def _open_effects_folder(self) -> None:
        USER_EFFECTS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(USER_EFFECTS_DIR)))

    def _open_palette_editor(self) -> None:
        dlg = PaletteEditorDialog(self, self.config.palettes)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.engine.set_palettes(dlg.palettes)
            self._save_settings()
            self._sync_inspector_from_selection()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Glediator",
            "<b>Glediator LED Matrix Studio</b><br>Python + Qt6 rebuild<br><br>"
            "Live effects, scene presets and MrCodetastic WebSocket output.<br><br>"
            "2026 Vibe coded by whatever LLM MrCodeTastic wanted to experiment with",
        )

    def _show_shortcuts(self) -> None:
        dlg = ShortcutsDialog(self, self.config.controls.get("keyboard", {}), self.action_registry)
        dlg.exec()

    def _show_controls_dialog(self) -> None:
        dlg = ControlsDialog(self, self.config, self.action_registry, self.midi_controller, self.osc_controller)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._save_settings()

    def _save_settings(self) -> None:
        self.network_panel.sync_endpoint_to_config()
        self.config.live_state = self.engine.export_state()
        self.config.save()
        self.statusBar().showMessage("Settings, live sources and scene presets saved", 4000)

    def _show_panel_config(self) -> None:
        dialog = PanelConfigDialog(self, self.config.width, self.config.height)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height = dialog.dimensions()
        self._apply_matrix_size(width, height)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 3, 12, 8)

        header = QHBoxLayout()
        title = QLabel("GLEDIATOR")
        title.setObjectName("appTitle")
        subtitle = QLabel("REAL-TIME MATRIX STUDIO")
        subtitle.setObjectName("subtitle")
        header.addWidget(title)
        header.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        self.fps_label = QLabel("●  Starting renderer")
        self.fps_label.setObjectName("status")
        header.addWidget(self.fps_label)
        layout.addLayout(header)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setObjectName("headerDivider")
        layout.addWidget(divider)

        self.preset_bar = PresetBar(self.config)
        self.preset_bar.preset_saved.connect(self._save_preset)
        self.preset_bar.preset_loaded.connect(self._load_preset)
        self.preset_bar.preset_deleted.connect(self._delete_preset)
        layout.addWidget(self.preset_bar)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        self.left_preview = FramePreview("LIVE A  ·  SOURCE A", "#3c9eff", self.config.width, self.config.height)
        self.right_preview = FramePreview("LIVE B  ·  SOURCE B", "#c56bff", self.config.width, self.config.height)
        self.mix_preview = FramePreview("FINAL OUTPUT", "#ffb84a", self.config.width, self.config.height)

        self.source_a_panel = SourcePanel("A", "left", self.engine)
        self.source_b_panel = SourcePanel("B", "right", self.engine)
        for panel in (self.source_a_panel, self.source_b_panel):
            panel.status_message.connect(lambda msg: self.statusBar().showMessage(msg, 3000))
            panel.layer_selected.connect(self._on_layer_selected)
            panel.inspect_requested.connect(self._on_inspect_requested)
            panel.scene_mutated.connect(self._on_scene_mutated)

        self.fader_panel = FaderPanel(self.engine)
        self.fader_panel.copy_scene_requested.connect(self._copy_scene)
        self.fader_panel.swap_scenes_requested.connect(self._swap_scenes)

        self.network_panel = NetworkPanel(self.engine, self.config)
        self.network_panel.status_message.connect(lambda msg: self.statusBar().showMessage(msg, 4000))
        self.network_panel.beacon_status_changed.connect(lambda msg: self.beacon_status.setText(msg))
        self.network_panel.matrix_size_requested.connect(self._apply_matrix_size)

        for preview, panel in (
            (self.left_preview, self.source_a_panel),
            (self.right_preview, self.source_b_panel),
        ):
            col = QVBoxLayout()
            col.setSpacing(10)
            col.addWidget(preview)
            col.addWidget(panel)
            col.addStretch(1)
            columns.addLayout(col, 1)

        output_col = QVBoxLayout()
        output_col.setSpacing(10)
        output_col.addWidget(self.mix_preview)
        output_col.addWidget(self.fader_panel)
        output_col.addWidget(self.network_panel, 1)
        columns.addLayout(output_col, 1)

        layout.addLayout(columns, 1)

        self.inspector = LayerInspector(self.engine)
        self.inspector.parameters_committed.connect(self._on_params_committed)
        self.inspector.layer_options_changed.connect(self._on_inspector_options_changed)
        self.inspector_dock = QDockWidget("Layer Inspector", self)
        self.inspector_dock.setObjectName("inspectorDock")
        self.inspector_dock.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)

        self.playlist_panel = PlaylistPanel(self.engine, self.config)
        self.playlist_panel.playlists_changed.connect(self._save_settings)
        self.playlist_dock = QDockWidget("Playlist / Sequencer", self)
        self.playlist_dock.setObjectName("playlistDock")
        self.playlist_dock.setWidget(self.playlist_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.playlist_dock)
        self.playlist_dock.hide()

        self.performance_panel = PerformancePanel(self.config.fps)
        self.performance_dock = QDockWidget("Performance", self)
        self.performance_dock.setObjectName("performanceDock")
        self.performance_dock.setWidget(self.performance_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.performance_dock)
        self.performance_dock.hide()

        self._on_layer_selected("left", self.source_a_panel.selected_layer() or -1)
        self.statusBar().showMessage("Ready · output is disabled until connected")

    def _on_layer_selected(self, side: str, layer_index: int) -> None:
        self.inspector.inspect(side, layer_index)

    def _on_inspect_requested(self, side: str, layer_index: int) -> None:
        self.inspector_dock.show()
        self.inspector_dock.raise_()
        self.inspector.inspect(side, layer_index)

    def _sync_inspector_from_selection(self) -> None:
        self.source_a_panel.refresh_effect_list()
        self.source_b_panel.refresh_effect_list()

    def _on_scene_mutated(self, side: str, before: dict, after: dict, text: str) -> None:
        self._mark_dirty()
        cmd = RestoreSceneCommand(
            self.engine,
            side,
            before,
            after,
            text,
            lambda s=side: (
                self.source_a_panel.refresh_effect_list() if s == "left" else self.source_b_panel.refresh_effect_list()
            ),
        )
        self.undo_stack.push(cmd)

    def _on_params_committed(self, side: str, layer_index: int, before: dict, after: dict) -> None:
        self._mark_dirty()
        cmd = SetParametersCommand(
            self.engine,
            side,
            layer_index,
            before,
            after,
            lambda: self.inspector.inspect(side, layer_index),
        )
        self.undo_stack.push(cmd)

    def _on_inspector_options_changed(self) -> None:
        self._mark_dirty()
        self.source_a_panel.sync_controls()
        self.source_b_panel.sync_controls()

    def _copy_scene(self, src_side: str, dst_side: str) -> None:
        before = self.engine.export_state()
        self.engine.copy_scene(src_side, dst_side)
        after = self.engine.export_state()
        self._sync_all_after_state_restore()
        self.undo_stack.push(
            RestoreProjectStateCommand(
                self.engine,
                before,
                after,
                f"Copy {src_side} to {dst_side}",
                self._sync_all_after_state_restore,
            )
        )
        self._mark_dirty()

    def _swap_scenes(self) -> None:
        before = self.engine.export_state()
        self.engine.swap_scenes()
        after = self.engine.export_state()
        self._sync_all_after_state_restore()
        self.undo_stack.push(
            RestoreProjectStateCommand(
                self.engine,
                before,
                after,
                "Swap A and B",
                self._sync_all_after_state_restore,
            )
        )
        self._mark_dirty()

    def _sync_all_after_state_restore(self) -> None:
        self.config.width, self.config.height = self.engine.config.width, self.engine.config.height
        for preview in (self.left_preview, self.right_preview, self.mix_preview):
            preview.set_matrix_size(self.config.width, self.config.height)
        self._relayout_previews()
        self.fader_panel.sync_from_engine()
        self.source_a_panel.refresh_effect_list()
        self.source_b_panel.refresh_effect_list()

    def _apply_matrix_size(self, width: int, height: int) -> None:
        self.engine.set_matrix_size(width, height)
        self.config.width, self.config.height = width, height
        for preview in (self.left_preview, self.right_preview, self.mix_preview):
            preview.set_matrix_size(width, height)
        self._relayout_previews()
        self._mark_dirty()
        self._save_settings()
        self.statusBar().showMessage(f"LED panel set to {width} × {height}", 4000)

    def _save_preset(self, name: str) -> None:
        preset = {"name": name, "state": self.engine.export_state()}
        existing = next(
            (i for i, entry in enumerate(self.config.presets) if entry["name"].casefold() == name.casefold()),
            None,
        )
        if existing is None:
            self.config.presets.append(preset)
        else:
            self.config.presets[existing] = preset
        self.preset_bar.refresh(name)
        self.playlist_panel.refresh_presets()
        self._mark_dirty()
        self._save_settings()

    def _load_preset(self, name: str) -> None:
        preset = next((entry for entry in self.config.presets if entry["name"] == name), None)
        if not preset:
            return
        before = self.engine.export_state()
        self.engine.restore_state(preset.get("state", {}))
        after = self.engine.export_state()
        self._sync_all_after_state_restore()
        self.undo_stack.push(
            RestoreProjectStateCommand(
                self.engine,
                before,
                after,
                f"Load preset {name}",
                self._sync_all_after_state_restore,
            )
        )
        self._save_settings()
        self.statusBar().showMessage(f"Loaded scene preset: {name}", 3000)

    def _delete_preset(self, name: str) -> None:
        self.config.presets = [entry for entry in self.config.presets if entry["name"] != name]
        self.preset_bar.refresh()
        self.playlist_panel.refresh_presets()
        self._mark_dirty()
        self._save_settings()

    def _new_project(self) -> None:
        fresh = EngineConfig(width=self.config.width, height=self.config.height)
        self.config.presets.clear()
        self.config.playlists.clear()
        self.engine.restore_state(RenderEngine(fresh).export_state())
        self._project_path = None
        self._dirty = False
        self.undo_stack.clear()
        self.preset_bar.refresh()
        self.playlist_panel.refresh_presets()
        self.playlist_panel.refresh_playlists()
        self._sync_all_after_state_restore()
        self._update_title()

    def _open_project(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "Glediator Projects (*.gled);;All Files (*)"
        )
        if file_name:
            self.load_project_file(Path(file_name))

    def load_project_file(self, path: Path) -> None:
        data = load_project(path)
        live_state = apply_project_to_config(data, self.config)
        self.engine.set_palettes(self.config.palettes)
        self.engine.restore_state(live_state)
        self._project_path = path
        self._dirty = False
        self.undo_stack.clear()
        self.preset_bar.refresh()
        self.playlist_panel.refresh_presets()
        self.playlist_panel.refresh_playlists()
        self._sync_all_after_state_restore()
        self._record_recent_project(path)
        self._update_title()
        self.statusBar().showMessage(f"Opened project: {path.name}", 4000)

    def _save_project(self) -> None:
        if self._project_path is None:
            self._save_project_as()
            return
        self.save_project_file(self._project_path)

    def _save_project_as(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Project As", "", "Glediator Projects (*.gled)")
        if not file_name:
            return
        path = Path(file_name)
        if path.suffix.lower() != ".gled":
            path = path.with_suffix(".gled")
        self.save_project_file(path)

    def save_project_file(self, path: Path, *, include_devices: bool = False) -> None:
        payload = build_project_payload(self.config, self.engine.export_state(), include_devices=include_devices)
        save_project(path, payload)
        self._project_path = path
        self._dirty = False
        self._record_recent_project(path)
        self._update_title()
        self.statusBar().showMessage(f"Saved project: {path.name}", 4000)

    def _import_presets(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Import Presets", "", "JSON / Glediator (*.json *.gled)")
        if not file_name:
            return
        raw = json.loads(Path(file_name).read_text(encoding="utf-8"))
        items = raw.get("presets", raw) if isinstance(raw, dict) else raw
        if isinstance(items, list):
            self.config.presets = merge_imported_presets(self.config.presets, items)
            self.preset_bar.refresh()
            self.playlist_panel.refresh_presets()
            self._mark_dirty()
            self._save_settings()

    def _export_presets(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(self, "Export Presets", "presets.json", "JSON (*.json)")
        if not file_name:
            return
        Path(file_name).write_text(json.dumps({"presets": self.config.presets}, indent=2), encoding="utf-8")

    def _record_recent_project(self, path: Path) -> None:
        resolved = str(path)
        recent = [p for p in self._recent_projects if p != resolved]
        recent.insert(0, resolved)
        self._recent_projects = recent[:5]
        self._qsettings.setValue("recent_projects", self._recent_projects)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        if not hasattr(self, "recent_menu"):
            return
        stored = self._qsettings.value("recent_projects", [])
        if isinstance(stored, list):
            self._recent_projects = [str(p) for p in stored[:5]]
        self.recent_menu.clear()
        for path_str in self._recent_projects:
            act = self.recent_menu.addAction(path_str)
            act.triggered.connect(lambda _c=False, p=Path(path_str): self.load_project_file(p))
        self.recent_menu.setEnabled(bool(self._recent_projects))

    def _restore_window_state(self) -> None:
        geom = self._qsettings.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        state = self._qsettings.value("windowState")
        if state is not None:
            self.restoreState(state)

    def _autosave(self) -> None:
        try:
            payload = build_project_payload(self.config, self.engine.export_state())
            save_project(AUTOSAVE_PATH, payload)
        except OSError:
            pass

    def _relayout_previews(self) -> None:
        central = self.centralWidget()
        if central and central.layout():
            central.layout().invalidate()
            central.layout().activate()
        self.updateGeometry()
        required_height = self.minimumSizeHint().height()
        if required_height > self.height():
            screen = self.screen()
            if screen:
                required_height = min(required_height, screen.availableGeometry().height())
            self.resize(self.width(), required_height)

    def _refresh(self) -> None:
        self.network_panel.handle_discovery_events(self.discovery.poll_events())
        eng_status = self.engine.status()
        self.network_panel.update_controls(eng_status.outputs)
        self.fader_panel.sync_from_status(eng_status)
        self.playlist_panel.sync_status(eng_status.sequencer)
        if self.performance_dock.isVisible():
            self.performance_panel.update_status(eng_status, self.config.fps)
        self.mix_preview.set_badge(
            "BLACKOUT" if eng_status.blackout else "FROZEN" if eng_status.freeze else ""
        )

        frames = self.engine.snapshot()
        if not frames:
            return
        self.left_preview.set_frame(frames["left"])
        self.mix_preview.set_frame(frames["mixed"])
        self.right_preview.set_frame(frames["right"])

        status = f"●  {eng_status.fps:.0f} FPS  ·  {self.config.width} × {self.config.height}"
        if eng_status.layer_errors:
            (side, idx), msg = next(iter(eng_status.layer_errors.items()))
            side_tag = "A" if side == "left" else "B"
            status += "  ·  LAYER ERROR"
            self.statusBar().showMessage(f"{side_tag}/L{idx + 1}: {msg}")
        if eng_status.audio_error:
            status += "  ·  AUDIO INPUT ERROR"
            self.statusBar().showMessage(eng_status.audio_error)
        if eng_status.outputs:
            states = [st.state for st in eng_status.outputs.values()]
            if any(s == "mismatch" for s in states):
                status += "  ·  SIZE MISMATCH"
            elif any(s == "online" for s in states):
                status += "  ·  OUTPUT ONLINE"
            elif any(s == "connecting" for s in states):
                status += "  ·  CONNECTING"
            elif any(s == "error" for s in states):
                status += "  ·  OUTPUT ERROR"
            errors = [st.last_error for st in eng_status.outputs.values() if st.last_error]
            if errors:
                self.statusBar().showMessage(errors[0])
        self.fps_label.setText(status)

    def closeEvent(self, event) -> None:
        self._qsettings.setValue("geometry", self.saveGeometry())
        self._qsettings.setValue("windowState", self.saveState())
        self.discovery.stop()
        self.midi_controller.stop()
        self.osc_controller.stop()
        self.network_panel.disconnect_output()
        self.network_panel.sync_endpoint_to_config()
        self.config.live_state = self.engine.export_state()
        self.config.save()
        super().closeEvent(event)
