from __future__ import annotations

import threading
import time

import numpy as np

from glediator.effects.support import ConfiguredEffect


class WebcamEffect(ConfiguredEffect):
    name = "Webcam"
    description = "Live webcam feed scaled to the matrix (requires glediator3[camera])."
    category = "Capture"
    settings = {
        "device": ("int", 0, 0, 16, 1),
        "mirror": ("bool", True, False, True, 1),
        "capture_fps": ("int", 15, 1, 30, 1),
    }

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sig: tuple[int, int, int, bool, int] | None = None
        self._latest: np.ndarray | None = None

    def _ensure_running(self, device: int, width: int, height: int, mirror: bool, fps: int) -> None:
        sig = (device, width, height, mirror, fps)
        if sig == self._sig:
            return
        self.cleanup()
        self._sig = sig
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            args=(device, width, height, mirror, fps),
            name="GlediatorWebcam",
            daemon=True,
        )
        self._thread.start()

    def _capture_loop(self, device: int, width: int, height: int, mirror: bool, fps: int) -> None:
        try:
            import cv2
        except ImportError:
            self.last_error = "Install glediator3[camera] (OpenCV) to enable Webcam input."
            return

        cap = cv2.VideoCapture(device)
        if not cap.isOpened():
            self.last_error = f"Unable to open camera device {device}."
            cap.release()
            return
        self.last_error = ""
        period = 1.0 / max(1, fps)
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                ok, bgr = cap.read()
                if not ok:
                    self.last_error = f"Camera {device} stopped returning frames."
                    break
                if mirror:
                    bgr = cv2.flip(bgr, 1)
                resized = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_LINEAR)
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                with self._lock:
                    self._latest = np.ascontiguousarray(rgb, dtype=np.uint8)
                elapsed = time.monotonic() - started
                if elapsed < period:
                    self._stop.wait(timeout=period - elapsed)
        finally:
            cap.release()

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        p = self.parameters
        self._ensure_running(
            int(p.get("device", 0)),
            width,
            height,
            bool(p.get("mirror", True)),
            int(p.get("capture_fps", 15)),
        )
        with self._lock:
            if self._latest is not None and self._latest.shape[:2] == (height, width):
                return self._latest.copy()
        return np.zeros((height, width, 3), dtype=np.uint8)

    def cleanup(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._sig = None
        with self._lock:
            self._latest = None
