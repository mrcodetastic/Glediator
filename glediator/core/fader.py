from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRANSITION_KINDS = (
    "crossfade",
    "cut",
    "wipe_left",
    "wipe_right",
    "wipe_up",
    "wipe_down",
    "dissolve",
    "luma",
)

EASINGS = ("linear", "ease_in_out")

_DISSOLVE_MASK_CACHE: dict[tuple[int, int], np.ndarray] = {}


@dataclass
class Transition:
    kind: str
    start_value: float
    target: float
    duration: float
    started_at: float
    easing: str = "ease_in_out"

    def progress(self, now: float) -> tuple[float, bool]:
        if self.duration <= 0:
            return self.target, True
        t = float(np.clip((now - self.started_at) / self.duration, 0.0, 1.0))
        eased = t * t * (3.0 - 2.0 * t) if self.easing == "ease_in_out" else t
        value = self.start_value + (self.target - self.start_value) * eased
        return float(np.clip(value, 0.0, 1.0)), t >= 1.0


def _dissolve_mask(height: int, width: int) -> np.ndarray:
    key = (height, width)
    cached = _DISSOLVE_MASK_CACHE.get(key)
    if cached is not None:
        return cached
    rng = np.random.default_rng(1337)
    mask = rng.random((height, width), dtype=np.float32)
    _DISSOLVE_MASK_CACHE[key] = mask
    return mask


def crossfade(left: np.ndarray, right: np.ndarray, amount: float, kind: str = "crossfade") -> np.ndarray:
    """Blend two RGB frames; amount 0 selects left and 1 selects right."""
    alpha = float(np.clip(amount, 0.0, 1.0))
    if alpha <= 0.0:
        return left.copy()
    if alpha >= 1.0:
        return right.copy()

    if kind == "cut":
        return right.copy() if alpha >= 0.5 else left.copy()

    h, w = left.shape[:2]
    if kind == "wipe_left":
        cols = int(np.floor(alpha * w))
        out = left.copy()
        if cols > 0:
            out[:, :cols] = right[:, :cols]
        return out
    if kind == "wipe_right":
        cols = int(np.floor(alpha * w))
        out = left.copy()
        if cols > 0:
            out[:, w - cols :] = right[:, w - cols :]
        return out
    if kind == "wipe_up":
        rows = int(np.floor(alpha * h))
        out = left.copy()
        if rows > 0:
            out[:rows, :] = right[:rows, :]
        return out
    if kind == "wipe_down":
        rows = int(np.floor(alpha * h))
        out = left.copy()
        if rows > 0:
            out[h - rows :, :] = right[h - rows :, :]
        return out
    if kind == "dissolve":
        mask = _dissolve_mask(h, w) < alpha
        return np.where(mask[..., None], right, left)
    if kind == "luma":
        luma = (
            0.2126 * left[..., 0].astype(np.float32)
            + 0.7152 * left[..., 1].astype(np.float32)
            + 0.0722 * left[..., 2].astype(np.float32)
        ) / 255.0
        mask = luma <= alpha
        return np.where(mask[..., None], right, left)

    return np.rint(left.astype(np.float32) * (1.0 - alpha) + right.astype(np.float32) * alpha).astype(np.uint8)
