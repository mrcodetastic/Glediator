from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np

from glediator.audio.capture import AudioCapture
from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.effects import create_effect, effect_categories, effect_names, picker_effect_names
from glediator.effects.base import EFFECT_CATEGORIES
from glediator.output.mrcodetastic_websocket import MrCodetasticWebSocketOutput


def test_row_major_websocket_encoding_order():
    frame = np.zeros((2, 3, 3), dtype=np.uint8)
    frame[0, 0] = (255, 0, 0)
    frame[0, 2] = (0, 255, 0)
    frame[1, 1] = (0, 0, 255)
    encoded = MrCodetasticWebSocketOutput.encode_frame(frame)
    pixels = np.frombuffer(encoded[2:], dtype=">u2").tolist()
    assert pixels == [0xF800, 0x0000, 0x07E0, 0x0000, 0x001F, 0x0000]


def test_v1_config_migrates_and_strips_mapping(tmp_path: Path):
    path = tmp_path / "settings.json"
    v1_data = {
        "width": 64,
        "height": 32,
        "mapping": "vertical-snake",
        "websocket_url": "ws://192.168.1.44:9999",
        "presets": [{"name": "P1", "state": {}, "mapping": "horizontal-snake"}],
    }
    path.write_text(json.dumps(v1_data), encoding="utf-8")
    loaded = EngineConfig.load(path)
    assert loaded.config_version == 3
    assert loaded.websocket_host == "192.168.1.44"
    assert loaded.websocket_port == 9999
    assert "mapping" not in loaded.presets[0]
    loaded.save(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "mapping" not in saved
    assert saved["config_version"] == 3


def test_atomic_save_and_backup_recovery(tmp_path: Path):
    path = tmp_path / "settings.json"
    cfg = EngineConfig(width=48, height=24, websocket_host="10.0.0.5")
    cfg.save(path)
    cfg.width = 96
    cfg.save(path)
    assert not path.with_name("settings.json.tmp").exists()
    assert path.with_name("settings.json.bak").exists()
    path.write_text("{corrupt json", encoding="utf-8")
    recovered = EngineConfig.load(path)
    assert recovered.width == 48
    assert recovered.load_warning


def test_render_thread_feeds_output_hub():
    class FakeOutput:
        def __init__(self) -> None:
            self.frames: list[np.ndarray] = []

        def submit(self, frame: np.ndarray) -> None:
            self.frames.append(frame)

    engine = RenderEngine(EngineConfig(width=16, height=8, fps=60))
    fake = FakeOutput()
    engine.outputs.add("fake", fake)
    engine.start()
    try:
        time.sleep(0.45)
        count = len(fake.frames)
        assert count >= 15
        engine.outputs.remove("fake")
        after = len(fake.frames)
        time.sleep(0.1)
        assert len(fake.frames) == after
    finally:
        engine.stop()


def test_audio_stop_does_not_block_engine_lock(monkeypatch):
    engine = RenderEngine(EngineConfig(width=16, height=8, fps=60))
    entered_stop = threading.Event()
    release_stop = threading.Event()

    def slow_stop() -> None:
        entered_stop.set()
        release_stop.wait(timeout=1.5)

    monkeypatch.setattr(engine.audio_capture, "start", lambda: None)
    monkeypatch.setattr(engine.audio_capture, "stop", slow_stop)
    engine.set_generator("left", 0, "VU Meter")
    engine.start()
    try:
        time.sleep(0.08)
        engine.set_generator("left", 0, "Plasma")
        assert entered_stop.wait(timeout=1.0)
        t0 = time.perf_counter()
        engine.set_fader(0.25)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.1
    finally:
        release_stop.set()
        engine.stop()


def test_audio_retry_backoff(monkeypatch):
    import sys
    import types

    cap = AudioCapture()
    assert cap.spectrum.shape == (AudioCapture.SPECTRUM_BINS,)

    fake_now = [100.0]
    monkeypatch.setattr("glediator.audio.capture.time.monotonic", lambda: fake_now[0])
    fake_sc = types.SimpleNamespace(default_speaker=lambda: None, default_microphone=lambda: None)
    monkeypatch.setitem(sys.modules, "soundcard", fake_sc)

    cap.start()
    if cap._thread:
        cap._thread.join(timeout=1.0)
    assert "Audio input unavailable" in cap.last_error

    cap.start()
    assert cap._thread is None

    fake_now[0] = 103.0
    cap.start()
    assert cap._thread is not None
    cap._thread.join(timeout=1.0)


def test_engine_status_and_scene_snapshot():
    engine = RenderEngine(EngineConfig(width=16, height=8))
    status = engine.status()
    assert status.frame_count == 0
    snap = engine.scene_snapshot("left")
    snap["layers"][0]["brightness"] = 1
    assert engine.scene_snapshot("left")["layers"][0]["brightness"] == 100


def test_registry_caching_and_categories():
    t0 = time.perf_counter()
    for _ in range(1000):
        names = effect_names()
    assert time.perf_counter() - t0 < 0.25
    assert names == sorted(names, key=str.casefold)
    assert "Black" not in picker_effect_names()
    cats = effect_categories()
    assert set(cats.values()).issubset(set(EFFECT_CATEGORIES))
    assert create_effect("Black").drawFrame(8, 8, 0.0).shape == (8, 8, 3)


def test_scrolling_text_palette_and_solid_colors():
    fx = create_effect("Scrolling Text")
    fx.configure({
        "text": "HI",
        "font": "NoSuchFontFamilyXYZ",
        "font_size": 14,
        "color_mode": "Solid",
        "color": "#ff0000",
        "background": "#000000",
        "speed": 10.0,
    })
    solid = fx.drawFrame(32, 16, 1.5)
    assert solid.shape == (16, 32, 3)
    assert np.count_nonzero(solid[..., 0]) > 0
    assert np.count_nonzero(solid[..., 1]) == 0
    assert np.count_nonzero(solid[..., 2]) == 0

    fx.configure({
        "text": "HI",
        "font": "Arial",
        "font_size": 14,
        "color_mode": "Palette",
        "palette": "Fire",
        "background": "#000000",
        "speed": 10.0,
    })
    pal = fx.drawFrame(32, 16, 1.5)
    assert not np.array_equal(solid, pal)
