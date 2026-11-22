from __future__ import annotations

import numpy as np


def new_frame(width: int, height: int) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def to_rgb888(frame: np.ndarray) -> np.ndarray:
    """Return a contiguous row-major RGB888 uint8 pixel array of shape (H, W, 3)."""
    return np.ascontiguousarray(frame, dtype=np.uint8)
