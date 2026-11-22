from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from glediator.core.migrations import LATEST_CONFIG_VERSION, migrate

CONFIG_PATH = Path.home() / ".glediator" / "settings.json"


def _default_master() -> dict:
    return {"brightness": 1.0, "gamma": 1.4}


def _default_controls() -> dict:
    return {"keyboard": {}, "osc": {"enabled": False, "port": 9000}}


def _default_ui() -> dict:
    return {"theme": "dark"}


@dataclass(init=False)
class EngineConfig:
    width: int = 64
    height: int = 32
    fps: int = 60
    master: dict = field(default_factory=_default_master)
    devices: list[dict] = field(default_factory=list)
    presets: list[dict] = field(default_factory=list)
    live_state: dict = field(default_factory=dict)
    playlists: list[dict] = field(default_factory=list)
    controls: dict = field(default_factory=_default_controls)
    palettes: dict = field(default_factory=dict)
    ui: dict = field(default_factory=_default_ui)
    config_version: int = LATEST_CONFIG_VERSION
    load_warning: str = field(default="", init=False, repr=False, compare=False)

    def __init__(
        self,
        width: int = 64,
        height: int = 32,
        fps: int = 60,
        master: dict | None = None,
        devices: list[dict] | None = None,
        presets: list[dict] | None = None,
        live_state: dict | None = None,
        playlists: list[dict] | None = None,
        controls: dict | None = None,
        palettes: dict | None = None,
        ui: dict | None = None,
        config_version: int = LATEST_CONFIG_VERSION,
        websocket_host: str | None = None,
        websocket_port: int | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.master = dict(master) if master is not None else _default_master()
        self.devices = list(devices) if devices is not None else []
        self.presets = list(presets) if presets is not None else []
        self.live_state = dict(live_state) if live_state is not None else {}
        self.playlists = list(playlists) if playlists is not None else []
        self.controls = dict(controls) if controls is not None else _default_controls()
        self.palettes = dict(palettes) if palettes is not None else {}
        self.ui = dict(ui) if ui is not None else _default_ui()
        self.config_version = config_version
        self.load_warning = ""
        if websocket_host is not None or websocket_port is not None:
            host = (str(websocket_host).strip() if websocket_host else "") or "127.0.0.1"
            port = int(websocket_port) if websocket_port is not None else 12345
            if not self.devices:
                self.devices = [
                    {
                        "id": "dev-1",
                        "name": "",
                        "host": host,
                        "port": port,
                        "auto_connect": False,
                    }
                ]
            else:
                if websocket_host is not None:
                    self.devices[0]["host"] = host
                if websocket_port is not None:
                    self.devices[0]["port"] = port
        self.validate()

    @classmethod
    def _from_dict(cls, values: dict) -> EngineConfig:
        migrated = migrate(values)
        allowed = {f.name for f in fields(cls) if f.name != "load_warning"}
        filtered = {key: migrated[key] for key in allowed if key in migrated}
        config = cls(**filtered)
        config.validate()
        return config

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> EngineConfig:
        backup_path = path.with_name(f"{path.name}.bak")
        primary_error: Exception | None = None
        if path.exists():
            try:
                values = json.loads(path.read_text(encoding="utf-8"))
                return cls._from_dict(values)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                primary_error = exc
        if backup_path.exists():
            try:
                values = json.loads(backup_path.read_text(encoding="utf-8"))
                config = cls._from_dict(values)
                if primary_error is not None:
                    config.load_warning = f"Recovered settings from backup ({backup_path.name})."
                return config
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        config = cls()
        if primary_error is not None:
            config.load_warning = f"Settings file was unreadable ({primary_error}); using defaults."
        return config

    def save(self, path: Path = CONFIG_PATH) -> None:
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload.pop("load_warning", None)
        tmp_path = path.with_name(f"{path.name}.tmp")
        backup_path = path.with_name(f"{path.name}.bak")
        data = json.dumps(payload, indent=2)
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copy2(path, backup_path)
        os.replace(tmp_path, path)

    def validate(self) -> None:
        self.width = max(8, min(512, int(self.width)))
        self.height = max(8, min(512, int(self.height)))
        self.fps = max(1, min(120, int(self.fps)))
        if not isinstance(self.master, dict):
            self.master = _default_master()
        self.master = {
            "brightness": max(0.0, min(1.0, float(self.master.get("brightness", 1.0)))),
            "gamma": max(0.1, min(4.0, float(self.master.get("gamma", 1.4)))),
        }
        cleaned_devices: list[dict] = []
        if isinstance(self.devices, list):
            for idx, dev in enumerate(self.devices):
                if not isinstance(dev, dict):
                    continue
                host = str(dev.get("host", "")).strip()
                if not host:
                    continue
                try:
                    port = max(1, min(65535, int(dev.get("port", 12345))))
                except (TypeError, ValueError):
                    port = 12345
                cleaned_devices.append({
                    "id": str(dev.get("id") or f"dev-{idx + 1}"),
                    "name": str(dev.get("name", "")),
                    "host": host,
                    "port": port,
                    "auto_connect": bool(dev.get("auto_connect", False)),
                })
        self.devices = cleaned_devices
        self.presets = [preset for preset in self.presets if isinstance(preset, dict) and preset.get("name")]
        if not isinstance(self.playlists, list):
            self.playlists = []
        if not isinstance(self.controls, dict):
            self.controls = _default_controls()
        if not isinstance(self.palettes, dict):
            self.palettes = {}
        if not isinstance(self.ui, dict):
            self.ui = _default_ui()
        self.config_version = max(LATEST_CONFIG_VERSION, int(self.config_version))

    @property
    def websocket_host(self) -> str:
        if self.devices:
            return str(self.devices[0].get("host", "127.0.0.1"))
        return "127.0.0.1"

    @websocket_host.setter
    def websocket_host(self, value: str) -> None:
        host = str(value).strip() or "127.0.0.1"
        if not self.devices:
            self.devices = [{"id": "dev-1", "name": "", "host": host, "port": 12345, "auto_connect": False}]
        else:
            self.devices[0]["host"] = host

    @property
    def websocket_port(self) -> int:
        if self.devices:
            return int(self.devices[0].get("port", 12345))
        return 12345

    @websocket_port.setter
    def websocket_port(self, value: int) -> None:
        port = max(1, min(65535, int(value)))
        if not self.devices:
            self.devices = [{"id": "dev-1", "name": "", "host": "127.0.0.1", "port": port, "auto_connect": False}]
        else:
            self.devices[0]["port"] = port

    @property
    def websocket_url(self) -> str:
        host = self.websocket_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"ws://{host}:{self.websocket_port}"
