from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from glediator.control.actions import ActionRegistry


def parse_midi_event(msg: Any) -> tuple[str, int, int, float] | None:
    """Normalize a mido Message into (kind, channel, number, normalized_value)."""
    mtype = getattr(msg, "type", "")
    channel = int(getattr(msg, "channel", 0))
    if mtype == "control_change":
        number = int(getattr(msg, "control", 0))
        val = max(0.0, min(1.0, float(getattr(msg, "value", 0)) / 127.0))
        return "cc", channel, number, val
    if mtype == "note_on":
        vel = int(getattr(msg, "velocity", 0))
        if vel <= 0:
            return None
        number = int(getattr(msg, "note", 0))
        return "note", channel, number, min(1.0, vel / 127.0)
    return None


class MidiController:
    """Optional MIDI input listener with learn mode."""

    def __init__(self, registry: ActionRegistry) -> None:
        self.registry = registry
        self.mappings: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._learn_callback: Callable[[dict], None] | None = None
        self.last_error = ""
        self.port_name = ""

    @staticmethod
    def available_ports() -> tuple[list[str], str]:
        try:
            import mido

            return list(mido.get_input_names()), ""
        except ImportError:
            return [], "Install glediator3[midi] to enable MIDI control."
        except Exception as exc:
            return [], f"MIDI unavailable: {exc}"

    def set_mappings(self, mappings: list[dict]) -> None:
        with self._lock:
            self.mappings = [dict(m) for m in mappings if isinstance(m, dict)]

    def start_learn(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._learn_callback = callback

    def cancel_learn(self) -> None:
        with self._lock:
            self._learn_callback = None

    def dispatch_message(self, msg: Any) -> bool:
        parsed = parse_midi_event(msg)
        if parsed is None:
            return False
        kind, channel, number, value = parsed
        with self._lock:
            learn_cb = self._learn_callback
            if learn_cb is not None:
                self._learn_callback = None
        if learn_cb is not None:
            learn_cb({"type": kind, "channel": channel, "number": number})
            return True

        with self._lock:
            matches = [
                m
                for m in self.mappings
                if m.get("type") == kind
                and int(m.get("channel", 0)) == channel
                and int(m.get("number", -1)) == number
            ]
        dispatched = False
        for m in matches:
            action_id = str(m.get("action", ""))
            mode = str(m.get("mode", "continuous"))
            arg = None if mode in ("trigger", "toggle") else value
            if self.registry.invoke(action_id, arg):
                dispatched = True
        return dispatched

    def start(self, port_name: str) -> None:
        self.stop()
        self.port_name = port_name
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(port_name,), name="GlediatorMIDI", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _run(self, port_name: str) -> None:
        try:
            import mido

            with mido.open_input(port_name) as port:
                self.last_error = ""
                while not self._stop.is_set():
                    for msg in port.iter_pending():
                        self.dispatch_message(msg)
                    self._stop.wait(timeout=0.01)
        except ImportError:
            self.last_error = "Install glediator3[midi] to enable MIDI control."
        except Exception as exc:
            self.last_error = f"MIDI input error: {exc}"
