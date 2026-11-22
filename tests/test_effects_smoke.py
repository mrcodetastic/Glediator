from __future__ import annotations

import numpy as np
import pytest

from glediator.audio.capture import AudioCapture
from glediator.effects import create_effect, effect_names, effect_settings

SYNTHETIC_AUDIO = {
    "audio_level": 0.65,
    "audio_peak": 0.85,
    "audio_spectrum": np.linspace(0.0, 1.0, AudioCapture.SPECTRUM_BINS, dtype=np.float32),
}

EFFECTS_TO_TEST = [name for name in effect_names() if name != "Screen Capture"]


@pytest.mark.parametrize("name", EFFECTS_TO_TEST)
@pytest.mark.parametrize("size", [(8, 8), (17, 9), (64, 32), (128, 64)])
def test_effect_renders_valid_frames(name: str, size: tuple[int, int]):
    width, height = size
    effect = create_effect(name)
    try:
        effect.configure({})
        for t in (0.0, 0.5, 3.0):
            for audio in (None, SYNTHETIC_AUDIO):
                frame = effect.drawFrame(width, height, t, audio)
                assert isinstance(frame, np.ndarray)
                assert frame.shape == (height, width, 3)
                assert frame.dtype == np.uint8
    finally:
        effect.cleanup()


@pytest.mark.parametrize("name", EFFECTS_TO_TEST)
def test_effect_extreme_numeric_parameters(name: str):
    schema = effect_settings(name)
    if not schema:
        return
    min_params = {}
    max_params = {}
    for key, spec in schema.items():
        kind, _default, low, high, _step = spec
        if kind in ("int", "float"):
            min_params[key] = low
            max_params[key] = high
    if not min_params:
        return
    effect = create_effect(name)
    try:
        for params in (min_params, max_params):
            effect.configure(params)
            frame = effect.drawFrame(32, 16, 1.0, SYNTHETIC_AUDIO)
            assert frame.shape == (16, 32, 3)
            assert frame.dtype == np.uint8
    finally:
        effect.cleanup()
