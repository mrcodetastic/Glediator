from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from glediator.effects.support import ConfiguredEffect


def compute_video_resize(src_w: int, src_h: int, dst_w: int, dst_h: int, fit: str) -> tuple[int, int]:
    """Return intermediate (scaled_w, scaled_h) preserving aspect ratio for Fill or Fit."""
    if src_w <= 0 or src_h <= 0:
        return dst_w, dst_h
    if fit == "Stretch":
        return dst_w, dst_h
    if fit == "Fit (Letterbox)":
        scale = min(dst_w / src_w, dst_h / src_h)
        return max(1, min(dst_w, round(src_w * scale))), max(1, min(dst_h, round(src_h * scale)))
    # Default: Fill (Crop) — best fit that covers the full matrix, clipped on overflow axis
    scale = max(dst_w / src_w, dst_h / src_h)
    return max(dst_w, round(src_w * scale)), max(dst_h, round(src_h * scale))


def apply_video_fit(rgb: np.ndarray, dst_w: int, dst_h: int, fit: str) -> np.ndarray:
    """Center-crop (for Fill) or letterbox-pad (for Fit) a scaled RGB frame to (dst_h, dst_w, 3)."""
    sh, sw = rgb.shape[:2]
    if sw == dst_w and sh == dst_h:
        return np.ascontiguousarray(rgb, dtype=np.uint8)
    if fit == "Fit (Letterbox)":
        canvas = np.zeros((dst_h, dst_w, 3), dtype=np.uint8)
        cw = min(sw, dst_w)
        ch = min(sh, dst_h)
        x0 = (dst_w - cw) // 2
        y0 = (dst_h - ch) // 2
        canvas[y0 : y0 + ch, x0 : x0 + cw] = rgb[:ch, :cw]
        return canvas
    # Fill (Crop)
    x0 = max(0, (sw - dst_w) // 2)
    y0 = max(0, (sh - dst_h) // 2)
    return np.ascontiguousarray(rgb[y0 : y0 + dst_h, x0 : x0 + dst_w], dtype=np.uint8)


class VideoPlayerEffect(ConfiguredEffect):
    name = "Video Player"
    description = "Play a video file decoded and cropped to fill the matrix."
    category = "Capture"
    settings = {
        "path": ("file", "", "", "", ""),
        "fit": ("choice", "Fill (Crop)", ("Fill (Crop)", "Fit (Letterbox)", "Stretch"), "", ""),
        "speed": ("float", 1.0, 0.25, 4.0, 0.05),
        "loop": ("bool", True, False, True, 1),
    }

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_sig: tuple[str, int, int, str, float, bool] | None = None
        self._latest_frame: np.ndarray | None = None

    def _start_decoder(
        self,
        path: str,
        width: int,
        height: int,
        fit: str,
        speed: float,
        loop: bool,
    ) -> None:
        sig = (path, width, height, fit, speed, loop)
        if sig == self._current_sig:
            return
        self.cleanup()
        self._current_sig = sig
        if not path:
            self.last_error = ""
            return
        if not Path(path).is_file():
            self.last_error = f"Video file not found: {path}"
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._decode_loop,
            args=(path, width, height, fit, speed, loop),
            name="GlediatorVideoDecode",
            daemon=True,
        )
        self._thread.start()

    def _decode_loop(
        self,
        path: str,
        width: int,
        height: int,
        fit: str,
        speed: float,
        loop: bool,
    ) -> None:
        try:
            import av
        except ImportError:
            self.last_error = "PyAV (av) is required for video playback."
            return

        while not self._stop.is_set():
            try:
                with av.open(path) as container:
                    if not container.streams.video:
                        self.last_error = "Selected file contains no video stream."
                        break
                    stream = container.streams.video[0]
                    fps = float(stream.average_rate) if stream.average_rate else 30.0
                    period = 1.0 / max(1.0, fps * max(0.1, speed))
                    self.last_error = ""
                    for packet in container.demux(stream):
                        if self._stop.is_set():
                            break
                        for frame in packet.decode():
                            if self._stop.is_set():
                                break
                            started = time.monotonic()
                            sw, sh = compute_video_resize(frame.width, frame.height, width, height, fit)
                            rgb = frame.reformat(width=sw, height=sh, format="rgb24").to_ndarray()
                            fitted = apply_video_fit(rgb, width, height, fit)
                            with self._lock:
                                self._latest_frame = fitted
                            elapsed = time.monotonic() - started
                            if elapsed < period:
                                self._stop.wait(timeout=period - elapsed)
                if not loop:
                    break
            except Exception as exc:
                self.last_error = f"Video playback error: {exc}"
                break

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        p = self.parameters
        self._start_decoder(
            str(p.get("path", "")),
            width,
            height,
            str(p.get("fit", "Fill (Crop)")),
            float(p.get("speed", 1.0)),
            bool(p.get("loop", True)),
        )
        with self._lock:
            if self._latest_frame is not None and self._latest_frame.shape[:2] == (height, width):
                return self._latest_frame.copy()
        return np.zeros((height, width, 3), dtype=np.uint8)

    def cleanup(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._current_sig = None
        with self._lock:
            self._latest_frame = None
