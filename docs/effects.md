# Writing Custom Effects for Glediator

Place `.py` files in `~/.glediator/effects/` (or any directory listed in `GLEDIATOR_EFFECTS_PATH`) and restart Glediator. Each concrete subclass of `ConfiguredEffect` with a unique `name` is automatically discovered and added to the **Add effect** picker.

## Minimal template

```python
import numpy as np

from glediator.effects.support import ConfiguredEffect, coordinates
from glediator.generators.palettes import colorize, palette_names


class DiagonalPulseEffect(ConfiguredEffect):
    name = "Diagonal Pulse"
    description = "Moving diagonal bands colored with any palette."
    category = "Generative"
    settings = {
        "speed": ("float", 1.5, 0.1, 8.0, 0.1),
        "frequency": ("float", 3.0, 0.5, 12.0, 0.5),
        "palette": ("choice", "Aurora", palette_names, "", ""),
        "invert": ("bool", False, False, True, 1),
    }

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        x, y = coordinates(width, height)
        p = self.parameters
        phase = (x + y) * p["frequency"] - time_seconds * p["speed"]
        val = 0.5 + 0.5 * np.sin(phase * np.pi * 2.0)
        if p.get("invert"):
            val = 1.0 - val
        return colorize(val, p["palette"])
```

## Rules

1. Never import `PySide6` inside an effect module.
2. `drawFrame(width, height, time_seconds, audio_state)` must always return an `np.ndarray` of `dtype=np.uint8` and shape `(height, width, 3)` in RGB order.
3. Setting tuple schema: `(kind, default, min_or_choices, max, step)` where `kind` is one of `int`, `float`, `bool`, `choice`, `str`, `color`, `font`, `file`.
4. Release any threads, files, or hardware handles inside `cleanup()`.
