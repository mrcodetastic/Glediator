"""Shared state/configuration and low-level rendering helpers for effects."""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from glediator.effects.base import Effect
from glediator.generators.palettes import PALETTE_NAMES, colorize, parse_hex_color
from glediator.generators.settings import sanitize_parameters

AURORA_SETTINGS = {
    "speed": ("float", 1.0, 0.1, 8.0, 0.1),
    "scale": ("float", 1.0, 0.1, 8.0, 0.1),
    "palette": ("choice", "Aurora", PALETTE_NAMES, "", ""),
}

_FONT_PATH_CACHE: dict[str, str | None] = {}
_FONT_INDEX: dict[str, str] | None = None
_TEXT_STRIP_CACHE: OrderedDict[tuple, tuple[np.ndarray, int, int]] = OrderedDict()
_BUNDLED_FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "DejaVuSans.ttf"


class ConfiguredEffect(Effect):
    """Convenience base for effects using the application's settings schema."""

    settings: dict = {}

    def __init__(self) -> None:
        self.parameters: dict = {}
        self._rng = np.random.default_rng()
        self.last_error = ""

    def setup(self) -> None:
        self.configure({})

    def configure(self, parameters: dict | None = None) -> None:
        self.parameters = sanitize_parameters(self.name, parameters, self.settings)


def coordinates(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Return normalized x/y coordinate grids in the legacy renderer layout."""
    return (
        np.linspace(0, 1, width, dtype=np.float32)[None, :],
        np.linspace(0, 1, height, dtype=np.float32)[:, None],
    )


def aurora_coordinates(width: int, height: int):
    x, y = coordinates(width, height)
    xx, yy = np.broadcast_to(x, (height, width)), np.broadcast_to(y, (height, width))
    nx, ny = xx * 2 - 1, yy * 2 - 1
    return x, y, xx, yy, nx, ny, np.sqrt(nx * nx + ny * ny), np.arctan2(ny, nx)


def _normalize_font_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _build_font_index() -> dict[str, str]:
    global _FONT_INDEX
    if _FONT_INDEX is not None:
        return _FONT_INDEX
    index: dict[str, str] = {}
    search_dirs = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path("/usr/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / ".local" / "share" / "fonts",
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path.home() / "Library" / "Fonts",
    ]
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            try:
                for font_path in directory.rglob(ext):
                    key = _normalize_font_key(font_path.stem)
                    if key and key not in index:
                        index[key] = str(font_path)
            except OSError:
                continue
    _FONT_INDEX = index
    return index


def _resolve_font_path(family: str) -> str | None:
    if family in _FONT_PATH_CACHE:
        return _FONT_PATH_CACHE[family]
    win_map = {
        "Arial": "arial.ttf",
        "Calibri": "calibri.ttf",
        "Consolas": "consola.ttf",
        "Courier New": "cour.ttf",
        "Georgia": "georgia.ttf",
        "Segoe UI": "segoeui.ttf",
        "Tahoma": "tahoma.ttf",
        "Times New Roman": "times.ttf",
        "Verdana": "verdana.ttf",
    }
    win_candidate = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / win_map.get(family, "")
    if win_map.get(family) and win_candidate.is_file():
        _FONT_PATH_CACHE[family] = str(win_candidate)
        return str(win_candidate)
    index = _build_font_index()
    key = _normalize_font_key(family)
    if key in index:
        _FONT_PATH_CACHE[family] = index[key]
        return index[key]
    _FONT_PATH_CACHE[family] = None
    return None


def load_font(family: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    resolved = _resolve_font_path(family)
    if resolved:
        try:
            return ImageFont.truetype(resolved, size=size)
        except OSError:
            pass
    for candidate_name in (family, str(_BUNDLED_FONT), "DejaVuSans.ttf"):
        if not candidate_name:
            continue
        try:
            return ImageFont.truetype(candidate_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _render_text_strip(
    text: str, family: str, size: int, direction: str, width: int, height: int
) -> tuple[np.ndarray, int, int]:
    cache_key = (text, family, size, direction, width, height)
    cached = _TEXT_STRIP_CACHE.get(cache_key)
    if cached is not None:
        _TEXT_STRIP_CACHE.move_to_end(cache_key)
        return cached
    font = load_font(family, size)
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    bounds = measure.textbbox((0, 0), text, font=font)
    text_width = max(1, bounds[2] - bounds[0])
    text_height = max(1, bounds[3] - bounds[1])
    if direction in ("Left", "Right"):
        strip = Image.new("L", (text_width, height), 0)
        strip_draw = ImageDraw.Draw(strip)
        text_y = (height - text_height) // 2 - bounds[1]
        strip_draw.text((-bounds[0], text_y), text, font=font, fill=255)
    else:
        strip = Image.new("L", (width, text_height), 0)
        strip_draw = ImageDraw.Draw(strip)
        text_x = (width - text_width) // 2 - bounds[0]
        strip_draw.text((text_x, -bounds[1]), text, font=font, fill=255)
    strip_arr = np.asarray(strip, dtype=np.float32) / 255.0
    result = (strip_arr, text_width, text_height)
    _TEXT_STRIP_CACHE[cache_key] = result
    if len(_TEXT_STRIP_CACHE) > 64:
        _TEXT_STRIP_CACHE.popitem(last=False)
    return result


def scrolling_text(width: int, height: int, t: float, params: dict) -> np.ndarray:
    text = str(params.get("text", ""))
    bg = parse_hex_color(str(params.get("background", "#000000")))
    if not text:
        return np.broadcast_to(bg.astype(np.uint8), (height, width, 3)).copy()
    direction = str(params.get("direction", "Left"))
    strip_arr, text_width, text_height = _render_text_strip(
        text,
        str(params.get("font", "Arial")),
        int(params.get("font_size", 18)),
        direction,
        width,
        height,
    )
    mask = np.zeros((height, width), dtype=np.float32)
    distance = int(t * float(params.get("speed", 5.0)))
    if direction in ("Left", "Right"):
        phase = distance % (width + text_width)
        offset_x = width - phase if direction == "Left" else -text_width + phase
        dst_x0 = max(0, offset_x)
        dst_x1 = min(width, offset_x + text_width)
        if dst_x1 > dst_x0:
            src_x0 = dst_x0 - offset_x
            src_x1 = src_x0 + (dst_x1 - dst_x0)
            mask[:, dst_x0:dst_x1] = strip_arr[:, src_x0:src_x1]
    else:
        phase = distance % (height + text_height)
        offset_y = height - phase if direction == "Up" else -text_height + phase
        dst_y0 = max(0, offset_y)
        dst_y1 = min(height, offset_y + text_height)
        if dst_y1 > dst_y0:
            src_y0 = dst_y0 - offset_y
            src_y1 = src_y0 + (dst_y1 - dst_y0)
            mask[dst_y0:dst_y1, :] = strip_arr[src_y0:src_y1, :]

    if params.get("color_mode") == "Solid":
        fg = parse_hex_color(str(params.get("color", "#1EDCFF")))[None, None, :]
    else:
        grad = np.mod(np.linspace(0.0, 1.0, width, dtype=np.float32) + t * 0.15, 1.0)
        fg = colorize(grad, str(params.get("palette", "Ocean"))).astype(np.float32)[None, :, :]
    out = fg * mask[..., None] + bg[None, None, :] * (1.0 - mask[..., None])
    return np.clip(out, 0, 255).astype(np.uint8)


def capture_screen(effect: ConfiguredEffect, width: int, height: int, params: dict) -> np.ndarray:
    signature = None
    try:
        if not hasattr(effect, "_capture_backend") or effect._capture_backend is None:
            import mss

            effect._capture_backend = mss.MSS()
            effect._capture_black_frames = 0
        capture = effect._capture_backend
        monitors = capture.monitors
        monitor_index = max(1, min(int(params["monitor"]), len(monitors) - 1)) if len(monitors) > 1 else 0
        monitor = monitors[monitor_index]
        x, y = int(params["x"]), int(params["y"])
        region = {
            "left": monitor["left"] + x,
            "top": monitor["top"] + y,
            "width": max(1, int(params["width"]) or monitor["width"] - x),
            "height": max(1, int(params["height"]) or monitor["height"] - y),
        }
        capture_fps = max(1, min(30, int(params.get("capture_fps", 8))))
        signature = (
            monitor_index,
            region["left"],
            region["top"],
            region["width"],
            region["height"],
            width,
            height,
            capture_fps,
        )
        now = time.monotonic()
        cached = getattr(effect, "_capture_frame_cache", None)
        if (
            cached is not None
            and getattr(effect, "_capture_signature", None) == signature
            and now - getattr(effect, "_capture_last_time", 0.0) < 1.0 / capture_fps
        ):
            return cached.copy()
        shot = np.asarray(capture.grab(region), dtype=np.uint8)[..., :3][..., ::-1]
        if np.any(shot):
            effect._capture_black_frames = 0
            effect.last_error = ""
        else:
            effect._capture_black_frames += 1
            if effect._capture_black_frames >= 30:
                effect.last_error = (
                    "Screen Capture is returning black frames. Verify the selected monitor/region; "
                    "Windows secure desktop, protected video, or a locked/remote session may block capture."
                )
        ys = np.linspace(0, shot.shape[0] - 1, height).astype(np.intp)
        xs = np.linspace(0, shot.shape[1] - 1, width).astype(np.intp)
        frame = shot[ys[:, None], xs[None, :]].copy()
        effect._capture_frame_cache = frame
        effect._capture_signature = signature
        effect._capture_last_time = now
        return frame.copy()
    except Exception as exc:
        effect.last_error = f"Screen capture failed: {exc}"
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        if signature is not None:
            effect._capture_frame_cache = frame
            effect._capture_signature = signature
            effect._capture_last_time = time.monotonic()
        return frame


def close_capture(effect: ConfiguredEffect) -> None:
    backend = getattr(effect, "_capture_backend", None)
    if backend is not None:
        try:
            backend.close()
        except Exception:
            pass
        effect._capture_backend = None
    effect._capture_frame_cache = None
    effect._capture_signature = None
