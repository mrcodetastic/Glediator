from __future__ import annotations

import statistics
import time
from collections import deque


class TapTempo:
    """Median-interval tap-tempo estimator with idle reset."""

    IDLE_RESET_SECONDS = 2.0

    def __init__(self, max_taps: int = 8, clock=time.monotonic) -> None:
        self._clock = clock
        self._taps: deque[float] = deque(maxlen=max(3, max_taps))
        self.bpm: float = 0.0

    def tap(self) -> float:
        now = self._clock()
        if self._taps and (now - self._taps[-1]) > self.IDLE_RESET_SECONDS:
            self._taps.clear()
            self.bpm = 0.0
        self._taps.append(now)
        if len(self._taps) >= 2:
            intervals = [self._taps[i] - self._taps[i - 1] for i in range(1, len(self._taps))]
            median_dt = statistics.median(intervals)
            if median_dt > 0.05:
                self.bpm = max(30.0, min(300.0, 60.0 / median_dt))
        return self.bpm

    def reset(self) -> None:
        self._taps.clear()
        self.bpm = 0.0
