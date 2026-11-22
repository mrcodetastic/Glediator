import numpy as np

from glediator.effects.support import AURORA_SETTINGS, ConfiguredEffect, aurora_coordinates
from glediator.generators.palettes import colorize


class SpinEffect(ConfiguredEffect):
    name = "Spin"
    description = "A rotating radial interference pattern."
    category = "Aurora"
    settings = AURORA_SETTINGS

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        _, _, _, _, _, _, radius, angle = aurora_coordinates(width, height)
        value = .5 + .5 * np.sin(angle * 8 + radius * 15 - time_seconds * self.parameters["speed"] * 3)
        return colorize(value, self.parameters["palette"])
