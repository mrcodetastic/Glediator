from __future__ import annotations

import threading
from typing import Any

import numpy as np


class OutputHub:
    """Thread-safe registry of active outputs fed directly by the render loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._outputs: dict[str, Any] = {}
        self._errors: dict[str, str] = {}

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
        for output_id, output in targets:
            try:
                if hasattr(output, "submit"):
                    output.submit(frame)
                else:
                    output.send(frame)
                with self._lock:
                    self._errors.pop(output_id, None)
            except Exception as exc:
                with self._lock:
                    self._errors[output_id] = str(exc)

    def errors(self) -> dict[str, str]:
        with self._lock:
            return dict(self._errors)
