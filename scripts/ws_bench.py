"""Throughput benchmark for MrCodetastic WebSocket v1/v2 frame delivery."""

from __future__ import annotations

import argparse
import time

import numpy as np

from glediator.effects import create_effect
from glediator.output.delta import choose_encoding, encode_full
from glediator.output.websocket_output import WebSocketOutput


def _generate_frames(kind: str, width: int, height: int, count: int) -> list[np.ndarray]:
    rng = np.random.default_rng(7)
    if kind == "noise":
        return [rng.integers(0, 256, (height, width, 3), dtype=np.uint8) for _ in range(count)]
    if kind == "black":
        base = np.zeros((height, width, 3), dtype=np.uint8)
        frames = []
        for i in range(count):
            f = base.copy()
            f[i % height, i % width] = (255, 80, 40)
            frames.append(f)
        return frames
    fx_name = "Plasma" if kind == "plasma" else "Scrolling Text"
    fx = create_effect(fx_name)
    fx.configure({})
    return [fx.drawFrame(width, height, i / 60.0) for i in range(count)]


def run_local_encoding_bench(width: int, height: int) -> None:
    print(f"\n=== Encoding size benchmark ({width}x{height}) ===")
    for kind in ("noise", "plasma", "text", "black"):
        frames = _generate_frames(kind, width, height, 60)
        full_bytes = sum(len(encode_full(f)) for f in frames)
        delta_bytes = 0
        rle_bytes = 0
        prev = None
        for f in frames:
            _, p_delta = choose_encoding(prev, f, {"delta"})
            delta_bytes += len(p_delta) if p_delta else 0
            _, p_rle = choose_encoding(prev, f, {"delta", "rle"})
            rle_bytes += len(p_rle) if p_rle else 0
            prev = f
        print(
            f"{kind:8s} | full: {full_bytes / 1024:7.1f} KB "
            f"| delta: {delta_bytes / 1024:7.1f} KB ({delta_bytes / full_bytes * 100:5.1f}%) "
            f"| delta+rle: {rle_bytes / 1024:7.1f} KB ({rle_bytes / full_bytes * 100:5.1f}%)"
        )


def run_live_bench(host: str, port: int, width: int, height: int, seconds: float) -> None:
    out = WebSocketOutput(host, port)
    out.start()
    try:
        deadline = time.monotonic() + 3.0
        while not out.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        if not out.connected:
            print(f"Failed to connect to ws://{host}:{port}: {out.status().last_error}")
            return
        frames = _generate_frames("plasma", width, height, 120)
        start = time.monotonic()
        idx = 0
        while time.monotonic() - start < seconds:
            out.submit(frames[idx % len(frames)])
            idx += 1
            time.sleep(1.0 / 60.0)
        st = out.status()
        print(
            f"Live {width}x{height} proto={st.protocol} fps={st.fps:.1f} "
            f"sent={st.frames_sent} skip={st.frames_skipped} "
            f"rate={st.bytes_per_sec / 1024:.1f} KB/s latency={st.latency_ms:.1f} ms"
        )
    finally:
        out.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark WebSocket encoding and live throughput")
    parser.add_argument("--host", default="", help="Optional target WebSocket host")
    parser.add_argument("--port", type=int, default=12345)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--height", type=int, default=32)
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()
    run_local_encoding_bench(args.width, args.height)
    if args.host:
        run_live_bench(args.host, args.port, args.width, args.height, args.seconds)


if __name__ == "__main__":
    main()
