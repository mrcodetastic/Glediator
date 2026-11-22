import numpy as np

from glediator.effects.support import AURORA_SETTINGS, ConfiguredEffect, aurora_coordinates
from glediator.generators.palettes import colorize


class SimplexNoiseEffect(ConfiguredEffect):
    name = "Simplex Noise"
    description = "A smoothly animated noise field."
    category = "Aurora"
    settings = AURORA_SETTINGS

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        _, _, _, _, nx, ny, _, _ = aurora_coordinates(width, height)
        spd = self.parameters["speed"]
        noise = np.sin(nx * 3 + time_seconds * spd) * np.sin(ny * 4 - time_seconds * spd * 0.7)
        noise += .45 * np.sin((nx + ny) * 9 + time_seconds * .23) + .2 * np.cos(nx * 17 - ny * 13)
        return colorize((noise + 1.65) / 3.3, self.parameters["palette"])
