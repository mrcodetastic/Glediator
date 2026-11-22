from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from glediator.core.migrations import LATEST_CONFIG_VERSION, migrate

CONFIG_PATH = Path.home() / ".glediator" / "settings.json"


@dataclass
class EngineConfig:
    width: int = 64
    height: int = 32
    fps: int = 60
    websocket_host: str = "127.0.0.1"
    websocket_port: int = 12345
    presets: list[dict] = field(default_factory=list)
    live_state: dict = field(default_factory=dict)
    config_version: int = LATEST_CONFIG_VERSION
    load_warning: str = field(default="", init=False, repr=False, compare=False)

    @classmethod
    def _from_dict(cls, values: dict) -> EngineConfig:
        migrated = migrate(values)
        allowed = {f.name for f in fields(cls) if f.init}
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
        self.websocket_host = str(self.websocket_host).strip() or "127.0.0.1"
        self.websocket_port = max(1, min(65535, int(self.websocket_port)))
        self.presets = [preset for preset in self.presets if isinstance(preset, dict) and preset.get("name")]
        self.config_version = max(2, int(self.config_version))

    @property
    def websocket_url(self) -> str:
        host = self.websocket_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"ws://{host}:{self.websocket_port}"
