from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.network.discovery import DeviceDiscovery
from glediator.output.websocket_output import OutputStatus, WebSocketOutput

STATE_COLORS = {
    "stopped": "#647486",
    "stale": "#647486",
    "connecting": "#f59e0b",
    "online": "#22c55e",
    "mismatch": "#ef4444",
    "error": "#ef4444",
}


class NetworkPanel(QGroupBox):
    status_message = Signal(str)
    beacon_status_changed = Signal(str)
    matrix_size_requested = Signal(int, int)

    def __init__(self, engine: RenderEngine, config: EngineConfig, parent: QWidget | None = None) -> None:
        super().__init__("NETWORK OUTPUT", parent)
        self.engine = engine
        self.config = config
        self._outputs: dict[str, WebSocketOutput] = {}
        self._device_rows: dict[str, dict] = {}
        self._ignored_mismatches: set[tuple[str, int, int]] = set()
        self._mismatch_size: tuple[int, int] | None = None
        self._mismatch_output_id: str | None = None

        layout = QVBoxLayout(self)
        self.device_hint = QLabel("Searching for CODETASTIC devices…")
        self.device_hint.setWordWrap(True)
        layout.addWidget(self.device_hint)

        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(76)
        self.device_list.setMaximumHeight(180)
        self.device_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.device_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.device_list)

        self.stats_label = QLabel("No active output")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("color:#8ea0b4; font-size:8.5pt;")
        layout.addWidget(self.stats_label)

        self.mismatch_banner = QFrame()
        self.mismatch_banner.setStyleSheet(
            "QFrame { background:#2b161b; border:1px solid #ef4444; border-radius:6px; padding:6px; }"
        )
        mismatch_layout = QHBoxLayout(self.mismatch_banner)
        mismatch_layout.setContentsMargins(6, 4, 6, 4)
        self.mismatch_label = QLabel("")
        self.mismatch_label.setWordWrap(True)
        self.mismatch_apply_btn = QPushButton("Use device size")
        self.mismatch_apply_btn.clicked.connect(self._apply_mismatch_size)
        self.mismatch_ignore_btn = QPushButton("Ignore")
        self.mismatch_ignore_btn.clicked.connect(self._ignore_mismatch)
        mismatch_layout.addWidget(self.mismatch_label, 1)
        mismatch_layout.addWidget(self.mismatch_apply_btn)
        mismatch_layout.addWidget(self.mismatch_ignore_btn)
        self.mismatch_banner.setVisible(False)
        layout.addWidget(self.mismatch_banner)

        proc_row = QHBoxLayout()
        proc_row.addWidget(QLabel("Out brightness"))
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setValue(round(self.config.master.get("brightness", 1.0) * 100))
        self.brightness_slider.valueChanged.connect(self._on_master_processing_changed)
        proc_row.addWidget(self.brightness_slider, 1)
        proc_row.addWidget(QLabel("Gamma"))
        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.5, 3.0)
        self.gamma_spin.setSingleStep(0.1)
        self.gamma_spin.setDecimals(2)
        self.gamma_spin.setValue(float(self.config.master.get("gamma", 1.0)))
        self.gamma_spin.valueChanged.connect(self._on_master_processing_changed)
        proc_row.addWidget(self.gamma_spin)
        layout.addLayout(proc_row)

        self.device_brightness_row = QWidget()
        dev_b_layout = QHBoxLayout(self.device_brightness_row)
        dev_b_layout.setContentsMargins(0, 0, 0, 0)
        dev_b_layout.addWidget(QLabel("Panel brightness"))
        self.device_brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.device_brightness_slider.setRange(0, 255)
        self.device_brightness_slider.setValue(255)
        self.device_brightness_slider.valueChanged.connect(self._on_device_brightness_changed)
        dev_b_layout.addWidget(self.device_brightness_slider, 1)
        self.device_brightness_row.setVisible(False)
        layout.addWidget(self.device_brightness_row)

        self.manual_toggle = QCheckBox("Connect manually")
        self.manual_toggle.toggled.connect(self._show_manual_connection)
        layout.addWidget(self.manual_toggle)

        self.manual_form = QWidget()
        manual_row = QHBoxLayout(self.manual_form)
        manual_row.setContentsMargins(0, 0, 0, 0)
        initial_host = self.config.devices[0]["host"] if self.config.devices else ""
        self.websocket_host = QLineEdit(initial_host)
        self.websocket_host.setPlaceholderText("IP address or host (e.g. 192.168.1.50)")
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

        self._restore_saved_devices()

    @property
    def output(self) -> WebSocketOutput | None:
        if not self._outputs:
            return None
        return next(iter(self._outputs.values()))

    def _device_key(self, host: str, port: int) -> str:
        return f"{host}:{port}"

    @staticmethod
    def _is_untouched_local(dev: dict) -> bool:
        host = str(dev.get("host", "")).strip().lower()
        try:
            port = int(dev.get("port", 12345))
        except (TypeError, ValueError):
            port = 12345
        return (
            host in ("", "127.0.0.1", "localhost")
            and port == 12345
            and not dev.get("auto_connect", False)
            and not dev.get("name", "")
        )

    def _restore_saved_devices(self) -> None:
        for dev in self.config.devices:
            if self._is_untouched_local(dev):
                continue
            host = dev["host"]
            port = int(dev.get("port", 12345))
            info = {"address": host, "name": dev.get("name", ""), "w": 0, "h": 0, "port": port, "v": 1}
            self._upsert_device_row(info, saved=True, auto_connect=bool(dev.get("auto_connect", False)))
            if dev.get("auto_connect"):
                self._connect_output(host, port)

    def sync_endpoint_to_config(self) -> None:
        saved_by_key: dict[str, dict] = {
            self._device_key(d["host"], int(d.get("port", 12345))): dict(d)
            for d in self.config.devices
            if not self._is_untouched_local(d)
        }
        for key, row_data in self._device_rows.items():
            auto_chk: QCheckBox = row_data["auto_check"]
            host = row_data["host"]
            port = row_data["port"]
            if auto_chk.isChecked() or key in self._outputs or key in saved_by_key:
                saved_by_key[key] = {
                    "id": key,
                    "name": row_data["name"],
                    "host": host,
                    "port": port,
                    "auto_connect": auto_chk.isChecked(),
                }
        self.config.devices = list(saved_by_key.values())
        self.config.master = {
            "brightness": self.brightness_slider.value() / 100.0,
            "gamma": float(self.gamma_spin.value()),
        }

    def handle_discovery_events(self, events: list[tuple[str, object]]) -> None:
        for event, payload in events:
            if event == "device":
                if isinstance(payload, str):
                    info = {
                        "address": payload,
                        "name": "",
                        "w": 0,
                        "h": 0,
                        "port": DeviceDiscovery.WEBSOCKET_PORT,
                        "v": 1,
                    }
                else:
                    info = dict(payload)  # type: ignore[arg-type]
                self.add_discovered_device(info)
            elif event == "device_stale" and isinstance(payload, str):
                self._mark_stale(payload, True)
            elif event == "device_lost" and isinstance(payload, str):
                self._remove_discovered_device(payload)
            elif event == "error":
                self._discovery_error(str(payload))
            elif event == "ready":
                self._discovery_ready()

    def add_discovered_device(self, info_or_address: str | dict) -> None:
        if isinstance(info_or_address, str):
            info = {
                "address": info_or_address,
                "name": "",
                "w": 0,
                "h": 0,
                "port": DeviceDiscovery.WEBSOCKET_PORT,
                "v": 1,
            }
        else:
            info = info_or_address
        self._upsert_device_row(info, saved=False)

    def _upsert_device_row(self, info: dict, *, saved: bool = False, auto_connect: bool | None = None) -> None:
        host = str(info["address"])
        port = int(info.get("port", DeviceDiscovery.WEBSOCKET_PORT))
        key = self._device_key(host, port)
        name = str(info.get("name", ""))
        w, h = int(info.get("w", 0)), int(info.get("h", 0))
        proto_v = int(info.get("v", 1))

        if key in self._device_rows:
            row_data = self._device_rows[key]
            row_data["stale"] = False
            if name:
                row_data["name"] = name
            if w > 0 and h > 0:
                row_data["size"] = (w, h)
            row_data["proto_v"] = max(row_data["proto_v"], proto_v)
            self._refresh_row_label(key)
            return

        self.device_hint.setVisible(False)
        item = QListWidgetItem(self.device_list)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(5, 2, 5, 2)

        dot = QLabel("●")
        dot.setFixedWidth(12)
        label = QLabel()
        label.setMinimumWidth(0)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        auto_chk = QCheckBox("Auto")
        auto_chk.setToolTip("Automatically reconnect on startup")
        if auto_connect is not None:
            auto_chk.setChecked(auto_connect)

        connect_button = QPushButton("Connect")
        connect_button.setMinimumWidth(82)
        connect_button.setMinimumHeight(30)
        connect_button.clicked.connect(lambda _c=False, k=key: self._toggle_device_output(k))

        row_layout.addWidget(dot)
        row_layout.addWidget(label, 1)
        row_layout.addWidget(auto_chk)
        row_layout.addWidget(connect_button)
        item.setSizeHint(QSize(0, 48))
        self.device_list.setItemWidget(item, row)

        self._device_rows[key] = {
            "item": item,
            "host": host,
            "port": port,
            "name": name,
            "size": (w, h) if (w > 0 and h > 0) else None,
            "proto_v": proto_v,
            "stale": False,
            "saved": saved,
            "dot": dot,
            "label": label,
            "auto_check": auto_chk,
            "button": connect_button,
        }
        self._refresh_row_label(key)
        self.update_controls()

    def _refresh_row_label(self, key: str) -> None:
        data = self._device_rows[key]
        title = data["name"] or data["host"]
        meta = [f"{data['host']}:{data['port']}"]
        if data["size"]:
            meta.append(f"{data['size'][0]}×{data['size'][1]}")
        meta.append(f"v{data['proto_v']}")
        if data["stale"]:
            meta.append("stale")
        sub = " · ".join(meta)
        data["label"].setText(
            f"<b>{title}</b><br><span style='color:#8ea0b4; font-size:8.5pt;'>{sub}</span>"
        )

    def _mark_stale(self, address: str, stale: bool) -> None:
        for key, data in self._device_rows.items():
            if data["host"] == address:
                data["stale"] = stale
                self._refresh_row_label(key)
        self.update_controls()

    def _remove_discovered_device(self, address: str) -> None:
        to_remove = [
            key
            for key, data in self._device_rows.items()
            if data["host"] == address and key not in self._outputs and not data["saved"]
        ]
        for key in to_remove:
            row_data = self._device_rows.pop(key)
            row = self.device_list.row(row_data["item"])
            if row >= 0:
                self.device_list.takeItem(row)
        if not self._device_rows:
            self.device_hint.setVisible(True)

    def _discovery_ready(self) -> None:
        if not self._device_rows:
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
        key = self._device_key(host, port)
        if key in self._outputs:
            self._disconnect_key(key)
            return
        self._upsert_device_row({"address": host, "name": "", "w": 0, "h": 0, "port": port, "v": 1}, saved=True)
        self._connect_output(host, port)

    def _toggle_device_output(self, key: str) -> None:
        if key in self._outputs:
            self._disconnect_key(key)
            return
        data = self._device_rows.get(key)
        if data:
            self._connect_output(data["host"], data["port"])

    def _connect_output(self, host: str, port: int) -> None:
        host = host.strip()
        if not host:
            return
        key = self._device_key(host, port)
        if key in self._outputs:
            return
        output = WebSocketOutput(host, int(port), device_id=key)
        self._outputs[key] = output
        output.start()
        self.engine.outputs.add(key, output)
        self.sync_endpoint_to_config()
        self.config.live_state = self.engine.export_state()
        self.config.save()
        self.update_controls()
        self.status_message.emit(f"Connecting to {output.url}")

    def _disconnect_key(self, key: str) -> None:
        removed = self.engine.outputs.remove(key)
        output = removed or self._outputs.pop(key, None)
        self._outputs.pop(key, None)
        if output is not None:
            output.stop()
        if self._mismatch_output_id == key:
            self.mismatch_banner.setVisible(False)
            self._mismatch_size = None
            self._mismatch_output_id = None
        self.update_controls()
        self.status_message.emit("Output disconnected")

    def disconnect_output(self) -> None:
        for key in list(self._outputs):
            self._disconnect_key(key)

    def _on_master_processing_changed(self) -> None:
        brightness = self.brightness_slider.value() / 100.0
        gamma = float(self.gamma_spin.value())
        self.engine.set_master(brightness=brightness, gamma=gamma)

    def _on_device_brightness_changed(self, value: int) -> None:
        for output in self._outputs.values():
            output.set_brightness(value)

    def _apply_mismatch_size(self) -> None:
        if self._mismatch_size is not None:
            w, h = self._mismatch_size
            self.mismatch_banner.setVisible(False)
            self.matrix_size_requested.emit(w, h)

    def _ignore_mismatch(self) -> None:
        if self._mismatch_output_id and self._mismatch_size:
            self._ignored_mismatches.add((self._mismatch_output_id, *self._mismatch_size))
        self.mismatch_banner.setVisible(False)

    def update_controls(self, statuses: dict[str, OutputStatus] | None = None) -> None:
        if statuses is None:
            statuses = {key: out.status() for key, out in self._outputs.items()}

        has_brightness_cap = False
        mismatch_found: tuple[str, int, int, str] | None = None
        stat_parts: list[str] = []

        for key, row_data in self._device_rows.items():
            out_status = statuses.get(key)
            button: QPushButton = row_data["button"]
            dot: QLabel = row_data["dot"]
            if out_status is None:
                state = "stale" if row_data["stale"] else "stopped"
                dot.setStyleSheet(f"color:{STATE_COLORS[state]};")
                button.setText("Connect")
                continue

            state = out_status.state
            dot.setStyleSheet(f"color:{STATE_COLORS.get(state, '#647486')};")
            button.setText("Disconnect" if state != "stopped" else "Connect")

            if out_status.protocol == "v2" and out_status.device:
                dw = int(out_status.device.get("w", 0))
                dh = int(out_status.device.get("h", 0))
                name = str(out_status.device.get("name", ""))
                changed = False
                if name and row_data["name"] != name:
                    row_data["name"] = name
                    changed = True
                if dw > 0 and dh > 0 and row_data["size"] != (dw, dh):
                    row_data["size"] = (dw, dh)
                    changed = True
                if row_data["proto_v"] != 2:
                    row_data["proto_v"] = 2
                    changed = True
                if changed:
                    self._refresh_row_label(key)
                if "brightness" in out_status.device.get("caps", []):
                    has_brightness_cap = True
                if state == "mismatch" and dw > 0 and dh > 0:
                    if (key, dw, dh) not in self._ignored_mismatches:
                        mismatch_found = (key, dw, dh, out_status.last_error)

            kbps = out_status.bytes_per_sec / 1024.0
            show_lat = out_status.protocol == "v2" and out_status.latency_ms > 0
            lat = f" · {out_status.latency_ms:.0f} ms" if show_lat else ""
            stat_parts.append(
                f"{key}: {out_status.fps:.0f} FPS · {kbps:.1f} KB/s · skip {out_status.frames_skipped}{lat}"
            )

        self.device_brightness_row.setVisible(has_brightness_cap)
        if mismatch_found:
            m_key, dw, dh, msg = mismatch_found
            self._mismatch_output_id = m_key
            self._mismatch_size = (dw, dh)
            self.mismatch_label.setText(msg or f"Device reports {dw}×{dh}.")
            self.mismatch_apply_btn.setText(f"Use device size ({dw}×{dh})")
            self.mismatch_banner.setVisible(True)
        elif not any(st.state == "mismatch" for st in statuses.values()):
            self.mismatch_banner.setVisible(False)
            self._mismatch_size = None
            self._mismatch_output_id = None

        self.stats_label.setText(" | ".join(stat_parts) if stat_parts else "No active output")

        manual_key = self._device_key(
            self.websocket_host.text().strip() or self.config.websocket_host,
            int(self.websocket_port.text() or self.config.websocket_port)
            if self.websocket_port.text().isdigit()
            else self.config.websocket_port,
        )
        self.manual_connect_button.setText("Disconnect" if manual_key in self._outputs else "Connect")
