from __future__ import annotations

import threading
from typing import Any

import numpy as np


class OutputHub:
    """Thread-safe output distributor with master brightness and gamma LUT processing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._outputs: dict[str, Any] = {}
        self._errors: dict[str, str] = {}
        self._brightness: float = 1.0
        self._gamma: float = 1.0
        self._lut_params: tuple[float, float] | None = None
        self._lut: np.ndarray | None = None

    def set_processing(self, brightness: float = 1.0, gamma: float = 1.0) -> None:
        clamped_b = max(0.0, min(1.0, float(brightness)))
        clamped_g = max(0.1, min(4.0, float(gamma)))
        with self._lock:
            self._brightness = clamped_b
            self._gamma = clamped_g
            self._lut_params = None

    def processing_settings(self) -> tuple[float, float]:
        with self._lock:
            return self._brightness, self._gamma

    def _get_lut_locked(self) -> np.ndarray | None:
        if self._brightness == 1.0 and self._gamma == 1.0:
            return None
        key = (self._brightness, self._gamma)
        if self._lut_params != key or self._lut is None:
            ramp = np.arange(256, dtype=np.float32) / 255.0
            scaled = np.power(ramp, self._gamma) * (255.0 * self._brightness)
            self._lut = np.clip(np.rint(scaled), 0, 255).astype(np.uint8)
            self._lut_params = key
        return self._lut

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        with self._lock:
            lut = self._get_lut_locked()
        if lut is None:
            return frame
        return lut[frame]

    def add(self, output_id: str, output: Any) -> None:
        with self._lock:
            self._outputs[output_id] = output
            self._errors.pop(output_id, None)

    def remove(self, output_id: str) -> Any | None:
        with self._lock:
            self._errors.pop(output_id, None)
            return self._outputs.pop(output_id, None)

    def clear(self) -> list[Any]:
        with self._lock:
            items = list(self._outputs.values())
            self._outputs.clear()
            self._errors.clear()
            return items

    def get(self, output_id: str) -> Any | None:
        with self._lock:
            return self._outputs.get(output_id)

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return list(self._outputs.items())

    def submit(self, frame: np.ndarray) -> None:
        with self._lock:
            targets = list(self._outputs.items())
            lut = self._get_lut_locked()
        processed = lut[frame] if lut is not None and targets else frame
        for output_id, output in targets:
            try:
                if hasattr(output, "submit"):
                    output.submit(processed)
                else:
                    output.send(processed)
                with self._lock:
                    self._errors.pop(output_id, None)
            except Exception as exc:
                with self._lock:
                    self._errors[output_id] = str(exc)

    def errors(self) -> dict[str, str]:
        with self._lock:
            return dict(self._errors)
