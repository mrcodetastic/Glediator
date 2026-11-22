from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.network.discovery import DeviceDiscovery
from glediator.output.mrcodetastic_websocket import MrCodetasticWebSocketOutput


class NetworkPanel(QGroupBox):
    status_message = Signal(str)
    beacon_status_changed = Signal(str)

    def __init__(self, engine: RenderEngine, config: EngineConfig, parent: QWidget | None = None) -> None:
        super().__init__("NETWORK OUTPUT", parent)
        self.engine = engine
        self.config = config
        self.output: MrCodetasticWebSocketOutput | None = None
        self.discovered_ips: set[str] = set()
        self.device_connect_buttons: dict[str, QPushButton] = {}
        self._connection_button: QPushButton | None = None
        self._connected_device_ip: str | None = None

        layout = QVBoxLayout(self)
        self.device_hint = QLabel("Searching for CODETASTIC devices…")
        self.device_hint.setWordWrap(True)
        layout.addWidget(self.device_hint)

        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(68)
        self.device_list.setMaximumHeight(170)
        self.device_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.device_list)

        self.manual_toggle = QCheckBox("Connect manually")
        self.manual_toggle.toggled.connect(self._show_manual_connection)
        layout.addWidget(self.manual_toggle)

        self.manual_form = QWidget()
        manual_row = QHBoxLayout(self.manual_form)
        manual_row.setContentsMargins(0, 0, 0, 0)
        self.websocket_host = QLineEdit(self.config.websocket_host)
        self.websocket_host.setPlaceholderText("IP address or host")
        self.websocket_host.setMaxLength(253)
        self.websocket_host.setMinimumWidth(self.fontMetrics().horizontalAdvance("0" * 16) + 20)
        self.websocket_port = QLineEdit(str(self.config.websocket_port))
        self.websocket_port.setValidator(QIntValidator(1, 65535, self.websocket_port))
        self.websocket_port.setMaxLength(5)
        self.websocket_port.setFixedWidth(self.fontMetrics().horizontalAdvance("0" * 5) + 20)
        self.manual_connect_button = QPushButton("Connect")
        self.manual_connect_button.setFixedWidth(98)
        self.manual_connect_button.setMinimumHeight(34)
        self.manual_connect_button.clicked.connect(self._connect_manually)
        manual_row.addWidget(self.websocket_host, 1)
        manual_row.addWidget(QLabel(":"))
        manual_row.addWidget(self.websocket_port)
        manual_row.addWidget(self.manual_connect_button)
        self.manual_form.setVisible(False)
        layout.addWidget(self.manual_form)

    def sync_endpoint_to_config(self) -> None:
        self.config.websocket_host = self.websocket_host.text().strip() or self.config.websocket_host
        try:
            self.config.websocket_port = int(self.websocket_port.text())
        except ValueError:
            pass

    def handle_discovery_events(self, events: list[tuple[str, str]]) -> None:
        for event, payload in events:
            if event == "device":
                self.add_discovered_device(payload)
            elif event == "error":
                self._discovery_error(payload)
            elif event == "ready":
                self._discovery_ready()

    def add_discovered_device(self, address: str) -> None:
        if address in self.discovered_ips:
            return
        self.discovered_ips.add(address)
        self.device_hint.setVisible(False)
        item = QListWidgetItem(self.device_list)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(5, 2, 5, 2)
        ip_label = QLabel(f"{address}  ·  WS :{DeviceDiscovery.WEBSOCKET_PORT}")
        ip_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        connect_button = QPushButton("Connect")
        connect_button.setMinimumWidth(100)
        connect_button.setMinimumHeight(34)
        connect_button.clicked.connect(
            lambda _checked=False, ip=address, button=connect_button: self._toggle_discovered_output(ip, button)
        )
        row_layout.addWidget(ip_label, 1)
        row_layout.addWidget(connect_button)
        item.setSizeHint(QSize(max(260, self.device_list.viewport().width()), 47))
        self.device_list.setItemWidget(item, row)
        self.device_connect_buttons[address] = connect_button
        self.update_controls()

    def _discovery_ready(self) -> None:
        if not self.discovered_ips:
            self.device_hint.setText("No devices found yet. Listening for CODETASTIC beacons…")
        self.beacon_status_changed.emit("Listening for CODETASTIC beacons on UDP 20586")

    def _discovery_error(self, message: str) -> None:
        self.device_hint.setText("Discovery unavailable. Use Connect manually.")
        self.device_hint.setVisible(True)
        self.beacon_status_changed.emit("CODETASTIC discovery unavailable")
        self.status_message.emit(message)

    def _show_manual_connection(self, visible: bool) -> None:
        self.manual_form.setVisible(visible)

    def _connect_manually(self) -> None:
        if self.output:
            if self._connection_button is self.manual_connect_button:
                self.disconnect_output()
            return
        host = self.websocket_host.text().strip()
        if not host:
            QMessageBox.warning(self, "WebSocket destination", "Enter a destination IP address or host name.")
            return
        try:
            port = int(self.websocket_port.text())
        except ValueError:
            port = 0
        if not 1 <= port <= 65535:
            QMessageBox.warning(self, "WebSocket destination", "Enter a port from 1 to 65535.")
            return
        self._connect_output(host, port, self.manual_connect_button)

    def _toggle_discovered_output(self, address: str, button: QPushButton) -> None:
        if self.output:
            if self._connection_button is button and self._connected_device_ip == address:
                self.disconnect_output()
            return
        self._connect_output(address, DeviceDiscovery.WEBSOCKET_PORT, button)

    def _connect_output(self, host: str, port: int, source_button: QPushButton) -> None:
        if self.output is not None:
            return
        host = host.strip()
        if not host:
            return
        self.config.websocket_host = host
        self.config.websocket_port = int(port)
        self.websocket_host.setText(host)
        self.websocket_port.setText(str(port))
        self.config.live_state = self.engine.export_state()
        self.config.save()
        output = MrCodetasticWebSocketOutput(self.config.websocket_url)
        self.output = output
        self._connection_button = source_button
        self._connected_device_ip = host if source_button in self.device_connect_buttons.values() else None
        output.start()
        self.engine.outputs.add("primary", output)
        self.update_controls()
        self.status_message.emit(f"Connecting to {self.config.websocket_url}")

    def disconnect_output(self) -> None:
        removed = self.engine.outputs.remove("primary")
        output = removed or self.output
        if output is not None:
            output.stop()
        self.output = None
        self._connection_button = None
        self._connected_device_ip = None
        self.update_controls()
        self.status_message.emit("Output disconnected")

    def update_controls(self) -> None:
        connected = bool(self.output and self.output.connected)
        connecting = self.output is not None and not connected
        for _address, button in self.device_connect_buttons.items():
            is_selected = self._connection_button is button
            label = (
                "Disconnect"
                if connected and is_selected
                else "Connecting…" if connecting and is_selected else "Connect"
            )
            button.setText(label)
            button.setEnabled(self.output is None or is_selected)
        self.manual_toggle.setEnabled(self.output is None)
        self.websocket_host.setEnabled(self.output is None)
        self.websocket_port.setEnabled(self.output is None)
        manual_selected = self._connection_button is self.manual_connect_button
        self.manual_connect_button.setText(
            "Disconnect"
            if connected and manual_selected
            else "Connecting…" if connecting and manual_selected else "Connect"
        )
        self.manual_connect_button.setEnabled(self.output is None or manual_selected)
