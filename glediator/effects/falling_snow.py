import numpy as np

from glediator.effects.support import ConfiguredEffect
from glediator.generators.palettes import PALETTE_NAMES, colorize


class FallingSnowEffect(ConfiguredEffect):
    name = "Falling Snow"
    description = "Multi-depth snowflakes gently drifting down across the matrix."
    category = "Generative"
    settings = {
        "speed": ("float", 8.0, 1.0, 30.0, 0.5),
        "density": ("float", 1.0, 0.2, 3.0, 0.1),
        "wind": ("float", 0.4, -2.0, 2.0, 0.1),
        "palette": ("choice", "Monochrome", PALETTE_NAMES, "", ""),
    }

    def __init__(self) -> None:
        super().__init__()
        self._flakes: np.ndarray | None = None
        self._shape: tuple[int, int] | None = None

    def _init_flakes(self, width: int, height: int) -> None:
        pool = max(48, min(320, round(width * height * 0.12)))
        self._flakes = np.column_stack((
            self._rng.random(pool),                     # base x [0, 1)
            self._rng.random(pool),                     # base y [0, 1)
            self._rng.uniform(0.35, 1.0, pool),         # depth / speed / brightness
            self._rng.uniform(0.8, 2.6, pool),          # horizontal sway frequency
            self._rng.uniform(0.0, np.pi * 2.0, pool),  # sway phase
        )).astype(np.float32)
        self._shape = (height, width)

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        p = self.parameters
        if self._flakes is None or self._shape != (height, width):
            self._init_flakes(width, height)

        assert self._flakes is not None
        density = float(p.get("density", 1.0))
        speed = float(p.get("speed", 8.0))
        wind = float(p.get("wind", 0.4))
        palette = str(p.get("palette", "Monochrome"))

        active_count = max(4, min(len(self._flakes), round(len(self._flakes) * (density / 3.0))))
        flakes = self._flakes[:active_count]
        depth = flakes[:, 2]

        # Foreground flakes fall faster and glow brighter than distant ones.
        py = np.mod(flakes[:, 1] * height + time_seconds * speed * (0.35 + 0.85 * depth), height)
        sway = np.sin(time_seconds * flakes[:, 3] + flakes[:, 4]) * (0.45 + 0.8 * depth)
        px = np.mod(flakes[:, 0] * width + time_seconds * wind * 4.5 * depth + sway, width)

        ix = np.floor(px).astype(int) % width
        iy = np.floor(py).astype(int) % height
        fx = px - np.floor(px)
        fy = py - np.floor(py)

        intensity = np.zeros((height, width), dtype=np.float32)
        color_scalar = np.zeros((height, width), dtype=np.float32)
        brightness = 0.35 + 0.65 * depth

        # Bilinear splat gives soft smooth falling snowflakes on coarse LED panels.
        for dx, wx in ((0, 1.0 - fx), (1, fx)):
            for dy, wy in ((0, 1.0 - fy), (1, fy)):
                weight = wx * wy * brightness
                tx = (ix + dx) % width
                ty = (iy + dy) % height
                np.add.at(intensity, (ty, tx), weight)
                np.maximum.at(color_scalar, (ty, tx), depth)

        intensity = np.clip(intensity, 0.0, 1.0)
        if palette == "Monochrome":
            val = np.clip(intensity * 255.0, 0, 255).astype(np.uint8)
            return np.repeat(val[..., None], 3, axis=-1)

        rgb = colorize(np.clip(0.35 + 0.65 * color_scalar, 0.0, 1.0), palette).astype(np.float32)
        return np.clip(rgb * intensity[..., None], 0, 255).astype(np.uint8)
