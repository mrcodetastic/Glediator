from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field

import numpy as np

from glediator.core.filters import apply_filter_chain, sanitize_filter_chain
from glediator.core.frame import new_frame
from glediator.core.pipeline import LEGACY_FILTERS, MIX_MODES, apply_filter, mix
from glediator.effects import (
    create_effect,
    default_effect_parameters,
    effect_names,
    effect_settings,
    sanitize_effect_parameters,
)

MODULATION_SOURCES = ("level", "peak", "bass", "mid", "treble", "beat", "lfo_sine", "lfo_saw")
AUDIO_MOD_SOURCES = frozenset({"level", "peak", "bass", "mid", "treble", "beat"})


def sanitize_modulations(generator_name: str, items: list | None) -> list[dict]:
    if not isinstance(items, list):
        return []
    schema = effect_settings(generator_name)
    result: list[dict] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        param = str(entry.get("param", ""))
        if param not in schema:
            continue
        kind, _default, low, high, _step = schema[param]
        if kind not in ("int", "float"):
            continue
        source = str(entry.get("source", ""))
        if source not in MODULATION_SOURCES:
            continue
        try:
            amount = float(np.clip(float(entry.get("amount", 1.0)), 0.0, 2.0))
            m_min = float(np.clip(float(entry.get("min", low)), low, high))
            m_max = float(np.clip(float(entry.get("max", high)), low, high))
            smoothing = float(np.clip(float(entry.get("smoothing", 0.3)), 0.0, 0.98))
        except (TypeError, ValueError):
            continue
        result.append({
            "param": param,
            "source": source,
            "amount": amount,
            "min": m_min,
            "max": m_max,
            "smoothing": smoothing,
        })
    return result


@dataclass
class Layer:
    generator_name: str = "Plasma"
    enabled: bool = True
    configured: bool = True
    brightness: int = 100
    opacity: int = 100
    filter_name: str = "None"
    filters: list[dict] = field(default_factory=list)
    mix_mode: str = "Add"
    parameters: dict = field(default_factory=dict)
    modulations: list[dict] = field(default_factory=list)


class Scene:
    """A scene owns five independently configurable generator layers."""

    def __init__(self, name: str, width: int = 64, height: int = 32) -> None:
        self.name = name
        self.width, self.height = width, height
        self.layers = [
            Layer(generator_name="Plasma" if i == 0 else "Black", enabled=(i == 0), configured=(i == 0))
            for i in range(5)
        ]
        self._generators = [create_effect(layer.generator_name) for layer in self.layers]
        self._mod_ema: list[dict[str, float]] = [{} for _ in range(5)]
        self._last_applied_params: list[dict | None] = [None for _ in range(5)]
        self._filter_state: list[dict] = [{} for _ in range(5)]
        self.layer_times_ms: list[float] = [0.0 for _ in range(5)]
        self.active_layer = 0
        self._frame = new_frame(width, height)

    def resize(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self._frame = new_frame(width, height)
        for st in self._filter_state:
            st.clear()

    def set_generator(self, index: int, name: str) -> None:
        if name == "Expanding Objects":
            name = "Expanding Circles"
        if name not in effect_names():
            raise ValueError(f"Unknown effect: {name}")
        self._generators[index].cleanup()
        self.layers[index].generator_name = name
        self.layers[index].configured = True
        self.layers[index].parameters = default_effect_parameters(name)
        self.layers[index].modulations = []
        self._mod_ema[index].clear()
        self._last_applied_params[index] = None
        self._filter_state[index].clear()
        self._generators[index] = create_effect(name)
        self.layers[index].enabled = True

    def add_layer(self, name: str) -> int | None:
        """Add an enabled effect in the first free slot, up to the five-layer limit."""
        for index, layer in enumerate(self.layers):
            if not layer.configured:
                self.set_generator(index, name)
                return index
        return None

    def duplicate_layer(self, source: int) -> int | None:
        if not (0 <= source < 5) or not self.layers[source].configured:
            return None
        src = self.layers[source]
        for index, layer in enumerate(self.layers):
            if not layer.configured:
                self._generators[index].cleanup()
                eff = create_effect(src.generator_name)
                params = copy.deepcopy(src.parameters)
                eff.configure(params)
                self._generators[index] = eff
                self.layers[index] = Layer(
                    generator_name=src.generator_name,
                    enabled=src.enabled,
                    configured=True,
                    brightness=src.brightness,
                    opacity=src.opacity,
                    filter_name=src.filter_name,
                    filters=copy.deepcopy(src.filters),
                    mix_mode=src.mix_mode,
                    parameters=params,
                    modulations=copy.deepcopy(src.modulations),
                )
                self._mod_ema[index].clear()
                self._last_applied_params[index] = None
                self._filter_state[index].clear()
                return index
        return None

    def remove_layer(self, index: int) -> None:
        self._generators[index].cleanup()
        self.layers[index] = Layer(generator_name="Black", enabled=False, configured=False)
        self._generators[index] = create_effect("Black")
        self._mod_ema[index].clear()
        self._last_applied_params[index] = None
        self._filter_state[index].clear()
        self.layer_times_ms[index] = 0.0

    def move_layer(self, source: int, destination: int) -> None:
        if source == destination:
            return
        self.layers[source], self.layers[destination] = self.layers[destination], self.layers[source]
        self._generators[source], self._generators[destination] = (
            self._generators[destination],
            self._generators[source],
        )
        self._mod_ema[source], self._mod_ema[destination] = self._mod_ema[destination], self._mod_ema[source]
        self._last_applied_params[source], self._last_applied_params[destination] = (
            self._last_applied_params[destination],
            self._last_applied_params[source],
        )
        self._filter_state[source], self._filter_state[destination] = (
            self._filter_state[destination],
            self._filter_state[source],
        )
        self.layer_times_ms[source], self.layer_times_ms[destination] = (
            self.layer_times_ms[destination],
            self.layer_times_ms[source],
        )

    def has_audio_modulation(self) -> bool:
        return any(
            layer.configured
            and layer.enabled
            and any(mod.get("source") in AUDIO_MOD_SOURCES for mod in layer.modulations)
            for layer in self.layers
        )

    def _apply_modulations(
        self,
        index: int,
        layer: Layer,
        generator,
        audio_state: dict | None,
        mod_context: dict | None,
    ) -> None:
        if not layer.modulations:
            if self._last_applied_params[index] is not None:
                generator.configure(layer.parameters)
                self._last_applied_params[index] = None
            return

        schema = effect_settings(layer.generator_name)
        effective = dict(layer.parameters) if layer.parameters else default_effect_parameters(layer.generator_name)
        sources: dict[str, float] = {}
        if audio_state:
            sources["level"] = float(audio_state.get("audio_level", 0.0))
            sources["peak"] = float(audio_state.get("audio_peak", 0.0))
            sources["bass"] = float(audio_state.get("audio_bass", 0.0))
            sources["mid"] = float(audio_state.get("audio_mid", 0.0))
            sources["treble"] = float(audio_state.get("audio_treble", 0.0))
            sources["beat"] = 1.0 if audio_state.get("audio_beat") else 0.0
        if mod_context:
            for key in ("lfo_sine", "lfo_saw"):
                if key in mod_context:
                    sources[key] = float(mod_context[key])

        ema_state = self._mod_ema[index]
        for mod in layer.modulations:
            param = mod["param"]
            if param not in schema:
                continue
            raw = float(np.clip(sources.get(mod["source"], 0.0), 0.0, 1.0))
            smoothing = float(mod.get("smoothing", 0.3))
            ema_key = f"{param}:{mod['source']}"
            prev = ema_state.get(ema_key, raw)
            smoothed = smoothing * prev + (1.0 - smoothing) * raw
            ema_state[ema_key] = smoothed
            scaled = float(np.clip(float(mod["amount"]) * smoothed, 0.0, 1.0))
            val = float(mod["min"]) + (float(mod["max"]) - float(mod["min"])) * scaled
            kind = schema[param][0]
            effective[param] = round(val) if kind == "int" else val

        last = self._last_applied_params[index]
        changed = last is None
        if not changed:
            for k, v in effective.items():
                old = last.get(k)
                if isinstance(v, (int, float)) and isinstance(old, (int, float)):
                    if abs(float(v) - float(old)) > 1e-3:
                        changed = True
                        break
                elif v != old:
                    changed = True
                    break
        if changed:
            generator.configure(effective)
            self._last_applied_params[index] = effective

    def render(
        self,
        time_seconds: float,
        audio_state: dict | None = None,
        mod_context: dict | None = None,
    ) -> np.ndarray:
        self._frame.fill(0)
        has_layer = False
        for index, (layer, generator) in enumerate(zip(self.layers, self._generators, strict=True)):
            if not layer.enabled:
                self.layer_times_ms[index] = 0.0
                continue
            t0 = time.perf_counter()
            self._apply_modulations(index, layer, generator, audio_state, mod_context)
            image = generator.drawFrame(self.width, self.height, time_seconds, audio_state)
            if layer.filters:
                image = apply_filter_chain(image, layer.filters, time_seconds, self._filter_state[index])
            elif layer.filter_name != "None":
                image = apply_filter(image, layer.filter_name)
            if layer.brightness != 100:
                image = np.clip(image.astype(np.float32) * (layer.brightness / 100.0), 0, 255).astype(np.uint8)
            mode = layer.mix_mode if has_layer else "Normal"
            self._frame[:] = mix(self._frame, image, mode, layer.opacity)
            has_layer = True
            ms = (time.perf_counter() - t0) * 1000.0
            prev_ms = self.layer_times_ms[index]
            self.layer_times_ms[index] = ms if prev_ms == 0.0 else (0.85 * prev_ms + 0.15 * ms)
        return self._frame.copy()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "active_layer": self.active_layer,
            "layers": [
                {
                    "generator": layer.generator_name,
                    "enabled": layer.enabled,
                    "configured": layer.configured,
                    "brightness": layer.brightness,
                    "opacity": layer.opacity,
                    "filter": layer.filter_name,
                    "filters": layer.filters,
                    "mix_mode": layer.mix_mode,
                    "parameters": layer.parameters,
                    "modulations": layer.modulations,
                }
                for layer in self.layers
            ],
        }

    def restore(self, data: dict) -> None:
        self.name = str(data.get("name", self.name))
        self.active_layer = max(0, min(4, int(data.get("active_layer", 0))))
        saved_layers = data.get("layers", [])
        for index in range(min(5, len(saved_layers))):
            saved = saved_layers[index]
            if not isinstance(saved, dict):
                continue
            name = saved.get("generator", "Black")
            legacy_aliases = {
                "Expanding Objects": "Expanding Circles",
                "Falling Objects": "Falling Snow",
                "FireKoz": "Fire",
                "Spin": "Spiral",
                "Simple Spectrum": "Spectrum Analyser",
                "Maze": "3D Maze",
            }
            name = legacy_aliases.get(name, name)
            if name not in effect_names():
                name = "Black"
            self._generators[index].cleanup()
            effect = create_effect(name)
            parameters = sanitize_effect_parameters(name, saved.get("parameters"))
            effect.configure(parameters)
            self._generators[index] = effect
            self._mod_ema[index].clear()
            self._last_applied_params[index] = None
            self._filter_state[index].clear()
            legacy_filter = (
                saved.get("filter", "None") if saved.get("filter") in LEGACY_FILTERS else "None"
            )
            filters = sanitize_filter_chain(saved.get("filters"), legacy_filter=legacy_filter)
            self.layers[index] = Layer(
                generator_name=name,
                enabled=bool(saved.get("enabled", index == 0)),
                configured=bool(saved.get("configured", saved.get("enabled", index == 0) or name != "Black")),
                brightness=max(0, min(100, int(saved.get("brightness", 100)))),
                opacity=max(0, min(100, int(saved.get("opacity", 100)))),
                filter_name=legacy_filter,
                filters=filters,
                mix_mode=saved.get("mix_mode", "Add") if saved.get("mix_mode") in MIX_MODES else "Add",
                parameters=parameters,
                modulations=sanitize_modulations(name, saved.get("modulations")),
            )

    def close(self) -> None:
        for generator in self._generators:
            generator.cleanup()
