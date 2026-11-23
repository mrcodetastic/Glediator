from __future__ import annotations

import copy
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from glediator.audio.capture import AudioCapture
from glediator.core.config import EngineConfig
from glediator.core.fader import TRANSITION_KINDS, Transition, crossfade
from glediator.core.frame import new_frame
from glediator.core.scene import Scene, sanitize_modulations
from glediator.core.sequencer import PlaylistSequencer, SequencerStatus
from glediator.core.tempo import TapTempo
from glediator.output.hub import OutputHub


@dataclass
class EngineStatus:
    fps: float
    frame_count: int
    fader: float = 0.5
    transition_active: bool = False
    transition_kind: str = "crossfade"
    loop_fader: bool = False
    loop_hold_s: float = 5.0
    blackout: bool = False
    freeze: bool = False
    speed: float = 1.0
    bpm: float = 0.0
    bpm_source: str = "off"
    frame_time_ms: float = 0.0
    dropped_frames: int = 0
    layer_times_ms: dict[tuple[str, int], float] = field(default_factory=dict)
    layer_errors: dict[tuple[str, int], str] = field(default_factory=dict)
    audio_error: str = ""
    output_errors: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    sequencer: SequencerStatus = field(default_factory=SequencerStatus)


class RenderEngine:
    """Threaded render loop. Public mutations are protected by one small lock."""

    def __init__(self, config: EngineConfig, clock=time.perf_counter) -> None:
        config.validate()
        self.config = config
        self._clock = clock
        self.left_scene = Scene("Live A", config.width, config.height)
        self.right_scene = Scene("Live B", config.width, config.height)
        self.fader = 0.5
        self.transition_kind = "crossfade"
        self._transition: Transition | None = None
        self.loop_fader = False
        self.loop_hold_s = 5.0
        self.loop_duration_s = 2.0
        self._loop_next_at: float | None = None
        self.blackout = False
        self.freeze = False
        self.speed = 1.0
        self.running = False
        self._lock = threading.RLock()
        self._latest: dict[str, np.ndarray] = {}
        self._thread: threading.Thread | None = None
        self.frame_count = 0
        self.fps = 0.0
        self._start_time = self._clock()
        self._last_tick = self._start_time
        self._scene_time = 0.0
        self._lfo_phase = 0.0
        self._last_fps_time = self._start_time
        self._fps_frames = 0
        self._frame_time_ms = 0.0
        self._dropped_frames = 0
        self._detected_bpm = 0.0
        self.bpm_source = "off"
        self.tap_tempo_tracker = TapTempo()
        self.sequencer = PlaylistSequencer()
        self.audio_capture = AudioCapture()
        self._audio_active = False
        self.outputs = OutputHub()
        self.outputs.set_processing(
            config.master.get("brightness", 1.0),
            config.master.get("gamma", 1.4),
        )
        from glediator.generators.palettes import set_custom_palettes

        set_custom_palettes(config.palettes)
        if config.live_state:
            self.restore_state(config.live_state)

    def set_palettes(self, palettes: dict[str, list[str]]) -> None:
        from glediator.generators.palettes import set_custom_palettes

        with self._lock:
            self.config.palettes = dict(palettes)
            set_custom_palettes(self.config.palettes)

    def set_master(
        self,
        brightness: float | None = None,
        gamma: float | None = None,
        blackout: bool | None = None,
        freeze: bool | None = None,
        speed: float | None = None,
    ) -> None:
        with self._lock:
            cur_b, cur_g = self.outputs.processing_settings()
            new_b = cur_b if brightness is None else max(0.0, min(1.0, float(brightness)))
            new_g = cur_g if gamma is None else max(0.1, min(4.0, float(gamma)))
            self.config.master["brightness"] = new_b
            self.config.master["gamma"] = new_g
            if blackout is not None:
                self.blackout = bool(blackout)
            if freeze is not None:
                self.freeze = bool(freeze)
            if speed is not None:
                self.speed = max(0.0, min(4.0, float(speed)))
        self.outputs.set_processing(new_b, new_g)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._last_tick = self._clock()
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

    def duplicate_layer(self, side: str, layer: int) -> int | None:
        with self._lock:
            return self._scene(side).duplicate_layer(layer)

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

    def copy_scene(self, src_side: str, dst_side: str) -> None:
        with self._lock:
            data = copy.deepcopy(self._scene(src_side).to_dict())
            data["name"] = self._scene(dst_side).name
            self._scene(dst_side).restore(data)

    def swap_scenes(self) -> None:
        with self._lock:
            left_data = copy.deepcopy(self.left_scene.to_dict())
            right_data = copy.deepcopy(self.right_scene.to_dict())
            left_name, right_name = self.left_scene.name, self.right_scene.name
            right_data["name"] = left_name
            left_data["name"] = right_name
            self.left_scene.restore(right_data)
            self.right_scene.restore(left_data)

    def rename_scene(self, side: str, name: str) -> None:
        cleaned = str(name).strip()
        if not cleaned:
            return
        with self._lock:
            self._scene(side).name = cleaned

    def set_fader(self, amount: float, *, cancel_transition: bool = True) -> None:
        with self._lock:
            if cancel_transition:
                self._transition = None
                if self.loop_fader:
                    self._loop_next_at = self._clock() + self.loop_hold_s
            self.fader = min(1.0, max(0.0, float(amount)))

    def set_transition_kind(self, kind: str) -> None:
        if kind in TRANSITION_KINDS:
            with self._lock:
                self.transition_kind = kind

    def set_loop_fader(
        self,
        enabled: bool | None = None,
        hold_s: float | None = None,
        duration_s: float | None = None,
        kind: str | None = None,
    ) -> None:
        with self._lock:
            if hold_s is not None:
                old_hold = self.loop_hold_s
                self.loop_hold_s = max(0.0, min(300.0, float(hold_s)))
                if self.loop_fader and self._loop_next_at is not None:
                    self._loop_next_at += self.loop_hold_s - old_hold
            if duration_s is not None:
                self.loop_duration_s = max(0.1, min(30.0, float(duration_s)))
            if kind in TRANSITION_KINDS:
                self.transition_kind = kind
            if enabled is not None:
                want = bool(enabled)
                if want and not self.loop_fader:
                    self.loop_fader = True
                    now = self._clock()
                    if self._transition is None:
                        target = 1.0 if self.fader < 0.5 else 0.0
                        self._transition = Transition(
                            kind=self.transition_kind,
                            start_value=self.fader,
                            target=target,
                            duration=self.loop_duration_s,
                            started_at=now,
                        )
                    self._loop_next_at = None
                elif not want:
                    self.loop_fader = False
                    self._loop_next_at = None

    def start_transition(
        self,
        target: float,
        duration_s: float = 2.0,
        kind: str | None = None,
        easing: str = "ease_in_out",
    ) -> None:
        with self._lock:
            chosen_kind = kind if kind in TRANSITION_KINDS else self.transition_kind
            self.transition_kind = chosen_kind
            self._loop_next_at = None
            self._transition = Transition(
                kind=chosen_kind,
                start_value=self.fader,
                target=min(1.0, max(0.0, float(target))),
                duration=max(0.0, float(duration_s)),
                started_at=self._clock(),
                easing=easing,
            )

    def cancel_transition(self) -> None:
        with self._lock:
            self._transition = None
            self.loop_fader = False
            self._loop_next_at = None

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
        opacity: int | None = None,
        filter_name: str | None = None,
        filters: list[dict] | None = None,
        mix_mode: str | None = None,
    ) -> None:
        from glediator.core.filters import sanitize_filter_chain

        with self._lock:
            scene = self._scene(side)
            item = scene.layers[layer]
            if brightness is not None:
                item.brightness = min(100, max(0, int(brightness)))
            if opacity is not None:
                item.opacity = min(100, max(0, int(opacity)))
            if filter_name is not None:
                item.filter_name = filter_name
                if filters is None:
                    item.filters = sanitize_filter_chain(None, legacy_filter=filter_name)
                    scene._filter_state[layer].clear()
            if filters is not None:
                item.filters = sanitize_filter_chain(filters)
                scene._filter_state[layer].clear()
            if mix_mode is not None:
                item.mix_mode = mix_mode

    def set_generator_parameters(self, side: str, layer: int, parameters: dict) -> None:
        from glediator.effects import sanitize_effect_parameters

        with self._lock:
            scene = self._scene(side)
            target = scene.layers[layer]
            target.parameters = sanitize_effect_parameters(target.generator_name, parameters)
            scene._last_applied_params[layer] = None
            scene._generators[layer].configure(target.parameters)

    def set_layer_modulations(self, side: str, layer: int, modulations: list[dict]) -> None:
        with self._lock:
            scene = self._scene(side)
            target = scene.layers[layer]
            target.modulations = sanitize_modulations(target.generator_name, modulations)
            scene._last_applied_params[layer] = None
            if not target.modulations:
                scene._generators[layer].configure(target.parameters)

    def load_scene_state(self, side: str, scene_dict: dict) -> None:
        with self._lock:
            self._scene(side).restore(scene_dict)

    def tap_tempo(self) -> float:
        bpm = self.tap_tempo_tracker.tap()
        with self._lock:
            if bpm > 0:
                self.bpm_source = "tap"
        return bpm

    def clear_tap_tempo(self) -> None:
        self.tap_tempo_tracker.reset()
        with self._lock:
            self.bpm_source = "detected" if self._detected_bpm > 0 else "off"

    def play_playlist(self, playlist: dict) -> None:
        with self._lock:
            entry = self.sequencer.play(playlist)
            if entry:
                self._apply_playlist_entry(entry)

    def stop_playlist(self) -> None:
        with self._lock:
            self.sequencer.stop()

    def next_playlist_entry(self) -> None:
        with self._lock:
            entry = self.sequencer.advance(1)
            if entry:
                self._apply_playlist_entry(entry)

    def prev_playlist_entry(self) -> None:
        with self._lock:
            entry = self.sequencer.advance(-1)
            if entry:
                self._apply_playlist_entry(entry)

    def _apply_playlist_entry(self, entry: dict) -> None:
        preset_name = str(entry.get("preset", ""))
        preset = next((p for p in self.config.presets if p.get("name") == preset_name), None)
        if not preset:
            return
        state = preset.get("state", {})
        target_side = "right" if self.fader < 0.5 else "left"
        target_fader = 1.0 if target_side == "right" else 0.0
        source_key = "left" if isinstance(state.get("left"), dict) else "right"
        if isinstance(state.get(source_key), dict):
            self._scene(target_side).restore(state[source_key])
        self.start_transition(
            target_fader,
            float(entry.get("transition_s", 1.5)),
            kind=str(entry.get("transition_kind", self.transition_kind)),
        )

    def export_state(self) -> dict:
        with self._lock:
            return {
                "left": self.left_scene.to_dict(),
                "right": self.right_scene.to_dict(),
                "fader": self.fader,
                "transition_kind": self.transition_kind,
                "loop_fader": self.loop_fader,
                "loop_hold_s": self.loop_hold_s,
                "loop_duration_s": self.loop_duration_s,
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
            if state.get("transition_kind") in TRANSITION_KINDS:
                self.transition_kind = state["transition_kind"]
            self.loop_fader = bool(state.get("loop_fader", False))
            self.loop_hold_s = max(0.0, min(300.0, float(state.get("loop_hold_s", 5.0))))
            self.loop_duration_s = max(0.1, min(30.0, float(state.get("loop_duration_s", 2.0))))
            self._loop_next_at = (self._clock() + self.loop_hold_s) if self.loop_fader else None
            self._transition = None

    def scene_snapshot(self, side: str) -> dict:
        with self._lock:
            return copy.deepcopy(self._scene(side).to_dict())

    def status(self) -> EngineStatus:
        with self._lock:
            fps = self.fps
            frame_count = self.frame_count
            bpm = self.tap_tempo_tracker.bpm if self.bpm_source == "tap" else self._detected_bpm
            layer_errors: dict[tuple[str, int], str] = {}
            layer_times_ms: dict[tuple[str, int], float] = {}
            for side, scene in (("left", self.left_scene), ("right", self.right_scene)):
                for index, (layer, generator) in enumerate(zip(scene.layers, scene._generators, strict=True)):
                    if layer.configured:
                        layer_times_ms[(side, index)] = scene.layer_times_ms[index]
                    if layer.enabled:
                        err = getattr(generator, "last_error", "")
                        if err:
                            layer_errors[(side, index)] = err
            seq_status = self.sequencer.status()
            base_status = EngineStatus(
                fps=fps,
                frame_count=frame_count,
                fader=self.fader,
                transition_active=self._transition is not None,
                transition_kind=self.transition_kind,
                loop_fader=self.loop_fader,
                loop_hold_s=self.loop_hold_s,
                blackout=self.blackout,
                freeze=self.freeze,
                speed=self.speed,
                bpm=bpm,
                bpm_source=self.bpm_source,
                frame_time_ms=self._frame_time_ms,
                dropped_frames=self._dropped_frames,
                layer_times_ms=layer_times_ms,
                layer_errors=layer_errors,
                audio_error=self.audio_capture.last_error,
                output_errors=self.outputs.errors(),
                sequencer=seq_status,
            )
        output_statuses = {}
        for output_id, output in self.outputs.items():
            if hasattr(output, "status"):
                output_statuses[output_id] = output.status()
        base_status.outputs = output_statuses
        return base_status

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
            and layer.generator_name in ("VU Meter", "Spectrum Analyser")
        ]
        mod_audio = self.left_scene.has_audio_modulation() or self.right_scene.has_audio_modulation()
        if not audio_layers and not mod_audio:
            return False, "System Output", False, 2.5
        source = audio_layers[0].parameters.get("source", "System Output") if audio_layers else "System Output"
        auto_layers = [
            layer
            for layer in audio_layers
            if layer.generator_name in ("VU Meter", "Spectrum Analyser")
            and layer.parameters.get("auto_sensitivity", "Off") == "On"
        ]
        sensitivity = max((float(layer.parameters.get("sensitivity", 2.5)) for layer in auto_layers), default=2.5)
        return True, source, bool(auto_layers), sensitivity

    def step(self, now: float | None = None, audio_state: dict | None = None) -> np.ndarray:
        """Execute a single render tick; exposed for deterministic testing."""
        started = self._clock() if now is None else now
        dt = max(0.0, started - self._last_tick)
        self._last_tick = started

        with self._lock:
            if self._transition is not None:
                val, done = self._transition.progress(started)
                self.fader = val
                if done:
                    self._transition = None
                    if self.loop_fader:
                        self._loop_next_at = started + self.loop_hold_s
            elif self.loop_fader:
                if self._loop_next_at is None:
                    self._loop_next_at = started + self.loop_hold_s
                if started >= self._loop_next_at:
                    target = 1.0 if self.fader < 0.5 else 0.0
                    self._transition = Transition(
                        kind=self.transition_kind,
                        start_value=self.fader,
                        target=target,
                        duration=self.loop_duration_s,
                        started_at=started,
                    )
                    self._loop_next_at = None

            if audio_state:
                det = float(audio_state.get("audio_bpm", 0.0))
                if det > 0:
                    self._detected_bpm = det
                    if self.bpm_source != "tap":
                        self.bpm_source = "detected"
            if self.bpm_source == "tap" and self.tap_tempo_tracker.bpm <= 0:
                self.bpm_source = "detected" if self._detected_bpm > 0 else "off"

            active_bpm = (
                self.tap_tempo_tracker.bpm
                if self.bpm_source == "tap"
                else (self._detected_bpm if self._detected_bpm > 0 else 60.0)
            )
            self._lfo_phase = (self._lfo_phase + dt * (active_bpm / 60.0)) % 1.0
            mod_context = {
                "lfo_sine": 0.5 + 0.5 * math.sin(self._lfo_phase * 2.0 * math.pi),
                "lfo_saw": self._lfo_phase,
            }

            beat_fired = bool(audio_state.get("audio_beat")) if audio_state else False
            next_entry = self.sequencer.tick(beat_fired=beat_fired)
            if next_entry:
                self._apply_playlist_entry(next_entry)

            if self.freeze and "mixed" in self._latest:
                mixed = self._latest["mixed"]
            else:
                self._scene_time += dt * self.speed
                left = self.left_scene.render(self._scene_time, audio_state, mod_context)
                right = self.right_scene.render(self._scene_time, audio_state, mod_context)
                mixed = crossfade(left, right, self.fader, self.transition_kind)
                self._latest = {"left": left, "right": right, "mixed": mixed}

            out_frame = new_frame(self.config.width, self.config.height) if self.blackout else mixed
            self.frame_count += 1
            self._fps_frames += 1
            elapsed_fps = started - self._last_fps_time
            if elapsed_fps >= 1.0:
                self.fps = self._fps_frames / elapsed_fps
                self._last_fps_time = started
                self._fps_frames = 0
            render_ms = (self._clock() - started) * 1000.0
            self._frame_time_ms = (
                render_ms if self._frame_time_ms == 0.0 else (0.85 * self._frame_time_ms + 0.15 * render_ms)
            )
            return out_frame

    def _run(self) -> None:
        next_deadline = self._clock()
        while self.running:
            period = 1.0 / max(1, self.config.fps)
            started = self._clock()
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
            out_frame = self.step(started, audio_state)
            self.outputs.submit(out_frame)

            next_deadline += period
            now = self._clock()
            if now > next_deadline + period:
                self._dropped_frames += 1
                next_deadline = now
            time.sleep(max(0.0, next_deadline - now))
