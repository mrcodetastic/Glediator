import numpy as np

from glediator.effects.support import AURORA_SETTINGS, ConfiguredEffect, aurora_coordinates
from glediator.generators.palettes import colorize


class SpiralEffect(ConfiguredEffect):
    name = "Spiral"
    description = "An animated spiral field."
    category = "Aurora"
    settings = AURORA_SETTINGS

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        _, _, _, _, _, _, radius, angle = aurora_coordinates(width, height)
        value = .5 + .5 * np.sin(angle * 4 - radius * 22 + time_seconds * self.parameters["speed"] * 2)
        return colorize(value, self.parameters["palette"])
