import numpy as np

from glediator.effects.support import ConfiguredEffect
from glediator.generators.palettes import PALETTE_NAMES, colorize


class FireEffect(ConfiguredEffect):
    name = "Fire"
    description = "Upward-burning procedural flame simulation colored with the active palette."
    category = "Generative"
    settings = {
        "cooling": ("float", 1.0, 0.3, 2.0, 0.1),
        "sparks": ("float", 0.12, 0.0, 0.5, 0.01),
        "palette": ("choice", "Fire", PALETTE_NAMES, "", ""),
    }

    def __init__(self) -> None:
        super().__init__()
        self._heat: np.ndarray | None = None
        self._last_time: float | None = None
        self._sim_time = 0.0

    def _step_fire(self, height: int, width: int, cooling: float, sparks: float) -> None:
        assert self._heat is not None
        heat = self._heat
        h, w = height, width
        self._sim_time += 1.0 / 32.0

        # Base ember bed along the bottom row fluctuates organically across width.
        x = np.linspace(0.0, 1.0, w, dtype=np.float32)
        bed = (
            0.78
            + 0.14 * np.sin(x * 13.0 + self._sim_time * 4.2)
            + 0.08 * np.cos(x * 29.0 - self._sim_time * 6.5)
            + self._rng.uniform(-0.08, 0.14, size=w).astype(np.float32)
        )
        heat[h - 1, :] = np.clip(bed, 0.45, 1.0)
        if h > 1:
            heat[h - 2, :] = np.clip(
                heat[h - 2, :] * 0.45 + heat[h - 1, :] * 0.55 + self._rng.uniform(-0.05, 0.08, size=w),
                0.25,
                1.0,
            )

        # Occasional bright hot sparks bursting upward from the lower fuel zone.
        if sparks > 0 and h > 2:
            spark_prob = min(0.85, sparks * 1.1)
            mask = self._rng.random(w) < spark_prob
            if np.any(mask):
                spark_row = max(1, h - 1 - int(self._rng.integers(1, min(4, h))))
                heat[spark_row, mask] = np.maximum(
                    heat[spark_row, mask],
                    self._rng.uniform(0.75, 1.0, size=int(np.count_nonzero(mask))).astype(np.float32),
                )

        # Propagate heat upward (row 0 is top, row h-1 is bottom) with lateral flicker.
        if h > 2:
            below1 = heat[1 : h - 1, :] if h > 3 else heat[1:h, :]
            src_center = heat[2:h, :]
            # Random wind jitter left/right without wrapping edges harshly.
            shift_l = np.pad(src_center[:, 1:], ((0, 0), (0, 1)), mode="edge")
            shift_r = np.pad(src_center[:, :-1], ((0, 0), (1, 0)), mode="edge")
            near = heat[1 : h - 1, :]
            convected = 0.48 * src_center + 0.18 * shift_l + 0.18 * shift_r + 0.16 * near

            # Stronger cooling higher up creates flickering tapered flame tongues.
            row_frac = np.linspace(1.0, 0.25, h - 2, dtype=np.float32)[:, None]
            cool_step = (0.045 + 0.11 * row_frac) * cooling * (16.0 / max(12, h))
            jitter = self._rng.uniform(0.35, 1.65, size=(h - 2, w)).astype(np.float32)
            heat[: h - 2, :] = np.clip(convected - cool_step * jitter, 0.0, 1.0)
            _ = below1  # keep reference clear

        if h > 1:
            # Soft vertical smoothing on top rows keeps transitions organic.
            heat[0, :] = np.clip(heat[0, :] * 0.7 + heat[1, :] * 0.3 - 0.04 * cooling, 0.0, 1.0)

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        p = self.parameters
        cooling = float(p.get("cooling", 1.0))
        sparks = float(p.get("sparks", 0.12))
        palette = str(p.get("palette", "Fire"))

        if self._heat is None or self._heat.shape != (height, width):
            self._heat = np.zeros((height, width), dtype=np.float32)
            self._last_time = float(time_seconds)
            # Pre-warm so frame 0 opens with a full upright flame rather than empty rows.
            for _ in range(max(24, height)):
                self._step_fire(height, width, cooling, sparks)
        else:
            prev = float(time_seconds) if self._last_time is None else self._last_time
            dt = max(0.0, float(time_seconds) - prev)
            self._last_time = float(time_seconds)
            steps = max(1, min(4, round(dt * 32.0))) if dt > 0.001 else 1
            for _ in range(steps):
                self._step_fire(height, width, cooling, sparks)

        rgb = colorize(self._heat, palette).astype(np.float32)
        fade = np.clip(self._heat * 3.5, 0.0, 1.0)[..., None]
        return np.clip(rgb * fade, 0, 255).astype(np.uint8)
