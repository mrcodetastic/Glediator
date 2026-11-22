from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from glediator.output.delta import choose_encoding, encode_full


@dataclass
class OutputStatus:
    state: Literal["stopped", "connecting", "online", "mismatch", "error"] = "stopped"
    protocol: Literal["v1", "v2", "unknown"] = "unknown"
    device: dict = field(default_factory=dict)
    fps: float = 0.0
    frames_sent: int = 0
    frames_skipped: int = 0
    bytes_per_sec: float = 0.0
    latency_ms: float = 0.0
    last_error: str = ""


class WebSocketOutput:
    """WebSocket pixel output supporting v1 (open-loop full frames) and v2 (hello/ack/delta/rle)."""

    HELLO_TIMEOUT_S = 0.5
    MAX_IN_FLIGHT = 2
    ACK_WATCHDOG_S = 2.0

    def __init__(self, host: str, port: int = 12345, *, device_id: str = "") -> None:
        self.host = str(host).strip() or "127.0.0.1"
        self.port = int(port)
        self.device_id = device_id
        self._slot_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._wake_event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._pending_frame: np.ndarray | None = None
        self._control_queue: queue.SimpleQueue[str] = queue.SimpleQueue()

        self._state: Literal["stopped", "connecting", "online", "mismatch", "error"] = "stopped"
        self._protocol: Literal["v1", "v2", "unknown"] = "unknown"
        self._device: dict = {}
        self._frames_sent = 0
        self._frames_skipped = 0
        self._fps = 0.0
        self._bytes_per_sec = 0.0
        self._latency_ms = 0.0
        self._last_error = ""

        # Rolling 1s stats
        self._stat_window_start = time.monotonic()
        self._stat_frames = 0
        self._stat_bytes = 0

        # Connection-scoped tracking
        self._sent_count = 0
        self._acked_count = 0
        self._in_flight: dict[int, tuple[float, np.ndarray]] = {}
        self._last_sent_frame: np.ndarray | None = None
        self._last_acked_frame: np.ndarray | None = None
        self._pending_brightness: int | None = None

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"ws://{host}:{self.port}"

    @property
    def connected(self) -> bool:
        with self._state_lock:
            return self._state in ("online", "mismatch")

    @property
    def last_error(self) -> str:
        with self._state_lock:
            return self._last_error

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        with self._state_lock:
            self._state = "connecting"
            self._last_error = ""
        self._thread = threading.Thread(target=self._worker, name="GlediatorWebSocket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake_event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None
        with self._state_lock:
            self._state = "stopped"
            self._fps = 0.0
            self._bytes_per_sec = 0.0

    def submit(self, frame: np.ndarray) -> None:
        copy = np.ascontiguousarray(frame, dtype=np.uint8).copy()
        with self._slot_lock:
            if self._pending_frame is not None:
                with self._state_lock:
                    self._frames_skipped += 1
            self._pending_frame = copy
        self._wake_event.set()

    def send(self, frame: np.ndarray) -> None:
        self.submit(frame)

    def set_brightness(self, value: int) -> None:
        clamped = max(0, min(255, int(value)))
        with self._state_lock:
            caps = set(self._device.get("caps", []))
            self._pending_brightness = clamped
        if "brightness" in caps:
            self._control_queue.put(json.dumps({"type": "brightness", "value": clamped}))
            self._wake_event.set()

    def status(self) -> OutputStatus:
        with self._state_lock:
            return OutputStatus(
                state=self._state,
                protocol=self._protocol,
                device=dict(self._device),
                fps=self._fps,
                frames_sent=self._frames_sent,
                frames_skipped=self._frames_skipped,
                bytes_per_sec=self._bytes_per_sec,
                latency_ms=self._latency_ms,
                last_error=self._last_error,
            )

    @classmethod
    def encode_frame(cls, frame: np.ndarray) -> bytes:
        return encode_full(frame)

    def _negotiate_hello(self, websocket) -> tuple[Literal["v1", "v2"], dict]:
        deadline = time.monotonic() + self.HELLO_TIMEOUT_S
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "v1", {}
            try:
                message = websocket.recv(timeout=remaining)
            except TimeoutError:
                return "v1", {}
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("type") == "hello":
                    device = {
                        "name": str(data.get("name", self.host)),
                        "w": int(data.get("w", 0)),
                        "h": int(data.get("h", 0)),
                        "caps": [str(c) for c in data.get("caps", []) if isinstance(c, str)],
                    }
                    return "v2", device
        return "v1", {}

    def _handle_incoming_message(self, message: str | bytes) -> None:
        if not isinstance(message, str):
            return
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        msg_type = data.get("type")
        if msg_type == "ack":
            try:
                ack_n = int(data["n"])
            except (KeyError, TypeError, ValueError):
                return
            now = time.monotonic()
            with self._state_lock:
                self._acked_count = max(self._acked_count, ack_n)
                done_keys = [seq for seq in self._in_flight if seq <= ack_n]
                if done_keys:
                    highest = max(done_keys)
                    sent_ts, sent_frame = self._in_flight[highest]
                    sample_ms = max(0.0, (now - sent_ts) * 1000.0)
                    self._latency_ms = (
                        sample_ms if self._latency_ms == 0.0 else (0.8 * self._latency_ms + 0.2 * sample_ms)
                    )
                    self._last_acked_frame = sent_frame
                    for k in done_keys:
                        self._in_flight.pop(k, None)
            self._wake_event.set()
        elif msg_type == "hello":
            with self._state_lock:
                self._protocol = "v2"
                self._device = {
                    "name": str(data.get("name", self.host)),
                    "w": int(data.get("w", 0)),
                    "h": int(data.get("h", 0)),
                    "caps": [str(c) for c in data.get("caps", []) if isinstance(c, str)],
                }

    def _receiver_loop(self, websocket, conn_stop: threading.Event) -> None:
        while not self._stop.is_set() and not conn_stop.is_set():
            try:
                message = websocket.recv(timeout=0.15)
            except TimeoutError:
                continue
            except Exception:
                conn_stop.set()
                self._wake_event.set()
                break
            self._handle_incoming_message(message)

    def _reset_connection_state(self) -> None:
        with self._state_lock:
            self._sent_count = 0
            self._acked_count = 0
            self._in_flight.clear()
            self._last_sent_frame = None
            self._last_acked_frame = None
            self._stat_window_start = time.monotonic()
            self._stat_frames = 0
            self._stat_bytes = 0
            self._fps = 0.0
            self._bytes_per_sec = 0.0
            self._latency_ms = 0.0

    def _flush_controls(self, websocket) -> None:
        while True:
            try:
                cmd = self._control_queue.get_nowait()
            except queue.Empty:
                break
            websocket.send(cmd)

    def _record_tx_stats(self, byte_count: int) -> None:
        now = time.monotonic()
        with self._state_lock:
            self._frames_sent += 1
            self._stat_frames += 1
            self._stat_bytes += byte_count
            elapsed = now - self._stat_window_start
            if elapsed >= 1.0:
                self._fps = self._stat_frames / elapsed
                self._bytes_per_sec = self._stat_bytes / elapsed
                self._stat_window_start = now
                self._stat_frames = 0
                self._stat_bytes = 0

    def _worker(self) -> None:
        from websockets.sync.client import connect

        backoff = 1.0
        while not self._stop.is_set():
            with self._state_lock:
                self._state = "connecting"
                self._protocol = "unknown"
                self._device = {}
            self._reset_connection_state()
            conn_stop = threading.Event()
            recv_thread: threading.Thread | None = None
            try:
                with connect(self.url, open_timeout=2, close_timeout=1, max_size=None) as websocket:
                    backoff = 1.0
                    protocol, device = self._negotiate_hello(websocket)
                    caps = set(device.get("caps", []))
                    with self._state_lock:
                        self._protocol = protocol
                        self._device = device
                        self._state = "online"
                        self._last_error = ""
                        pending_brightness = self._pending_brightness
                    if pending_brightness is not None and "brightness" in caps:
                        websocket.send(json.dumps({"type": "brightness", "value": pending_brightness}))

                    recv_thread = threading.Thread(
                        target=self._receiver_loop,
                        args=(websocket, conn_stop),
                        name="GlediatorWSRecv",
                        daemon=True,
                    )
                    recv_thread.start()

                    while not self._stop.is_set() and not conn_stop.is_set():
                        self._flush_controls(websocket)
                        with self._state_lock:
                            cur_caps = set(self._device.get("caps", []))
                            use_ack = "ack" in cur_caps
                            in_flight = self._sent_count - self._acked_count
                            oldest_ts = min((ts for ts, _ in self._in_flight.values()), default=None)
                            dev_w = int(self._device.get("w", 0))
                            dev_h = int(self._device.get("h", 0))

                        if use_ack and in_flight >= self.MAX_IN_FLIGHT:
                            if oldest_ts is not None and (time.monotonic() - oldest_ts) > self.ACK_WATCHDOG_S:
                                raise TimeoutError("Timed out waiting for device frame ack")
                            self._wake_event.wait(timeout=0.05)
                            self._wake_event.clear()
                            continue

                        with self._slot_lock:
                            frame = self._pending_frame
                            self._pending_frame = None

                        if frame is None:
                            self._wake_event.wait(timeout=0.1)
                            self._wake_event.clear()
                            continue

                        fh, fw = frame.shape[:2]
                        if self._protocol == "v2" and dev_w > 0 and dev_h > 0 and (dev_w != fw or dev_h != fh):
                            with self._state_lock:
                                self._state = "mismatch"
                                self._last_error = f"Device is {dev_w}×{dev_h}, app is {fw}×{fh}"
                            continue

                        with self._state_lock:
                            if self._state == "mismatch":
                                self._state = "online"
                                self._last_error = ""
                            ref = self._last_acked_frame if use_ack else self._last_sent_frame

                        if ref is not None and ref.shape != frame.shape:
                            ref = None

                        kind, payload = choose_encoding(ref, frame, cur_caps)
                        if kind == "skip" or payload is None:
                            with self._state_lock:
                                self._frames_skipped += 1
                            continue

                        websocket.send(payload)
                        now = time.monotonic()
                        with self._state_lock:
                            self._sent_count += 1
                            seq = self._sent_count
                            self._last_sent_frame = frame
                            if use_ack:
                                self._in_flight[seq] = (now, frame)
                        self._record_tx_stats(len(payload))
            except Exception as exc:
                if not self._stop.is_set():
                    with self._state_lock:
                        self._state = "error"
                        self._last_error = str(exc)
                    self._stop.wait(timeout=backoff)
                    backoff = min(5.0, backoff * 2.0)
            finally:
                conn_stop.set()
                if recv_thread is not None:
                    recv_thread.join(timeout=0.5)
        with self._state_lock:
            self._state = "stopped"
