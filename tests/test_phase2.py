from __future__ import annotations

import random

import numpy as np

from glediator.audio.features import AudioFeatureExtractor
from glediator.control.actions import ActionRegistry, register_engine_actions
from glediator.control.osc import OscController
from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.core.fader import crossfade
from glediator.core.sequencer import PlaylistSequencer
from glediator.core.tempo import TapTempo


def test_transition_modes_and_auto_crossfade():
    left = np.zeros((4, 8, 3), dtype=np.uint8)
    right = np.full((4, 8, 3), 200, dtype=np.uint8)

    assert np.array_equal(crossfade(left, right, 0.25, "cut"), left)
    assert np.array_equal(crossfade(left, right, 0.75, "cut"), right)

    wiped = crossfade(left, right, 0.25, "wipe_left")
    assert np.all(wiped[:, :2] == 200)
    assert np.all(wiped[:, 2:] == 0)

    d1 = crossfade(left, right, 0.4, "dissolve")
    d2 = crossfade(left, right, 0.4, "dissolve")
    assert np.array_equal(d1, d2)

    now = [0.0]
    engine = RenderEngine(EngineConfig(width=8, height=4), clock=lambda: now[0])
    engine.set_fader(0.0)
    engine.start_transition(1.0, duration_s=2.0, kind="crossfade", easing="linear")
    now[0] = 1.0
    engine.step()
    assert abs(engine.fader - 0.5) < 0.05
    now[0] = 2.0
    engine.step()
    assert engine.fader == 1.0


def test_master_blackout_freeze_and_speed():
    now = [0.0]
    engine = RenderEngine(EngineConfig(width=16, height=8), clock=lambda: now[0])
    engine.set_generator("left", 0, "Plasma")
    engine.set_fader(0.0)

    f0 = engine.step(0.0)
    assert np.count_nonzero(f0) > 0

    engine.set_master(blackout=True)
    f_black = engine.step(0.1)
    assert np.count_nonzero(f_black) == 0
    assert np.count_nonzero(engine.snapshot()["mixed"]) > 0

    engine.set_master(blackout=False, freeze=True)
    frozen_snap = engine.snapshot()["mixed"]
    f_frozen = engine.step(5.0)
    assert np.array_equal(f_frozen, frozen_snap)

    engine.set_master(freeze=False, speed=0.0)
    t_before = engine._scene_time
    engine.step(6.0)
    assert engine._scene_time == t_before

    engine.set_master(speed=2.0)
    engine.step(7.0)
    assert abs((engine._scene_time - t_before) - 2.0) < 1e-6


def test_audio_feature_extractor_bands_and_bpm():
    ext = AudioFeatureExtractor(sample_rate=44100, block_size=1024, spectrum_bins=1024)
    nyquist = 44100 / 2.0
    low_bin = int(60.0 / nyquist * 1024)
    spec_low = np.zeros(1024, dtype=np.float32)
    spec_low[low_bin] = 1.0
    feats = ext.process(spec_low)
    assert feats["audio_bass"] > feats["audio_treble"]

    # Simulate 120 BPM (0.5 s interval) onset impulses over ~6 seconds
    ext2 = AudioFeatureExtractor(sample_rate=44100, block_size=1024, spectrum_bins=1024)
    dt = 1024 / 44100
    beat_hits = 0
    bpm = 0.0
    for step in range(260):
        t = step * dt
        s = np.zeros(1024, dtype=np.float32)
        if (t % 0.5) < dt:
            s[2:8] = 1.0
        res = ext2.process(s, dt_seconds=dt)
        if res["audio_beat"]:
            beat_hits += 1
        if res["audio_bpm"] > 0:
            bpm = float(res["audio_bpm"])
    assert beat_hits >= 8
    assert 115.0 <= bpm <= 125.0


def test_tap_tempo_median_and_reset():
    now = [10.0]
    tt = TapTempo(clock=lambda: now[0])
    tt.tap()
    now[0] = 10.5
    tt.tap()
    now[0] = 11.0
    bpm = tt.tap()
    assert abs(bpm - 120.0) < 1.0

    now[0] = 15.0
    assert tt.tap() == 0.0


def test_parameter_modulation_and_sanitization():
    engine = RenderEngine(EngineConfig(width=16, height=8))
    engine.set_generator("left", 0, "Wave")
    engine.set_layer_modulations("left", 0, [
        {"param": "speed", "source": "bass", "amount": 1.0, "min": 1.0, "max": 7.0, "smoothing": 0.0},
        {"param": "nonexistent", "source": "bass", "amount": 1.0, "min": 0.0, "max": 1.0},
        {"param": "speed", "source": "bad_source", "amount": 1.0, "min": 0.0, "max": 1.0},
    ])
    snap = engine.scene_snapshot("left")
    assert len(snap["layers"][0]["modulations"]) == 1

    engine.step(0.1, audio_state={"audio_bass": 1.0})
    assert abs(engine.left_scene._generators[0].parameters["speed"] - 7.0) < 1e-3

    # Removing modulations restores base stored speed (2.0)
    engine.set_layer_modulations("left", 0, [])
    engine.step(0.2, audio_state=None)
    assert abs(engine.left_scene._generators[0].parameters["speed"] - 2.0) < 1e-3


def test_playlist_sequencer_timed_shuffle_and_beats():
    now = [0.0]
    seq = PlaylistSequencer(clock=lambda: now[0], rng=random.Random(3))
    pl = {
        "name": "Club",
        "loop": True,
        "shuffle": False,
        "entries": [
            {"preset": "P1", "mode": "time", "duration_s": 5.0},
            {"preset": "P2", "mode": "beats", "beats": 4},
        ],
    }
    first = seq.play(pl)
    assert first["preset"] == "P1"
    now[0] = 5.1
    nxt = seq.tick()
    assert nxt is not None and nxt["preset"] == "P2"
    for _ in range(3):
        assert seq.tick(beat_fired=True) is None
    wrap = seq.tick(beat_fired=True)
    assert wrap is not None and wrap["preset"] == "P1"

    pl["shuffle"] = True
    prev = seq.index
    for _ in range(10):
        seq.advance(1)
        assert seq.index != prev
        prev = seq.index


def test_actions_and_osc_dispatch():
    cfg = EngineConfig(width=16, height=8, presets=[{"name": "First", "state": {}}])
    engine = RenderEngine(cfg)
    reg = ActionRegistry()
    loaded = []
    register_engine_actions(reg, engine, cfg, load_preset_cb=loaded.append)

    assert reg.invoke("fader.set", 0.9)
    assert abs(engine.fader - 0.9) < 1e-6
    assert reg.invoke("master.blackout.toggle")
    assert engine.blackout is True
    assert reg.invoke("preset.load.1")
    assert loaded == ["First"]

    osc = OscController(reg)
    assert osc.dispatch("/glediator/master/blackout/toggle", 0.0)
    assert engine.blackout is False
