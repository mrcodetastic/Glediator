from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from glediator.audio.capture import AudioCapture
from glediator.core.config import EngineConfig
from glediator.core.fader import crossfade
from glediator.core.scene import Scene
from glediator.output.hub import OutputHub


@dataclass
class EngineStatus:
    fps: float
    frame_count: int
    layer_errors: dict[tuple[str, int], str] = field(default_factory=dict)
    audio_error: str = ""
    output_errors: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)


class RenderEngine:
    """Threaded render loop. Public mutations are protected by one small lock."""

    def __init__(self, config: EngineConfig) -> None:
        config.validate()
        self.config = config
        self.left_scene = Scene("Live A", config.width, config.height)
        self.right_scene = Scene("Live B", config.width, config.height)
        self.fader = 0.5
        self.running = False
        self._lock = threading.RLock()
        self._latest: dict[str, np.ndarray] = {}
        self._thread: threading.Thread | None = None
        self.frame_count = 0
        self.fps = 0.0
        self._start_time = time.perf_counter()
        self._last_fps_time = self._start_time
        self._fps_frames = 0
        self.audio_capture = AudioCapture()
        self._audio_active = False
        self.outputs = OutputHub()
        self.outputs.set_processing(
            config.master.get("brightness", 1.0),
            config.master.get("gamma", 1.0),
        )
        if config.live_state:
            self.restore_state(config.live_state)

    def set_master(self, brightness: float | None = None, gamma: float | None = None) -> None:
        with self._lock:
            cur_b, cur_g = self.outputs.processing_settings()
            new_b = cur_b if brightness is None else max(0.0, min(1.0, float(brightness)))
            new_g = cur_g if gamma is None else max(0.1, min(4.0, float(gamma)))
            self.config.master["brightness"] = new_b
            self.config.master["gamma"] = new_g
        self.outputs.set_processing(new_b, new_g)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, name="GlediatorRender", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self.audio_capture.stop()
        self._audio_active = False
        for output in self.outputs.clear():
            try:
                output.stop()
            except Exception:
                pass
        with self._lock:
            self.left_scene.close()
            self.right_scene.close()

    def set_generator(self, side: str, layer: int, name: str) -> None:
        with self._lock:
            self._scene(side).set_generator(layer, name)

    def add_layer(self, side: str, name: str) -> int | None:
        with self._lock:
            return self._scene(side).add_layer(name)

    def remove_layer(self, side: str, layer: int) -> None:
        with self._lock:
            self._scene(side).remove_layer(layer)

    def set_layer_enabled(self, side: str, layer: int, enabled: bool) -> None:
        with self._lock:
            target = self._scene(side).layers[layer]
            if target.configured:
                target.enabled = bool(enabled)

    def move_layer(self, side: str, source: int, destination: int) -> None:
        with self._lock:
            self._scene(side).move_layer(source, destination)

    def set_fader(self, amount: float) -> None:
        with self._lock:
            self.fader = min(1.0, max(0.0, float(amount)))

    def set_matrix_size(self, width: int, height: int) -> None:
        width, height = max(8, min(512, int(width))), max(8, min(512, int(height)))
        with self._lock:
            self.config.width, self.config.height = width, height
            self.left_scene.resize(width, height)
            self.right_scene.resize(width, height)

    def set_layer_options(
        self,
        side: str,
        layer: int,
        brightness: int | None = None,
        filter_name: str | None = None,
        mix_mode: str | None = None,
    ) -> None:
        with self._lock:
            item = self._scene(side).layers[layer]
            if brightness is not None:
                item.brightness = min(100, max(0, int(brightness)))
            if filter_name is not None:
                item.filter_name = filter_name
            if mix_mode is not None:
                item.mix_mode = mix_mode

    def set_generator_parameters(self, side: str, layer: int, parameters: dict) -> None:
        from glediator.effects import sanitize_effect_parameters

        with self._lock:
            scene = self._scene(side)
            target = scene.layers[layer]
            target.parameters = sanitize_effect_parameters(target.generator_name, parameters)
            scene._generators[layer].configure(target.parameters)

    def export_state(self) -> dict:
        with self._lock:
            return {
                "left": self.left_scene.to_dict(),
                "right": self.right_scene.to_dict(),
                "fader": self.fader,
                "width": self.config.width,
                "height": self.config.height,
            }

    def restore_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return
        with self._lock:
            width = max(8, min(512, int(state.get("width", self.config.width))))
            height = max(8, min(512, int(state.get("height", self.config.height))))
            self.config.width, self.config.height = width, height
            self.left_scene.resize(width, height)
            self.right_scene.resize(width, height)
            if isinstance(state.get("left"), dict):
                self.left_scene.restore(state["left"])
            if isinstance(state.get("right"), dict):
                self.right_scene.restore(state["right"])
            self.fader = min(1.0, max(0.0, float(state.get("fader", 0.5))))

    def scene_snapshot(self, side: str) -> dict:
        with self._lock:
            return copy.deepcopy(self._scene(side).to_dict())

    def status(self) -> EngineStatus:
        with self._lock:
            fps = self.fps
            frame_count = self.frame_count
            layer_errors: dict[tuple[str, int], str] = {}
            for side, scene in (("left", self.left_scene), ("right", self.right_scene)):
                for index, (layer, generator) in enumerate(zip(scene.layers, scene._generators, strict=True)):
                    if layer.enabled:
                        err = getattr(generator, "last_error", "")
                        if err:
                            layer_errors[(side, index)] = err
        output_statuses = {}
        for output_id, output in self.outputs.items():
            if hasattr(output, "status"):
                output_statuses[output_id] = output.status()
        return EngineStatus(
            fps=fps,
            frame_count=frame_count,
            layer_errors=layer_errors,
            audio_error=self.audio_capture.last_error,
            output_errors=self.outputs.errors(),
            outputs=output_statuses,
        )

    def _scene(self, side: str) -> Scene:
        if side.lower() == "left":
            return self.left_scene
        if side.lower() == "right":
            return self.right_scene
        raise ValueError("side must be 'left' or 'right'")

    def snapshot(self) -> dict[str, np.ndarray]:
        with self._lock:
            return {name: frame.copy() for name, frame in self._latest.items()}

    def _audio_requirements(self) -> tuple[bool, str, bool, float]:
        audio_layers = [
            layer
            for scene in (self.left_scene, self.right_scene)
            for layer in scene.layers
            if layer.configured
            and layer.enabled
            and layer.generator_name in ("VU Meter", "Simple Spectrum", "Spectrum Analyser")
        ]
        if not audio_layers:
            return False, "System Output", False, 2.5
        source = audio_layers[0].parameters.get("source", "System Output")
        auto_layers = [
            layer
            for layer in audio_layers
            if layer.generator_name in ("VU Meter", "Spectrum Analyser")
            and layer.parameters.get("auto_sensitivity", "Off") == "On"
        ]
        sensitivity = max((float(layer.parameters.get("sensitivity", 2.5)) for layer in auto_layers), default=2.5)
        return True, source, bool(auto_layers), sensitivity

    def _run(self) -> None:
        next_deadline = time.perf_counter()
        while self.running:
            period = 1.0 / max(1, self.config.fps)
            started = time.perf_counter()
            with self._lock:
                want_audio, source, auto_enabled, sensitivity = self._audio_requirements()

            if want_audio:
                self.audio_capture.set_source(source)
                self.audio_capture.set_auto_sensitivity(auto_enabled, sensitivity)
                self.audio_capture.start()
                self._audio_active = True
            elif self._audio_active:
                self.audio_capture.set_auto_sensitivity(False)
                self.audio_capture.stop()
                self._audio_active = False

            audio_state = self.audio_capture.snapshot() if want_audio else None

            with self._lock:
                t = started - self._start_time
                left = self.left_scene.render(t, audio_state)
                right = self.right_scene.render(t, audio_state)
                mixed = crossfade(left, right, self.fader)
                self._latest = {"left": left, "right": right, "mixed": mixed}
                self.frame_count += 1
                self._fps_frames += 1
                elapsed_fps = started - self._last_fps_time
                if elapsed_fps >= 1.0:
                    self.fps = self._fps_frames / elapsed_fps
                    self._last_fps_time = started
                    self._fps_frames = 0

            self.outputs.submit(mixed)

            next_deadline += period
            now = time.perf_counter()
            if now > next_deadline + period:
                next_deadline = now
            time.sleep(max(0.0, next_deadline - now))
