from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    kind: Literal["trigger", "toggle", "continuous"]


class ActionRegistry:
    """Thread-safe registry mapping action IDs to engine/UI callbacks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._actions: dict[str, Action] = {}
        self._handlers: dict[str, Callable[[float | None], None]] = {}

    def register(self, action: Action, handler: Callable[[float | None], None]) -> None:
        with self._lock:
            self._actions[action.id] = action
            self._handlers[action.id] = handler

    def invoke(self, action_id: str, value: float | None = None) -> bool:
        with self._lock:
            handler = self._handlers.get(action_id)
        if handler is None:
            return False
        handler(value)
        return True

    def actions(self) -> list[Action]:
        with self._lock:
            return list(self._actions.values())


DEFAULT_SHORTCUTS: dict[str, str] = {
    "Space": "transition.auto",
    "B": "master.blackout.toggle",
    "F": "master.freeze.toggle",
    "T": "tap_tempo",
    "Left": "playlist.prev",
    "Right": "playlist.next",
    **{str(i): f"preset.load.{i}" for i in range(1, 10)},
}


def register_engine_actions(
    registry: ActionRegistry,
    engine,
    config,
    load_preset_cb: Callable[[str], None] | None = None,
    toggle_playlist_cb: Callable[[], None] | None = None,
) -> None:
    registry.register(
        Action("fader.set", "Crossfader", "continuous"),
        lambda v: engine.set_fader(0.5 if v is None else v),
    )
    registry.register(
        Action("transition.auto", "Auto Transition", "trigger"),
        lambda _v: engine.start_transition(1.0 if engine.fader < 0.5 else 0.0, 2.0),
    )
    registry.register(
        Action("transition.cut", "Cut Transition", "trigger"),
        lambda _v: engine.set_fader(1.0 if engine.fader < 0.5 else 0.0),
    )
    registry.register(
        Action("master.blackout.toggle", "Blackout Toggle", "toggle"),
        lambda v: engine.set_master(blackout=(not engine.blackout) if v is None else bool(v >= 0.5)),
    )
    registry.register(
        Action("master.freeze.toggle", "Freeze Toggle", "toggle"),
        lambda v: engine.set_master(freeze=(not engine.freeze) if v is None else bool(v >= 0.5)),
    )
    registry.register(
        Action("master.brightness", "Master Brightness", "continuous"),
        lambda v: engine.set_master(brightness=1.0 if v is None else v),
    )
    registry.register(
        Action("master.speed", "Master Speed", "continuous"),
        lambda v: engine.set_master(speed=1.0 if v is None else v * 4.0),
    )
    registry.register(Action("tap_tempo", "Tap Tempo", "trigger"), lambda _v: engine.tap_tempo())
    registry.register(Action("playlist.next", "Playlist Next", "trigger"), lambda _v: engine.next_playlist_entry())
    registry.register(Action("playlist.prev", "Playlist Previous", "trigger"), lambda _v: engine.prev_playlist_entry())
    if toggle_playlist_cb is not None:
        registry.register(Action("playlist.toggle", "Playlist Play/Stop", "toggle"), lambda _v: toggle_playlist_cb())

    def _load_idx(index_zero: int) -> None:
        if 0 <= index_zero < len(config.presets):
            name = config.presets[index_zero]["name"]
            if load_preset_cb is not None:
                load_preset_cb(name)

    for idx in range(1, 10):
        registry.register(
            Action(f"preset.load.{idx}", f"Load Preset {idx}", "trigger"),
            lambda _v, i=idx - 1: _load_idx(i),
        )

    for side, tag in (("left", "A"), ("right", "B")):
        for layer_idx in range(5):
            def _toggle(_v, s=side, idx=layer_idx) -> None:
                snap = engine.scene_snapshot(s)
                cur = bool(snap["layers"][idx].get("enabled", True))
                engine.set_layer_enabled(s, idx, not cur if _v is None else bool(_v >= 0.5))

            registry.register(
                Action(f"layer.toggle.{side}.{layer_idx + 1}", f"Toggle Source {tag} Layer {layer_idx + 1}", "toggle"),
                _toggle,
            )
