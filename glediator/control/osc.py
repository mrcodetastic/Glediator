from __future__ import annotations

import threading

from glediator.control.actions import ActionRegistry


def osc_address_to_action_id(address: str) -> str | None:
    text = address.strip()
    if not text.startswith("/glediator/"):
        return None
    parts = [p for p in text[len("/glediator/") :].split("/") if p]
    if not parts:
        return None
    return ".".join(parts)


class OscController:
    """Optional OSC UDP server dispatching /glediator/<action> messages."""

    def __init__(self, registry: ActionRegistry) -> None:
        self.registry = registry
        self.port = 9000
        self._server = None
        self._thread: threading.Thread | None = None
        self.last_error = ""

    def dispatch(self, address: str, *args) -> bool:
        action_id = osc_address_to_action_id(address)
        if not action_id:
            return False
        value: float | None = None
        if args:
            try:
                value = float(args[0])
            except (TypeError, ValueError):
                value = None
        return self.registry.invoke(action_id, value)

    def start(self, host: str = "0.0.0.0", port: int = 9000) -> None:
        self.stop()
        self.port = int(port)
        try:
            from pythonosc.dispatcher import Dispatcher
            from pythonosc.osc_server import ThreadingOSCUDPServer

            dispatcher = Dispatcher()
            dispatcher.set_default_handler(self.dispatch)
            self._server = ThreadingOSCUDPServer((host, self.port), dispatcher)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="GlediatorOSC",
                daemon=True,
            )
            self._thread.start()
            self.last_error = ""
        except ImportError:
            self.last_error = "Install glediator3[osc] to enable OSC control."
        except Exception as exc:
            self.last_error = f"OSC server error: {exc}"

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
