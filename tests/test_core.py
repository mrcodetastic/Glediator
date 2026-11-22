from pathlib import Path

import numpy as np

from glediator.audio.capture import AudioCapture
from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.core.fader import crossfade
from glediator.core.frame import to_rgb565
from glediator.core.pipeline import mix
from glediator.core.scene import Scene
from glediator.effects import create_effect
from glediator.generators import generator_names
from glediator.generators.palettes import PALETTES, colorize
from glediator.network.discovery import DeviceDiscovery
from glediator.output.mrcodetastic_websocket import MrCodetasticWebSocketOutput


def _render_effect(name: str, width: int, height: int, t: float, params: dict | None = None, audio: dict | None = None):
    effect = create_effect(name)
    if params is not None:
        effect.configure(params)
    return effect.drawFrame(width, height, t, audio)


def test_fader_endpoints():
    a = np.full((2, 3, 3), 10, dtype=np.uint8)
    b = np.full((2, 3, 3), 240, dtype=np.uint8)
    assert np.all(crossfade(a, b, 0) == a)
    assert np.all(crossfade(a, b, 1) == b)


def test_rgb565_and_mix():
    assert int(to_rgb565(np.array([[[255, 0, 0]]], dtype=np.uint8))[0, 0]) == 0xF800
    result = mix(np.array([[[200, 80, 10]]], dtype=np.uint8), np.array([[[100, 80, 20]]], dtype=np.uint8))
    assert result.tolist() == [[[255, 160, 30]]]


def test_generators_and_scene_shapes():
    assert "Plasma" in generator_names()
    scene = Scene("test", 32, 16)
    for name in generator_names():
        scene.set_generator(0, name)
        frame = scene.render(1.25)
        assert frame.shape == (16, 32, 3)
        assert frame.dtype == np.uint8


def test_mrcodetastic_websocket_frame_marker_and_rgb565_payload():
    frame = np.zeros((32, 64, 3), dtype=np.uint8)
    frame[0, 0] = (255, 0, 0)
    data = MrCodetasticWebSocketOutput.encode_frame(frame)
    assert data[:2] == bytes((0b10000001, 0b10000001))
    assert data[2:4] == bytes((0xF8, 0x00))
    assert len(data) == 2 + (64 * 32 * 2)


def test_scene_state_and_generator_parameters_round_trip():
    scene = Scene("preset", 24, 12)
    scene.set_generator(2, "Screen Capture")
    scene.layers[2].parameters.update({"monitor": 2, "x": 80, "width": 320})
    scene.layers[2].brightness = 64
    restored = Scene("blank", 24, 12)
    restored.restore(scene.to_dict())
    assert restored.name == "preset"
    assert restored.layers[2].generator_name == "Screen Capture"
    assert restored.layers[2].parameters == {
        "monitor": 2,
        "x": 80,
        "y": 0,
        "width": 320,
        "height": 0,
        "capture_fps": 8,
    }
    assert restored.layers[2].brightness == 64


def test_engine_effect_slot_limit_remove_and_reorder():
    engine = RenderEngine(EngineConfig())
    indices = [engine.add_layer("left", name) for name in ("Fire", "Grid", "Wave", "Screen Capture")]
    assert indices == [1, 2, 3, 4]
    assert engine.add_layer("left", "Plasma") is None
    engine.move_layer("left", 4, 2)
    assert engine.scene_snapshot("left")["layers"][2]["generator"] == "Screen Capture"
    engine.remove_layer("left", 2)
    assert engine.add_layer("left", "Plasma") == 2
    assert sum(layer["configured"] for layer in engine.scene_snapshot("left")["layers"]) == 5


def test_scrolling_text_uses_readable_font_and_configurable_direction():
    common = {"text": "Glediator", "font": "Arial", "font_size": 16, "speed": 3.0}
    left = _render_effect("Scrolling Text", 64, 32, 0.5, {**common, "direction": "Left"})
    up = _render_effect("Scrolling Text", 64, 32, 0.5, {**common, "direction": "Up"})
    assert left.shape == (32, 64, 3)
    assert np.count_nonzero(left) > 0
    assert not np.array_equal(left, up)


def test_audio_analyzer_produces_level_and_spectrum():
    samples = np.sin(np.linspace(0, np.pi * 8, 1024, dtype=np.float32)) * 0.1
    level, peak, spectrum = AudioCapture.analyse(samples)
    assert 0 < level <= 1
    assert 0 < peak <= 1
    assert spectrum.shape == (AudioCapture.SPECTRUM_BINS,)
    assert np.max(spectrum) > 0


def test_vu_meter_responds_to_audio_state():
    silent = _render_effect("VU Meter", 32, 16, 0, audio={"audio_level": 0, "audio_peak": 0})
    loud = _render_effect("VU Meter", 32, 16, 0, audio={"audio_level": 0.8, "audio_peak": 0.9})
    assert np.count_nonzero(loud) > np.count_nonzero(silent)


def test_shared_palettes_and_wave_controls():
    assert {"Aurora", "Fire", "Ocean", "Rainbow", "Monochrome"}.issubset(PALETTES)
    wave = create_effect("Wave")
    custom = {
        "amplitude": 0.2,
        "frequency": 1.5,
        "position": 0.2,
        "thickness": 0.08,
        "speed": 1.0,
        "palette": "Custom",
        "color_a": "#ff0000",
        "color_b": "#0000ff",
        "background": "#000000",
    }
    wave.configure(custom)
    red_wave = wave.drawFrame(64, 32, 0.4)
    custom["color_a"], custom["color_b"] = "#00ff00", "#ffffff"
    wave.configure(custom)
    green_wave = wave.drawFrame(64, 32, 0.4)
    assert not np.array_equal(red_wave, green_wave)
    assert colorize(np.array([0.0, 1.0]), "Fire").shape == (2, 3)


def test_random_pixel_rate_and_fade_expiry():
    pixel = create_effect("Random Pixel")
    pixel._rng = np.random.default_rng(11)
    pixel._random_time = -0.1
    pixel.configure({"spawn_rate": 500, "fade_duration": 0.1, "palette": "Rainbow"})
    live = pixel.drawFrame(64, 32, 0.0)
    pixel.configure({"spawn_rate": 0, "fade_duration": 0.1, "palette": "Rainbow"})
    expired = pixel.drawFrame(64, 32, 0.11)
    assert np.count_nonzero(live) > 0
    assert np.count_nonzero(expired) == 0


def test_metaballs_count_changes_population_not_only_blob_scale():
    single = _render_effect("Meta Balls", 64, 32, 1.25, {"count": 1, "radius": 0.2, "speed": 0.7, "palette": "Aurora"})
    many = _render_effect("Meta Balls", 64, 32, 1.25, {"count": 8, "radius": 0.2, "speed": 0.7, "palette": "Aurora"})
    assert np.count_nonzero(many.max(axis=2) > 40) > np.count_nonzero(single.max(axis=2) > 40)


def test_new_aurora_patterns_and_expanding_circles_name():
    names = generator_names()
    assert "Expanding Circles" in names
    assert "Expanding Objects" not in names
    assert {"Attract", "Julia Set Fractal", "Starfield", "Aurora Wave", "Test"}.issubset(names)
    scene = Scene("legacy", 16, 8)
    scene.set_generator(0, "Expanding Objects")
    assert scene.layers[0].generator_name == "Expanding Circles"


def test_settings_persist_endpoint_and_live_scene(tmp_path: Path):
    config_path = tmp_path / "settings.json"
    config = EngineConfig(
        websocket_host="led-controller.local",
        websocket_port=8123,
        presets=[{"name": "Saved", "state": {}}],
    )
    engine = RenderEngine(config)
    engine.set_fader(0.72)
    config.live_state = engine.export_state()
    config.save(config_path)
    loaded = EngineConfig.load(config_path)
    restored_engine = RenderEngine(loaded)
    assert loaded.websocket_url == "ws://led-controller.local:8123"
    assert loaded.presets[0]["name"] == "Saved"
    assert restored_engine.fader == 0.72


def test_codetastic_udp_discovery_beacon_parser():
    assert DeviceDiscovery.PORT == 20586
    assert DeviceDiscovery.WEBSOCKET_PORT == 12345
    assert DeviceDiscovery.is_beacon(b"CODETASTIC")
    assert DeviceDiscovery.is_beacon(b"codetastic\r\n")
    assert DeviceDiscovery.is_beacon(b"CODETASTIC\x00")
    assert not DeviceDiscovery.is_beacon(b"NOT-CODETASTIC")
