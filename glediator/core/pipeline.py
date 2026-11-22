from __future__ import annotations

import numpy as np

MIX_MODES = (
    "Add",
    "Subtract",
    "Multiply",
    "Difference",
    "Screen",
    "Maximum",
    "Normal",
    "Lighten",
    "Darken",
    "Overlay",
    "Average",
)

LEGACY_FILTERS = ("None", "Invert", "Monochrome", "Threshold")


def apply_filter(frame: np.ndarray, filter_name: str) -> np.ndarray:
    if filter_name == "Invert":
        return 255 - frame
    if filter_name == "Monochrome":
        luminance = np.dot(frame[..., :3], [0.2126, 0.7152, 0.0722]).astype(np.uint8)
        return np.repeat(luminance[..., None], 3, axis=2)
    if filter_name == "Threshold":
        return np.where(frame >= 128, 255, 0).astype(np.uint8)
    return frame


def mix(a: np.ndarray, b: np.ndarray, mode: str = "Add", opacity: int = 100) -> np.ndarray:
    alpha = float(np.clip(opacity / 100.0, 0.0, 1.0))
    if alpha <= 0.0:
        return a.copy()

    aa = a.astype(np.int16)
    bb = b.astype(np.int16)
    if mode == "Normal":
        blended = bb
    elif mode == "Subtract":
        blended = np.maximum(aa - bb, 0)
    elif mode == "Multiply":
        blended = (aa * bb) // 255
    elif mode == "Difference":
        blended = np.abs(aa - bb)
    elif mode == "Screen":
        blended = 255 - (((255 - aa) * (255 - bb)) // 255)
    elif mode in ("Maximum", "Lighten"):
        blended = np.maximum(aa, bb)
    elif mode == "Darken":
        blended = np.minimum(aa, bb)
    elif mode == "Average":
        blended = (aa + bb) // 2
    elif mode == "Overlay":
        af = aa.astype(np.float32) / 255.0
        bf = bb.astype(np.float32) / 255.0
        out_f = np.where(af < 0.5, 2.0 * af * bf, 1.0 - 2.0 * (1.0 - af) * (1.0 - bf))
        blended = np.rint(out_f * 255.0).astype(np.int16)
    else:  # Add
        blended = aa + bb

    blended = np.clip(blended, 0, 255)
    if alpha < 1.0:
        out = aa.astype(np.float32) * (1.0 - alpha) + blended.astype(np.float32) * alpha
        return np.clip(np.rint(out), 0, 255).astype(np.uint8)
    return blended.astype(np.uint8)
