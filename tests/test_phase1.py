from __future__ import annotations

import json
import struct
import threading
import time
from pathlib import Path

import numpy as np
from websockets.sync.server import serve

from glediator.core.config import EngineConfig
from glediator.core.frame import to_rgb565
from glediator.network.discovery import DeviceDiscovery
from glediator.output.delta import (
    MARKER_DELTA,
    MARKER_FULL,
    MARKER_RLE,
    choose_encoding,
    diff_rects,
    encode_delta,
    encode_rle,
)
from glediator.output.hub import OutputHub
from glediator.output.websocket_output import WebSocketOutput


def _decode_delta_into(buf_rgb565: np.ndarray, payload: bytes) -> np.ndarray:
    assert payload[:2] == MARKER_DELTA
    (n_rects,) = struct.unpack(">H", payload[2:4])
    pos = 4
    out = buf_rgb565.copy()
    for _ in range(n_rects):
        x, y, w, h = struct.unpack(">HHHH", payload[pos : pos + 8])
        pos += 8
        nbytes = w * h * 2
        patch = np.frombuffer(payload[pos : pos + nbytes], dtype=">u2").reshape(h, w)
        out[y : y + h, x : x + w] = patch
        pos += nbytes
    assert pos == len(payload)
    return out


def _decode_rle(payload: bytes, width: int, height: int) -> np.ndarray:
    assert payload[:2] == MARKER_RLE
    pixels: list[int] = []
    pos = 2
    while pos < len(payload):
        run = payload[pos] + 1
        (color,) = struct.unpack(">H", payload[pos + 1 : pos + 3])
        pixels.extend([color] * run)
        pos += 3
    assert len(pixels) == width * height
    return np.array(pixels, dtype=np.uint16).reshape(height, width)


def test_delta_encode_decode_round_trip():
    rng = np.random.default_rng(42)
    prev = np.zeros((32, 64, 3), dtype=np.uint8)
    cur = prev.copy()
    cur[5, 10] = (255, 0, 0)
    cur[20:24, 30:40] = (0, 255, 128)
    rects = diff_rects(prev, cur)
    assert len(rects) >= 1
    payload = encode_delta(cur, rects)
    decoded = _decode_delta_into(to_rgb565(prev), payload)
    assert np.array_equal(decoded, to_rgb565(cur))

    # Full random noise falls back to full frame in choose_encoding
    full_noise = rng.integers(0, 256, (32, 64, 3), dtype=np.uint8)
    kind, data = choose_encoding(prev, full_noise, {"delta"})
    assert kind == "full"
    assert data[:2] == MARKER_FULL

    # Identical frame skips
    kind_skip, data_skip = choose_encoding(cur, cur.copy(), {"delta"})
    assert kind_skip == "skip"
    assert data_skip is None


def test_rle_encode_decode_round_trip():
    frame = np.zeros((16, 32, 3), dtype=np.uint8)
    frame[:4, :] = (255, 0, 0)
    frame[4:10, 8:20] = (0, 255, 0)
    payload = encode_rle(frame)
    decoded = _decode_rle(payload, 32, 16)
    assert np.array_equal(decoded, to_rgb565(frame))
    kind, data = choose_encoding(None, frame, {"rle"})
    assert kind == "rle"
    assert data is not None and len(data) < len(frame.tobytes())


def test_output_hub_master_lut_and_multi_device():
    class Collector:
        def __init__(self) -> None:
            self.frames: list[np.ndarray] = []

        def submit(self, frame: np.ndarray) -> None:
            self.frames.append(frame)

    hub = OutputHub()
    c1, c2 = Collector(), Collector()
    hub.add("a", c1)
    hub.add("b", c2)

    frame = np.full((4, 4, 3), 200, dtype=np.uint8)
    hub.set_processing(brightness=0.5, gamma=1.0)
    hub.submit(frame)
    assert len(c1.frames) == 1 and len(c2.frames) == 1
    assert np.all(c1.frames[0] == 100)
    assert np.array_equal(c1.frames[0], c2.frames[0])

    hub.set_processing(brightness=0.0, gamma=1.0)
    hub.submit(frame)
    assert np.all(c1.frames[1] == 0)


def test_websocket_output_v1_v2_mismatch_and_ack():
    # 1) v1 server (never sends hello)
    v1_received: list[bytes] = []
    v1_got = threading.Event()

    def v1_handler(ws):
        for msg in ws:
            if isinstance(msg, bytes):
                v1_received.append(msg)
                v1_got.set()

    with serve(v1_handler, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        out = WebSocketOutput("127.0.0.1", port)
        out.start()
        try:
            time.sleep(0.6)
            out.submit(np.zeros((8, 16, 3), dtype=np.uint8))
            assert v1_got.wait(timeout=2.0)
            assert v1_received[0][:2] == MARKER_FULL
            assert out.status().protocol == "v1"
        finally:
            out.stop()
            server.shutdown()

    # 2) v2 mismatch server (64x32 vs 16x8)
    mismatch_frames: list[bytes] = []

    def mismatch_handler(ws):
        ws.send(json.dumps({"type": "hello", "v": 2, "name": "panel", "w": 64, "h": 32, "caps": ["delta", "ack"]}))
        for msg in ws:
            if isinstance(msg, bytes):
                mismatch_frames.append(msg)

    with serve(mismatch_handler, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        out = WebSocketOutput("127.0.0.1", port)
        out.start()
        try:
            deadline = time.monotonic() + 2.0
            while out.status().protocol != "v2" and time.monotonic() < deadline:
                time.sleep(0.02)
            out.submit(np.zeros((8, 16, 3), dtype=np.uint8))
            time.sleep(0.2)
            st = out.status()
            assert st.state == "mismatch"
            assert mismatch_frames == []
        finally:
            out.stop()
            server.shutdown()

    # 3) v2 ack flow control & delta
    ack_frames: list[bytes] = []

    def v2_handler(ws):
        ws.send(json.dumps({"type": "hello", "v": 2, "name": "panel", "w": 16, "h": 8, "caps": ["delta", "ack"]}))
        n = 0
        for msg in ws:
            if isinstance(msg, bytes):
                ack_frames.append(msg)
                time.sleep(0.06)
                n += 1
                ws.send(json.dumps({"type": "ack", "n": n}))

    with serve(v2_handler, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        out = WebSocketOutput("127.0.0.1", port)
        out.start()
        try:
            deadline = time.monotonic() + 2.0
            while out.status().protocol != "v2" and time.monotonic() < deadline:
                time.sleep(0.02)
            for i in range(10):
                f = np.zeros((8, 16, 3), dtype=np.uint8)
                f[0, i % 16] = (255, 255, 255)
                out.submit(f)
                time.sleep(0.01)
            time.sleep(0.35)
            st = out.status()
            assert st.state == "online"
            assert st.frames_skipped > 0
            assert st.latency_ms > 0
            assert ack_frames[0][:2] == MARKER_FULL
            assert any(p[:2] == MARKER_DELTA for p in ack_frames[1:])
        finally:
            out.stop()
            server.shutdown()


def test_discovery_v2_and_expiry():
    v1 = DeviceDiscovery.parse_beacon(b"CODETASTIC")
    assert v1 is not None and v1["v"] == 1

    v2 = DeviceDiscovery.parse_beacon(
        b'CODETASTIC {"v":2,"name":"wall-1","w":128,"h":64,"port":12345}'
    )
    assert v2 == {"v": 2, "name": "wall-1", "w": 128, "h": 64, "port": 12345}

    malformed = DeviceDiscovery.parse_beacon(b"CODETASTIC {bad-json")
    assert malformed is not None and malformed["v"] == 1

    assert DeviceDiscovery.parse_beacon(b"OTHER") is None

    now = [0.0]
    disc = DeviceDiscovery(clock=lambda: now[0])
    disc.record_beacon("192.168.1.10", v2)
    events = disc.poll_events()
    assert events[0][0] == "device"

    now[0] = 11.0
    events = disc.poll_events()
    assert ("device_stale", "192.168.1.10") in events

    now[0] = 61.0
    events = disc.poll_events()
    assert ("device_lost", "192.168.1.10") in events


def test_v1_to_v3_config_migration(tmp_path: Path):
    path = tmp_path / "settings.json"
    v1 = {
        "width": 64,
        "height": 32,
        "mapping": "vertical-snake",
        "websocket_host": "192.168.1.77",
        "websocket_port": 12345,
        "presets": [{"name": "A", "state": {}, "mapping": "horizontal-snake"}],
    }
    path.write_text(json.dumps(v1), encoding="utf-8")
    cfg = EngineConfig.load(path)
    assert cfg.config_version == 3
    assert cfg.devices[0]["host"] == "192.168.1.77"
    assert cfg.devices[0]["port"] == 12345
    assert cfg.master == {"brightness": 1.0, "gamma": 1.0}
    assert "mapping" not in cfg.presets[0]

    # Untouched 127.0.0.1:12345 default does not populate devices
    untouched = tmp_path / "untouched.json"
    untouched.write_text(json.dumps({"websocket_host": "127.0.0.1", "websocket_port": 12345}), encoding="utf-8")
    cfg_default = EngineConfig.load(untouched)
    assert cfg_default.devices == []
