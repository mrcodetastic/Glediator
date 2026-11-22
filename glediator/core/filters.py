from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from glediator.generators.palettes import parse_hex_color

FILTER_SCHEMAS: dict[str, dict[str, tuple]] = {
    "Invert": {},
    "Monochrome": {},
    "Threshold": {"level": ("int", 128, 0, 255, 1)},
    "Blur": {"radius": ("int", 1, 1, 4, 1)},
    "Hue Shift": {
        "degrees": ("float", 0.0, 0.0, 360.0, 5.0),
        "speed": ("float", 30.0, 0.0, 360.0, 5.0),
    },
    "Mirror": {"axis": ("choice", "Horizontal", ("Horizontal", "Vertical", "Quad"), "", "")},
    "Kaleidoscope": {"segments": ("int", 4, 2, 12, 1)},
    "Pixelate": {"block_size": ("int", 2, 2, 16, 1)},
    "Strobe": {"rate_hz": ("float", 4.0, 0.5, 30.0, 0.5)},
    "Tint": {
        "color": ("color", "#ff5500", "", "", ""),
        "amount": ("float", 0.5, 0.0, 1.0, 0.05),
    },
    "Trails": {"decay": ("float", 0.85, 0.0, 0.99, 0.02)},
    "Edge": {"gain": ("float", 1.5, 0.5, 5.0, 0.1)},
}

FILTER_NAMES: tuple[str, ...] = tuple(FILTER_SCHEMAS)


def sanitize_filter_params(name: str, values: dict | None) -> dict:
    schema = FILTER_SCHEMAS.get(name, {})
    out: dict[str, Any] = {}
    src = values if isinstance(values, dict) else {}
    for key, spec in schema.items():
        kind, default, low, high, _step = spec
        raw = src.get(key, default)
        try:
            if kind in ("str", "color"):
                out[key] = str(raw)[:40]
            elif kind == "choice":
                out[key] = raw if raw in low else default
            elif kind == "int":
                out[key] = max(int(low), min(int(high), int(raw)))
            else:
                out[key] = max(float(low), min(float(high), float(raw)))
        except (TypeError, ValueError):
            out[key] = default
    return out


def sanitize_filter_chain(chain: list | None, legacy_filter: str = "None") -> list[dict]:
    if isinstance(chain, list):
        cleaned: list[dict] = []
        for entry in chain[:3]:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", ""))
            if name not in FILTER_SCHEMAS:
                continue
            cleaned.append({"name": name, "params": sanitize_filter_params(name, entry.get("params"))})
        return cleaned
    if legacy_filter in FILTER_SCHEMAS:
        return [{"name": legacy_filter, "params": sanitize_filter_params(legacy_filter, {})}]
    return []


def _box_blur(frame: np.ndarray, radius: int) -> np.ndarray:
    r = max(1, min(4, int(radius)))
    k = 2 * r + 1
    padded_h = np.pad(frame.astype(np.float32), ((r, r), (0, 0), (0, 0)), mode="edge")
    csum_h = np.zeros((padded_h.shape[0] + 1, padded_h.shape[1], 3), dtype=np.float32)
    np.cumsum(padded_h, axis=0, out=csum_h[1:])
    v_blur = (csum_h[k:] - csum_h[:-k]) / k

    padded_w = np.pad(v_blur, ((0, 0), (r, r), (0, 0)), mode="edge")
    csum_w = np.zeros((padded_w.shape[0], padded_w.shape[1] + 1, 3), dtype=np.float32)
    np.cumsum(padded_w, axis=1, out=csum_w[:, 1:])
    h_blur = (csum_w[:, k:] - csum_w[:, :-k]) / k
    return np.clip(np.rint(h_blur), 0, 255).astype(np.uint8)


def _hue_shift(frame: np.ndarray, degrees: float) -> np.ndarray:
    angle = np.deg2rad(degrees)
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)
    sqrt_1_3 = np.sqrt(1.0 / 3.0)
    m = np.array([
        [
            cos_a + (1.0 - cos_a) / 3.0,
            (1.0 - cos_a) / 3.0 - sqrt_1_3 * sin_a,
            (1.0 - cos_a) / 3.0 + sqrt_1_3 * sin_a,
        ],
        [
            (1.0 - cos_a) / 3.0 + sqrt_1_3 * sin_a,
            cos_a + (1.0 - cos_a) / 3.0,
            (1.0 - cos_a) / 3.0 - sqrt_1_3 * sin_a,
        ],
        [
            (1.0 - cos_a) / 3.0 - sqrt_1_3 * sin_a,
            (1.0 - cos_a) / 3.0 + sqrt_1_3 * sin_a,
            cos_a + (1.0 - cos_a) / 3.0,
        ],
    ], dtype=np.float32)
    shifted = frame.astype(np.float32) @ m.T
    return np.clip(np.rint(shifted), 0, 255).astype(np.uint8)


def _mirror(frame: np.ndarray, axis: str) -> np.ndarray:
    h, w = frame.shape[:2]
    out = frame.copy()
    if axis in ("Horizontal", "Quad"):
        half = w // 2
        if half > 0:
            out[:, w - half :] = out[:, :half][:, ::-1]
    if axis in ("Vertical", "Quad"):
        half = h // 2
        if half > 0:
            out[h - half :, :] = out[:half, :][::-1, :]
    return out


def _kaleidoscope(frame: np.ndarray, segments: int) -> np.ndarray:
    h, w = frame.shape[:2]
    segs = max(2, min(12, int(segments)))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx = (w - 1) / 2.0
    cy = (h - 1) / 2.0
    dx = xx - cx
    dy = yy - cy
    radius = np.sqrt(dx * dx + dy * dy)
    theta = np.mod(np.arctan2(dy, dx), 2.0 * np.pi)
    sector = (2.0 * np.pi) / segs
    theta = np.mod(theta, sector)
    theta = np.where(theta > sector * 0.5, sector - theta, theta)
    sx = np.clip(np.rint(cx + radius * np.cos(theta)).astype(np.intp), 0, w - 1)
    sy = np.clip(np.rint(cy + radius * np.sin(theta)).astype(np.intp), 0, h - 1)
    return frame[sy, sx]


def _pixelate(frame: np.ndarray, block_size: int) -> np.ndarray:
    h, w = frame.shape[:2]
    bs = max(2, min(16, int(block_size)))
    ys = (np.arange(h) // bs) * bs
    xs = (np.arange(w) // bs) * bs
    return frame[ys[:, None], xs[None, :]]


def _edge(frame: np.ndarray, gain: float) -> np.ndarray:
    gray = (
        0.2126 * frame[..., 0].astype(np.float32)
        + 0.7152 * frame[..., 1].astype(np.float32)
        + 0.0722 * frame[..., 2].astype(np.float32)
    )
    p = np.pad(gray, 1, mode="edge")
    gx = (
        -p[:-2, :-2] + p[:-2, 2:]
        - 2.0 * p[1:-1, :-2] + 2.0 * p[1:-1, 2:]
        - p[2:, :-2] + p[2:, 2:]
    )
    gy = (
        -p[:-2, :-2] - 2.0 * p[:-2, 1:-1] - p[:-2, 2:]
        + p[2:, :-2] + 2.0 * p[2:, 1:-1] + p[2:, 2:]
    )
    mag = np.clip(np.sqrt(gx * gx + gy * gy) * float(gain), 0, 255).astype(np.uint8)
    return np.repeat(mag[..., None], 3, axis=2)


def apply_filter_entry(
    frame: np.ndarray,
    entry: dict,
    t: float,
    state: dict | None = None,
) -> np.ndarray:
    name = entry.get("name", "")
    params = entry.get("params", {})
    if name == "Invert":
        return 255 - frame
    if name == "Monochrome":
        luminance = np.dot(frame[..., :3], [0.2126, 0.7152, 0.0722]).astype(np.uint8)
        return np.repeat(luminance[..., None], 3, axis=2)
    if name == "Threshold":
        lvl = int(params.get("level", 128))
        return np.where(frame >= lvl, 255, 0).astype(np.uint8)
    if name == "Blur":
        return _box_blur(frame, int(params.get("radius", 1)))
    if name == "Hue Shift":
        deg = float(params.get("degrees", 0.0)) + t * float(params.get("speed", 30.0))
        return _hue_shift(frame, deg)
    if name == "Mirror":
        return _mirror(frame, str(params.get("axis", "Horizontal")))
    if name == "Kaleidoscope":
        return _kaleidoscope(frame, int(params.get("segments", 4)))
    if name == "Pixelate":
        return _pixelate(frame, int(params.get("block_size", 2)))
    if name == "Strobe":
        rate = max(0.5, float(params.get("rate_hz", 4.0)))
        on = (t * rate) % 1.0 < 0.5
        return frame if on else np.zeros_like(frame)
    if name == "Tint":
        amt = float(np.clip(float(params.get("amount", 0.5)), 0.0, 1.0))
        col = parse_hex_color(str(params.get("color", "#ff5500")))
        out = frame.astype(np.float32) * (1.0 - amt) + col[None, None, :] * amt
        return np.clip(np.rint(out), 0, 255).astype(np.uint8)
    if name == "Trails":
        decay = float(np.clip(float(params.get("decay", 0.85)), 0.0, 0.99))
        if state is None:
            return frame
        prev = state.get("trails_buf")
        if prev is None or prev.shape != frame.shape:
            buf = frame.astype(np.float32)
        else:
            buf = np.maximum(frame.astype(np.float32), prev * decay)
        state["trails_buf"] = buf
        return np.clip(np.rint(buf), 0, 255).astype(np.uint8)
    if name == "Edge":
        return _edge(frame, float(params.get("gain", 1.5)))
    return frame


def apply_filter_chain(
    frame: np.ndarray,
    chain: list[dict],
    t: float,
    state: dict | None = None,
) -> np.ndarray:
    out = frame
    for entry in chain:
        out = apply_filter_entry(out, entry, t, state)
    return out


__all__ = [
    "FILTER_NAMES",
    "FILTER_SCHEMAS",
    "Callable",
    "apply_filter_chain",
    "apply_filter_entry",
    "sanitize_filter_chain",
    "sanitize_filter_params",
]
