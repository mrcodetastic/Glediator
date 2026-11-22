from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence

from glediator.effects.support import ConfiguredEffect


def _fit_image(img: Image.Image, width: int, height: int, fit: str, resample: Image.Resampling) -> np.ndarray:
    rgb = img.convert("RGB")
    sw, sh = rgb.size
    if sw <= 0 or sh <= 0:
        return np.zeros((height, width, 3), dtype=np.uint8)
    if fit == "Stretch":
        resized = rgb.resize((width, height), resample=resample)
        return np.asarray(resized, dtype=np.uint8).copy()
    if fit == "Center":
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(rgb, ((width - sw) // 2, (height - sh) // 2))
        return np.asarray(canvas, dtype=np.uint8).copy()

    scale_x = width / sw
    scale_y = height / sh
    scale = max(scale_x, scale_y) if fit == "Fill" else min(scale_x, scale_y)
    nw = max(1, round(sw * scale))
    nh = max(1, round(sh * scale))
    resized = rgb.resize((nw, nh), resample=resample)
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    canvas.paste(resized, ((width - nw) // 2, (height - nh) // 2))
    return np.asarray(canvas, dtype=np.uint8).copy()


class ImagePlayerEffect(ConfiguredEffect):
    name = "Image / GIF"
    description = "Display a static image or animated GIF scaled to the matrix."
    category = "Capture"
    settings = {
        "path": ("file", "", "", "", ""),
        "fit": ("choice", "Fit", ("Stretch", "Fit", "Fill", "Center"), "", ""),
        "speed": ("float", 1.0, 0.1, 4.0, 0.1),
        "loop": ("bool", True, False, True, 1),
        "smoothing": ("choice", "Bilinear", ("Nearest", "Bilinear"), "", ""),
    }

    def __init__(self) -> None:
        super().__init__()
        self._cache_sig: tuple | None = None
        self._frames: list[np.ndarray] = []
        self._durations: list[float] = []
        self._total_duration: float = 0.0

    def _load(self, path_str: str, width: int, height: int, fit: str, smoothing: str) -> None:
        sig = (path_str, width, height, fit, smoothing)
        if sig == self._cache_sig:
            return
        self._cache_sig = sig
        self._frames = []
        self._durations = []
        self._total_duration = 0.0
        if not path_str:
            self.last_error = ""
            return
        path = Path(path_str)
        if not path.is_file():
            self.last_error = f"Image file not found: {path}"
            return
        resample = Image.Resampling.NEAREST if smoothing == "Nearest" else Image.Resampling.BILINEAR
        try:
            with Image.open(path) as img:
                for frame in ImageSequence.Iterator(img):
                    dur_ms = int(frame.info.get("duration", 100) or 100)
                    dur_s = max(0.02, dur_ms / 1000.0)
                    self._frames.append(_fit_image(frame, width, height, fit, resample))
                    self._durations.append(dur_s)
            self._total_duration = sum(self._durations)
            self.last_error = ""
        except Exception as exc:
            self._frames = []
            self._durations = []
            self._total_duration = 0.0
            self.last_error = f"Failed to load image: {exc}"

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        p = self.parameters
        self._load(
            str(p.get("path", "")),
            width,
            height,
            str(p.get("fit", "Fit")),
            str(p.get("smoothing", "Bilinear")),
        )
        if not self._frames:
            return np.zeros((height, width, 3), dtype=np.uint8)
        if len(self._frames) == 1 or self._total_duration <= 0:
            return self._frames[0].copy()

        scaled_t = max(0.0, float(time_seconds) * float(p.get("speed", 1.0)))
        if p.get("loop", True):
            pos = scaled_t % self._total_duration
        else:
            if scaled_t >= self._total_duration:
                return self._frames[-1].copy()
            pos = scaled_t

        acc = 0.0
        for frame, dur in zip(self._frames, self._durations, strict=True):
            acc += dur
            if pos < acc:
                return frame.copy()
        return self._frames[-1].copy()
