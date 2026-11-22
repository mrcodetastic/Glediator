from __future__ import annotations

import json
import queue
import socket
import threading
import time
from typing import Any


class DeviceDiscovery:
    """Listen for MrCodeTastic UDP discovery beacons (v1 & v2) without blocking the UI."""

    PORT = 20586
    WEBSOCKET_PORT = 12345
    BEACON = b"CODETASTIC"
    STALE_SECONDS = 10.0
    LOST_SECONDS = 60.0

    def __init__(self, port: int = PORT, clock=time.monotonic) -> None:
        self.port = int(port)
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._seen: dict[str, dict[str, Any]] = {}

    @classmethod
    def is_beacon(cls, payload: bytes) -> bool:
        return cls.parse_beacon(payload) is not None

    @classmethod
    def parse_beacon(cls, payload: bytes) -> dict[str, Any] | None:
        if not isinstance(payload, (bytes, bytearray)):
            return None
        text = bytes(payload).strip(b"\x00 \t\r\n")
        if not text:
            return None
        parts = text.split(None, 1)
        if parts[0].upper() != cls.BEACON:
            return None
        info: dict[str, Any] = {
            "v": 1,
            "name": "",
            "w": 0,
            "h": 0,
            "port": cls.WEBSOCKET_PORT,
        }
        if len(parts) == 2:
            try:
                parsed = json.loads(parts[1].decode("utf-8"))
                if isinstance(parsed, dict) and int(parsed.get("v", 1)) >= 2:
                    info["v"] = int(parsed.get("v", 2))
                    info["name"] = str(parsed.get("name", ""))
                    info["w"] = int(parsed.get("w", 0))
                    info["h"] = int(parsed.get("h", 0))
                    port = int(parsed.get("port", cls.WEBSOCKET_PORT))
                    info["port"] = port if 1 <= port <= 65535 else cls.WEBSOCKET_PORT
            except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
                pass
        return info

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, name="GlediatorDeviceDiscovery", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)
        self._thread = None
        self._socket = None

    def record_beacon(self, address: str, info: dict[str, Any]) -> None:
        now = self._clock()
        entry = self._seen.get(address)
        payload = {"address": address, **info}
        if entry is None:
            self._seen[address] = {"last_seen": now, "stale": False, "info": payload}
            self._events.put(("device", payload))
            return
        was_stale = entry["stale"]
        prev_info = entry["info"]
        entry["last_seen"] = now
        entry["stale"] = False
        entry["info"] = payload
        if was_stale or payload != prev_info:
            self._events.put(("device", payload))

    def check_expiries(self) -> None:
        now = self._clock()
        lost: list[str] = []
        for address, entry in self._seen.items():
            age = now - entry["last_seen"]
            if age >= self.LOST_SECONDS:
                lost.append(address)
            elif age >= self.STALE_SECONDS and not entry["stale"]:
                entry["stale"] = True
                self._events.put(("device_stale", address))
        for address in lost:
            self._seen.pop(address, None)
            self._events.put(("device_lost", address))

    def poll_events(self) -> list[tuple[str, Any]]:
        self.check_expiries()
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket = sock
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port))
            sock.settimeout(0.5)
            self._events.put(("ready", ""))
            while not self._stop.is_set():
                try:
                    payload, (address, _sender_port) = sock.recvfrom(2048)
                except TimeoutError:
                    continue
                except OSError:
                    if not self._stop.is_set():
                        raise
                    break
                info = self.parse_beacon(payload)
                if address and info is not None:
                    self.record_beacon(address, info)
        except Exception as exc:
            if not self._stop.is_set():
                self._events.put(("error", f"UDP device discovery on port {self.port} failed: {exc}"))
        finally:
            try:
                sock.close()
            except OSError:
                pass
