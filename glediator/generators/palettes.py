"""Shared, named palettes used by generator effects."""

from __future__ import annotations

import numpy as np

PALETTES: dict[str, tuple[tuple[int, int, int], ...]] = {
    "Aurora": ((0, 0, 0), (0, 38, 64), (0, 185, 130), (65, 255, 120), (210, 255, 215)),
    "Fire": ((0, 0, 0), (110, 4, 0), (245, 55, 0), (255, 175, 0), (255, 250, 195)),
    "Ocean": ((0, 0, 0), (0, 28, 110), (0, 130, 215), (0, 225, 210), (190, 255, 255)),
    "Sunset": ((0, 0, 0), (85, 0, 75), (215, 20, 75), (255, 110, 10), (255, 220, 65)),
    "Neon": ((0, 0, 0), (20, 0, 180), (0, 225, 255), (255, 0, 190), (255, 240, 40)),
    "Rainbow": ((255, 0, 0), (255, 140, 0), (255, 255, 0), (0, 230, 20), (0, 140, 255), (110, 0, 255), (255, 0, 160)),
    "Candy": ((0, 0, 0), (95, 10, 175), (240, 25, 155), (255, 120, 195), (60, 220, 255)),
    "Monochrome": ((0, 0, 0), (45, 50, 60), (140, 150, 165), (255, 255, 255)),
}

PALETTE_NAMES = tuple(PALETTES)
_CUSTOM_PALETTES: dict[str, tuple[tuple[int, int, int], ...]] = {}


def parse_hex_color(value: str) -> np.ndarray:
    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return np.array((255, 255, 255), dtype=np.float32)
    try:
        return np.array(tuple(int(text[i : i + 2], 16) for i in (0, 2, 4)), dtype=np.float32)
    except ValueError:
        return np.array((255, 255, 255), dtype=np.float32)


def set_custom_palettes(palettes: dict[str, list[str]]) -> None:
    _CUSTOM_PALETTES.clear()
    if not isinstance(palettes, dict):
        return
    for name, hex_stops in palettes.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(hex_stops, list) or len(hex_stops) < 2:
            continue
        stops = tuple(tuple(int(c) for c in parse_hex_color(h)) for h in hex_stops[:16])
        _CUSTOM_PALETTES[name.strip()] = stops  # type: ignore[assignment]


def all_palettes() -> dict[str, tuple[tuple[int, int, int], ...]]:
    merged = dict(PALETTES)
    merged.update(_CUSTOM_PALETTES)
    return merged


def palette_names() -> tuple[str, ...]:
    return tuple(all_palettes())


def colorize(values: np.ndarray, name: str = "Aurora") -> np.ndarray:
    """Interpolate a normalized scalar image through a preset or custom RGB palette."""
    merged = all_palettes()
    stops = np.asarray(merged.get(name, PALETTES["Aurora"]), dtype=np.float32)
    scalar = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    scaled = scalar * (len(stops) - 1)
    lower = np.floor(scaled).astype(np.intp)
    upper = np.minimum(lower + 1, len(stops) - 1)
    amount = (scaled - lower)[..., None]
    rgb = stops[lower] * (1.0 - amount) + stops[upper] * amount
    return np.clip(rgb, 0, 255).astype(np.uint8)


def blend_colors(a: str, b: str, amount: np.ndarray) -> np.ndarray:
    start, end = parse_hex_color(a), parse_hex_color(b)
    mix = np.clip(np.asarray(amount, dtype=np.float32), 0, 1)[..., None]
    return np.clip(start * (1 - mix) + end * mix, 0, 255).astype(np.uint8)
