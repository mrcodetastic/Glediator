import numpy as np

from glediator.effects.support import AURORA_SETTINGS, ConfiguredEffect
from glediator.generators.palettes import colorize


class PendulumWaveEffect(ConfiguredEffect):
    name = "Pendulum Wave"
    description = "Row of phase-staggered pendulum bobs forming traveling wave patterns."
    category = "Aurora"
    settings = AURORA_SETTINGS

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        speed = float(self.parameters.get("speed", 1.0))
        scale = float(self.parameters.get("scale", 1.0))
        palette = str(self.parameters.get("palette", "Aurora"))

        pendulums = max(6, min(width, round(14 * float(np.clip(scale, 0.4, 2.2)))))
        cx = np.linspace(1.5, max(1.5, width - 2.5), pendulums, dtype=np.float32)

        # Classic pendulum wave: linearly increasing frequency along the row.
        indices = np.arange(pendulums, dtype=np.float32)
        omega = (1.6 + indices * 0.22) * speed
        cy = (0.5 + 0.36 * np.cos(time_seconds * omega)) * max(1, height - 1)

        px = np.arange(width, dtype=np.float32)[None, :]
        py = np.arange(height, dtype=np.float32)[:, None]

        intensity = np.zeros((height, width), dtype=np.float32)
        color_idx = np.zeros((height, width), dtype=np.float32)
        radius_sq = max(2.2, (min(width, height) * 0.09) ** 2)

        for idx in range(pendulums):
            dist_sq = (px - cx[idx]) ** 2 + (py - cy[idx]) ** 2
            bob = np.exp(-dist_sq / radius_sq)
            # Subtle vertical rod / trail cue from top edge to bob for pendulum clarity.
            in_col = np.exp(-((px - cx[idx]) ** 2) / 0.65)
            above = np.where(py <= cy[idx], 0.14 * in_col, 0.0)
            contrib = np.maximum(bob, above)
            stronger = contrib > intensity
            intensity = np.maximum(intensity, contrib)
            color_idx = np.where(stronger, 0.18 + 0.82 * (idx / max(1, pendulums - 1)), color_idx)

        rgb = colorize(color_idx, palette).astype(np.float32)
        return np.clip(rgb * np.clip(intensity, 0.0, 1.0)[..., None], 0, 255).astype(np.uint8)
