from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from glediator.core.config import EngineConfig
from glediator.core.migrations import LATEST_CONFIG_VERSION, migrate

AUTOSAVE_PATH = Path.home() / ".glediator" / "autosave.gled"
LOCK_PATH = Path.home() / ".glediator" / "session.lock"


def build_project_payload(config: EngineConfig, live_state: dict, *, include_devices: bool = False) -> dict:
    payload = {
        "project_format": "gled",
        "config_version": LATEST_CONFIG_VERSION,
        "width": config.width,
        "height": config.height,
        "fps": config.fps,
        "presets": deepcopy(config.presets),
        "playlists": deepcopy(config.playlists),
        "palettes": deepcopy(config.palettes),
        "live_state": deepcopy(live_state),
    }
    if include_devices:
        payload["master"] = deepcopy(config.master)
        payload["devices"] = deepcopy(config.devices)
    return payload


def save_project(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def load_project(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid project file")
    return migrate(raw)


def apply_project_to_config(project: dict, config: EngineConfig) -> dict:
    config.width = max(8, min(512, int(project.get("width", config.width))))
    config.height = max(8, min(512, int(project.get("height", config.height))))
    config.fps = max(1, min(120, int(project.get("fps", config.fps))))
    if isinstance(project.get("presets"), list):
        config.presets = deepcopy(project["presets"])
    if isinstance(project.get("playlists"), list):
        config.playlists = deepcopy(project["playlists"])
    if isinstance(project.get("palettes"), dict):
        config.palettes = deepcopy(project["palettes"])
    if isinstance(project.get("master"), dict):
        config.master = deepcopy(project["master"])
    if isinstance(project.get("devices"), list):
        config.devices = deepcopy(project["devices"])
    config.validate()
    return project.get("live_state", {}) if isinstance(project.get("live_state"), dict) else {}


def merge_imported_presets(existing: list[dict], imported: list[dict]) -> list[dict]:
    merged = [deepcopy(p) for p in existing if isinstance(p, dict) and p.get("name")]
    used_names = {p["name"].casefold() for p in merged}
    for entry in imported:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        base_name = str(entry["name"]).strip()
        name = base_name
        suffix = 2
        while name.casefold() in used_names:
            name = f"{base_name} ({suffix})"
            suffix += 1
        used_names.add(name.casefold())
        cloned = deepcopy(entry)
        cloned["name"] = name
        merged.append(cloned)
    return merged


def acquire_session_lock(lock_path: Path = LOCK_PATH) -> bool:
    """Return True if a previous session exited uncleanly (stale lock existed)."""
    dirty_previous = lock_path.exists()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    return dirty_previous


def release_session_lock(lock_path: Path = LOCK_PATH) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass
