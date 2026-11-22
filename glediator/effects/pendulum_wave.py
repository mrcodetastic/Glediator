import numpy as np

from glediator.effects.support import AURORA_SETTINGS, ConfiguredEffect, coordinates
from glediator.generators.palettes import colorize


class PendulumWaveEffect(ConfiguredEffect):
    name = "Pendulum Wave"
    description = "A set of phase-shifted pendulum waves."
    category = "Aurora"
    settings = AURORA_SETTINGS

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        x, y = coordinates(width, height)
        wave = np.zeros((height, width), dtype=np.float32)
        for i in range(14):
            phase = time_seconds * self.parameters["speed"] * (0.5 + i * 0.035) + i * 0.48
            center = 0.5 + 0.42 * np.sin(x * np.pi * 2 + phase)
            wave = np.maximum(wave, np.exp(-((y - center) ** 2) * height * 5))
        return colorize(wave, self.parameters["palette"])
