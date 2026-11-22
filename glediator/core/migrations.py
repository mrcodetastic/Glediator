from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from urllib.parse import urlsplit


def _migrate_v1_to_v2(data: dict) -> dict:
    updated = deepcopy(data)
    updated.pop("mapping", None)
    presets = updated.get("presets")
    if isinstance(presets, list):
        for preset in presets:
            if isinstance(preset, dict):
                preset.pop("mapping", None)
    if "websocket_url" in updated and "websocket_host" not in updated:
        parsed = urlsplit(str(updated["websocket_url"]))
        if parsed.hostname:
            updated["websocket_host"] = parsed.hostname
        if parsed.port:
            updated["websocket_port"] = parsed.port
    updated.pop("websocket_url", None)
    updated["config_version"] = 2
    return updated


def _migrate_v2_to_v3(data: dict) -> dict:
    updated = deepcopy(data)
    host = str(updated.pop("websocket_host", "127.0.0.1")).strip() or "127.0.0.1"
    try:
        port = int(updated.pop("websocket_port", 12345))
    except (TypeError, ValueError):
        port = 12345
    if "devices" not in updated or not isinstance(updated["devices"], list):
        updated["devices"] = [
            {
                "id": "dev-1",
                "name": "",
                "host": host,
                "port": max(1, min(65535, port)),
                "auto_connect": False,
            }
        ]
    updated.setdefault("master", {"brightness": 1.0, "gamma": 1.0})
    updated.setdefault("playlists", [])
    updated.setdefault("controls", {"keyboard": {}, "midi": [], "osc": {"enabled": False, "port": 9000}})
    updated.setdefault("palettes", {})
    updated.setdefault("ui", {"theme": "dark"})
    updated["config_version"] = 3
    return updated


MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
}

LATEST_CONFIG_VERSION = max(MIGRATIONS) + 1


def migrate(data: dict) -> dict:
    """Upgrade a persisted settings dictionary to the latest schema version."""
    if not isinstance(data, dict):
        return {}
    current = deepcopy(data)
    try:
        version = int(current.get("config_version", 1))
    except (TypeError, ValueError):
        version = 1
    while version in MIGRATIONS:
        current = MIGRATIONS[version](current)
        version = int(current.get("config_version", version + 1))
    return current
