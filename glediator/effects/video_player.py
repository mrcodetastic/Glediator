from __future__ import annotations

import threading
import time

import numpy as np

from glediator.effects.support import ConfiguredEffect


class VideoPlayerEffect(ConfiguredEffect):
    name = "Video Player"
    description = "Play a local video file scaled to the matrix (requires glediator3[video])."
    category = "Capture"
    settings = {
        "path": ("file", "", "", "", ""),
        "speed": ("float", 1.0, 0.25, 4.0, 0.05),
        "loop": ("bool", True, False, True, 1),
    }

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_sig: tuple[str, int, int, float, bool] | None = None
        self._latest_frame: np.ndarray | None = None

    def _start_decoder(self, path: str, width: int, height: int, speed: float, loop: bool) -> None:
        sig = (path, width, height, speed, loop)
        if sig == self._current_sig:
            return
        self.cleanup()
        self._current_sig = sig
        if not path:
            self.last_error = ""
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._decode_loop,
            args=(path, width, height, speed, loop),
            name="GlediatorVideoDecode",
            daemon=True,
        )
        self._thread.start()

    def _decode_loop(self, path: str, width: int, height: int, speed: float, loop: bool) -> None:
        try:
            import av
        except ImportError:
            self.last_error = "Install glediator3[video] (PyAV) to play video files."
            return

        while not self._stop.is_set():
            try:
                with av.open(path) as container:
                    stream = container.streams.video[0]
                    fps = float(stream.average_rate) if stream.average_rate else 30.0
                    period = 1.0 / max(1.0, fps * max(0.1, speed))
                    self.last_error = ""
                    for packet in container.demux(stream):
                        if self._stop.is_set():
                            break
                        for frame in packet.decode():
                            if self._stop.is_set():
                                break
                            started = time.monotonic()
                            rgb = frame.reformat(width=width, height=height, format="rgb24").to_ndarray()
                            with self._lock:
                                self._latest_frame = rgb.copy()
                            elapsed = time.monotonic() - started
                            if elapsed < period:
                                self._stop.wait(timeout=period - elapsed)
                if not loop:
                    break
            except Exception as exc:
                self.last_error = f"Video playback error: {exc}"
                break

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        p = self.parameters
        self._start_decoder(
            str(p.get("path", "")),
            width,
            height,
            float(p.get("speed", 1.0)),
            bool(p.get("loop", True)),
        )
        with self._lock:
            if self._latest_frame is not None and self._latest_frame.shape[:2] == (height, width):
                return self._latest_frame.copy()
        return np.zeros((height, width, 3), dtype=np.uint8)

    def cleanup(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._current_sig = None
        with self._lock:
            self._latest_frame = None
