from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.network.discovery import DeviceDiscovery
from glediator.ui.dialogs.panel_config import PanelConfigDialog
from glediator.ui.panels.fader_panel import FaderPanel
from glediator.ui.panels.network_panel import NetworkPanel
from glediator.ui.panels.preset_bar import PresetBar
from glediator.ui.panels.source_panel import SourcePanel
from glediator.ui.preview import FramePreview
from glediator.ui.style import build_stylesheet


class MainWindow(QMainWindow):
    def __init__(self, engine: RenderEngine, config: EngineConfig) -> None:
        super().__init__()
        self.engine, self.config = engine, config
        self.setWindowTitle("Glediator — LED Matrix Studio")
        self.resize(1260, 780)
        self._build_menu()
        self._build_ui()
        self.setStyleSheet(build_stylesheet())
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
        if self.config.load_warning:
            self.statusBar().showMessage(self.config.load_warning, 6000)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        about_action = file_menu.addAction("About")
        about_action.triggered.connect(self._show_about)
        panel_config_action = file_menu.addAction("LED Panel Config…")
        panel_config_action.triggered.connect(self._show_panel_config)
        file_menu.addSeparator()
        save_action = file_menu.addAction("Save Settings")
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_settings)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Glediator",
            "<b>Glediator LED Matrix Studio</b><br>Python + Qt6 rebuild<br><br>"
            "Live effects, scene presets and MrCodetastic WebSocket output.<br><br>"
            "2026 Vibe coded by whatever LLM MrCodeTastic wanted to experiment with",
        )

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
        self.engine.set_matrix_size(width, height)
        self.config.width, self.config.height = width, height
        for preview in (self.left_preview, self.right_preview, self.mix_preview):
            preview.set_matrix_size(width, height)
        self._relayout_previews()
        self._save_settings()
        self.statusBar().showMessage(f"LED panel set to {width} × {height}", 4000)

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
        self.source_a_panel.status_message.connect(lambda msg: self.statusBar().showMessage(msg, 3000))
        self.source_b_panel.status_message.connect(lambda msg: self.statusBar().showMessage(msg, 3000))

        self.fader_panel = FaderPanel(self.engine)
        self.network_panel = NetworkPanel(self.engine, self.config)
        self.network_panel.status_message.connect(lambda msg: self.statusBar().showMessage(msg, 4000))
        self.network_panel.beacon_status_changed.connect(lambda msg: self.beacon_status.setText(msg))

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
        self.statusBar().showMessage("Ready · output is disabled until connected")

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
        self._save_settings()

    def _load_preset(self, name: str) -> None:
        preset = next((entry for entry in self.config.presets if entry["name"] == name), None)
        if not preset:
            return
        self.engine.restore_state(preset.get("state", {}))
        self.config.width, self.config.height = self.engine.config.width, self.engine.config.height
        for preview in (self.left_preview, self.right_preview, self.mix_preview):
            preview.set_matrix_size(self.config.width, self.config.height)
        self._relayout_previews()
        self.fader_panel.sync_from_engine()
        self.source_a_panel.refresh_effect_list()
        self.source_b_panel.refresh_effect_list()
        self._save_settings()
        self.statusBar().showMessage(f"Loaded scene preset: {name}", 3000)

    def _delete_preset(self, name: str) -> None:
        self.config.presets = [entry for entry in self.config.presets if entry["name"] != name]
        self.preset_bar.refresh()
        self._save_settings()

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
        if self.network_panel.output:
            self.network_panel.update_controls()
        frames = self.engine.snapshot()
        if not frames:
            return
        self.left_preview.set_frame(frames["left"])
        self.mix_preview.set_frame(frames["mixed"])
        self.right_preview.set_frame(frames["right"])

        eng_status = self.engine.status()
        status = f"●  {eng_status.fps:.0f} FPS  ·  {self.config.width} × {self.config.height}"
        if eng_status.layer_errors:
            (side, idx), msg = next(iter(eng_status.layer_errors.items()))
            side_tag = "A" if side == "left" else "B"
            status += "  ·  LAYER ERROR"
            self.statusBar().showMessage(f"{side_tag}/L{idx + 1}: {msg}")
        if eng_status.audio_error:
            status += "  ·  AUDIO INPUT ERROR"
            self.statusBar().showMessage(eng_status.audio_error)
        if self.network_panel.output:
            output = self.network_panel.output
            status += "  ·  OUTPUT ONLINE" if output.connected else "  ·  CONNECTING"
            if output.last_error:
                self.statusBar().showMessage(output.last_error)
        self.fps_label.setText(status)

    def closeEvent(self, event) -> None:
        self.discovery.stop()
        self.network_panel.disconnect_output()
        self.network_panel.sync_endpoint_to_config()
        self.config.live_state = self.engine.export_state()
        self.config.save()
        super().closeEvent(event)
