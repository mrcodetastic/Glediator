import numpy as np
from PIL import Image

from glediator.effects.support import AURORA_SETTINGS, ConfiguredEffect, coordinates
from glediator.generators.palettes import colorize


class NoiseSmearingEffect(ConfiguredEffect):
    name = "Noise Smearing"
    description = "Animated noise smeared smoothly across the matrix."
    category = "Aurora"
    settings = AURORA_SETTINGS

    def __init__(self) -> None:
        super().__init__()
        self._smear: np.ndarray | None = None
        self._last_time: float | None = None

    def _smooth_noise(self, width: int, height: int, scale: float) -> np.ndarray:
        coarse_w = max(3, min(width, round(max(2.0, width / (10.0 / max(0.25, scale))))))
        coarse_h = max(3, min(height, round(max(2.0, height / (8.0 / max(0.25, scale))))))
        raw = self._rng.random((coarse_h, coarse_w), dtype=np.float32)
        img = Image.fromarray(np.clip(raw * 255.0, 0, 255).astype(np.uint8), mode="L")
        upscaled = img.resize((width, height), resample=Image.Resampling.BILINEAR)
        return np.asarray(upscaled, dtype=np.float32) / 255.0

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        speed = float(self.parameters.get("speed", 1.0))
        scale = float(self.parameters.get("scale", 1.0))
        palette = str(self.parameters.get("palette", "Aurora"))

        if self._smear is None or self._smear.shape != (height, width):
            self._smear = self._smooth_noise(width, height, scale)
            self._last_time = float(time_seconds)

        dt = max(
            1.0 / 60.0,
            min(0.2, float(time_seconds) - (self._last_time if self._last_time is not None else float(time_seconds))),
        )
        self._last_time = float(time_seconds)

        # Flow field coordinates move proportional to speed and warp proportional to scale.
        x, y = coordinates(width, height)
        vx = np.cos(y * np.pi * (1.2 + scale * 0.6) + time_seconds * speed * 0.9) * speed * (width * dt * 0.45)
        vy = np.sin(x * np.pi * (1.2 + scale * 0.6) - time_seconds * speed * 0.7) * speed * (height * dt * 0.45)

        px = np.broadcast_to(np.arange(width, dtype=np.float32)[None, :], (height, width)) - vx
        py = np.broadcast_to(np.arange(height, dtype=np.float32)[:, None], (height, width)) - vy

        x0 = np.floor(px).astype(int) % width
        y0 = np.floor(py).astype(int) % height
        x1 = (x0 + 1) % width
        y1 = (y0 + 1) % height
        fx = px - np.floor(px)
        fy = py - np.floor(py)

        s = self._smear
        advected = (
            s[y0, x0] * (1.0 - fx) * (1.0 - fy)
            + s[y0, x1] * fx * (1.0 - fy)
            + s[y1, x0] * (1.0 - fx) * fy
            + s[y1, x1] * fx * fy
        )

        fresh = self._smooth_noise(width, height, scale)
        inject = min(0.35, 0.05 + 0.08 * dt * speed * 4.0)
        self._smear = np.clip(advected * (1.0 - inject) + fresh * inject, 0.0, 1.0).astype(np.float32)

        lo = float(np.percentile(self._smear, 5))
        hi = float(np.percentile(self._smear, 95))
        if hi - lo > 1e-3:
            self._smear = np.clip((self._smear - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)
        return colorize(self._smear, palette)
