import numpy as np

from glediator.effects.support import ConfiguredEffect
from glediator.generators.palettes import PALETTE_NAMES, colorize


class StarfieldEffect(ConfiguredEffect):
    name = "Starfield"
    description = "Classic 3D perspective starfield flying outward from the center."
    category = "Generative"
    settings = {
        "speed": ("float", 1.0, 0.1, 8.0, 0.1),
        "stars": ("int", 65, 15, 250, 5),
        "trails": ("float", 1.0, 0.0, 2.5, 0.1),
        "palette": ("choice", "Monochrome", PALETTE_NAMES, "", ""),
    }

    def __init__(self) -> None:
        super().__init__()
        self._x: np.ndarray | None = None
        self._y: np.ndarray | None = None
        self._z: np.ndarray | None = None
        self._pz: np.ndarray | None = None
        self._last_time: float | None = None

    def _spawn_xy(self, count: int) -> tuple[np.ndarray, np.ndarray]:
        angle = self._rng.uniform(0.0, np.pi * 2.0, count).astype(np.float32)
        radius = self._rng.uniform(0.06, 0.95, count).astype(np.float32)
        return np.cos(angle) * radius, np.sin(angle) * radius

    def _init_stars(self, count: int) -> None:
        self._x, self._y = self._spawn_xy(count)
        self._z = self._rng.uniform(0.08, 1.0, count).astype(np.float32)
        self._pz = self._z.copy()

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        p = self.parameters
        count = max(10, int(p.get("stars", 85)))
        speed = float(p.get("speed", 1.0))
        trails = float(p.get("trails", 1.0))
        palette = str(p.get("palette", "Monochrome"))

        if self._x is None or len(self._x) != count:
            self._init_stars(count)
            self._last_time = float(time_seconds)

        assert self._x is not None and self._y is not None and self._z is not None and self._pz is not None
        now = float(time_seconds)
        dt = max(0.0, min(0.1, now - (self._last_time if self._last_time is not None else now)))
        self._last_time = now

        # True 3D depth travel toward the camera -> stars accelerate radially via 1/z.
        self._pz[:] = self._z
        step = max(0.002, dt * speed * 0.45) if dt > 0 else 0.008 * speed
        self._z -= step

        cx = (width - 1) * 0.5
        cy = (height - 1) * 0.5
        scale_x = width * 0.5
        scale_y = height * 0.5

        sx = cx + (self._x / np.maximum(self._z, 0.02)) * scale_x
        sy = cy + (self._y / np.maximum(self._z, 0.02)) * scale_y

        respawn = (self._z <= 0.05) | (sx < 0) | (sx >= width) | (sy < 0) | (sy >= height)
        if np.any(respawn):
            rcount = int(np.count_nonzero(respawn))
            nx, ny = self._spawn_xy(rcount)
            self._x[respawn] = nx
            self._y[respawn] = ny
            self._z[respawn] = 1.0
            self._pz[respawn] = 1.0
            sx[respawn] = cx + nx * scale_x
            sy[respawn] = cy + ny * scale_y

        prev_z = np.minimum(1.0, self._z + step * (1.2 + trails * 1.4))
        psx = cx + (self._x / prev_z) * scale_x
        psy = cy + (self._y / prev_z) * scale_y

        brightness = np.clip((1.0 - self._z) ** 1.35 * 1.15, 0.14, 1.0)
        canvas = np.zeros((height, width), dtype=np.float32)

        # Draw crisp star points and short radial warp trails for foreground stars.
        steps = 4 if trails > 0.05 else 1
        for k in range(steps):
            frac = k / max(1, steps - 1) if steps > 1 else 1.0
            # Distant stars stay sharp single pixels; closer stars elongate subtly.
            trail_frac = np.where((self._z < 0.55) & (trails > 0.05), frac, 1.0)
            lx = np.rint(psx + (sx - psx) * trail_frac).astype(int)
            ly = np.rint(psy + (sy - psy) * trail_frac).astype(int)
            fade = brightness * (0.35 + 0.65 * trail_frac)
            valid = (lx >= 0) & (lx < width) & (ly >= 0) & (ly < height)
            np.maximum.at(canvas, (ly[valid], lx[valid]), fade[valid])

        if palette == "Monochrome":
            val = np.clip(canvas * 255.0, 0, 255).astype(np.uint8)
            return np.repeat(val[..., None], 3, axis=-1)

        rgb = colorize(np.clip(canvas, 0.0, 1.0), palette).astype(np.float32)
        return np.clip(rgb * canvas[..., None], 0, 255).astype(np.uint8)
