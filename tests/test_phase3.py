from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from glediator.core.config import EngineConfig
from glediator.core.engine import RenderEngine
from glediator.core.filters import FILTER_NAMES, apply_filter_chain, sanitize_filter_chain
from glediator.core.pipeline import mix
from glediator.core.project import (
    acquire_session_lock,
    apply_project_to_config,
    build_project_payload,
    load_project,
    merge_imported_presets,
    release_session_lock,
    save_project,
)
from glediator.core.scene import Scene
from glediator.effects import create_effect, effect_names, load_effects, plugin_warnings
from glediator.generators.palettes import colorize, palette_names, set_custom_palettes


def test_blend_modes_and_opacity():
    base = np.full((4, 4, 3), 100, dtype=np.uint8)
    layer = np.full((4, 4, 3), 200, dtype=np.uint8)

    assert np.array_equal(mix(base, layer, "Normal", opacity=0), base)
    assert np.array_equal(mix(base, layer, "Normal", opacity=100), layer)
    assert np.all(mix(base, layer, "Darken", opacity=100) == 100)
    assert np.all(mix(base, layer, "Lighten", opacity=100) == 200)
    assert np.all(mix(base, layer, "Average", opacity=100) == 150)
    ov = mix(base, layer, "Overlay", opacity=100)
    assert ov.dtype == np.uint8 and ov.shape == (4, 4, 3)


def test_filter_chain_odd_sizes_mirror_trails_and_migration():
    frame = np.zeros((9, 17, 3), dtype=np.uint8)
    frame[:, :5] = (255, 40, 10)
    state: dict = {}
    for fname in FILTER_NAMES:
        chain = sanitize_filter_chain([{"name": fname, "params": {}}])
        out = apply_filter_chain(frame, chain, 0.25, state)
        assert out.shape == (9, 17, 3)
        assert out.dtype == np.uint8

    mirrored = apply_filter_chain(frame, [{"name": "Mirror", "params": {"axis": "Horizontal"}}], 0.0)
    assert np.array_equal(mirrored[:, 0], mirrored[:, -1])

    t_state: dict = {}
    bright = np.full((9, 17, 3), 200, dtype=np.uint8)
    black = np.zeros((9, 17, 3), dtype=np.uint8)
    apply_filter_chain(bright, [{"name": "Trails", "params": {"decay": 0.5}}], 0.0, t_state)
    decayed = apply_filter_chain(black, [{"name": "Trails", "params": {"decay": 0.5}}], 0.1, t_state)
    assert np.all(decayed == 100)

    scene = Scene("legacy", 16, 8)
    scene.restore({
        "name": "legacy",
        "layers": [{"generator": "Plasma", "enabled": True, "configured": True, "filter": "Invert"}],
    })
    assert scene.layers[0].filters == [{"name": "Invert", "params": {}}]


def test_custom_palettes():
    set_custom_palettes({"MyCustom": ["#ff0000", "#0000ff"]})
    try:
        assert "MyCustom" in palette_names()
        cols = colorize(np.array([0.0, 1.0]), "MyCustom")
        assert cols.tolist() == [[255, 0, 0], [0, 0, 255]]
        fallback = colorize(np.array([0.5]), "NoSuchPalette")
        assert fallback.shape == (1, 3)
    finally:
        set_custom_palettes({})


def test_image_player_animated_gif(tmp_path: Path):
    gif_path = tmp_path / "anim.gif"
    frames = [
        Image.new("RGB", (8, 8), (255, 0, 0)),
        Image.new("RGB", (8, 8), (0, 255, 0)),
        Image.new("RGB", (8, 8), (0, 0, 255)),
    ]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)

    fx = create_effect("Image / GIF")
    fx.configure({"path": str(gif_path), "fit": "Stretch", "speed": 1.0, "loop": True, "smoothing": "Nearest"})
    f0 = fx.drawFrame(16, 8, 0.01)
    f1 = fx.drawFrame(16, 8, 0.12)
    assert f0.shape == (8, 16, 3)
    assert f0[0, 0, 0] > 200 and f1[0, 0, 1] > 200

    fx.configure({"path": str(tmp_path / "missing.gif")})
    miss = fx.drawFrame(16, 8, 0.0)
    assert np.count_nonzero(miss) == 0
    assert "not found" in fx.last_error


def test_user_effect_plugins_and_fault_isolation(tmp_path: Path, monkeypatch):
    (tmp_path / "good_plugin.py").write_text(
        "import numpy as np\n"
        "from glediator.effects.support import ConfiguredEffect\n"
        "class TestPluginEffect(ConfiguredEffect):\n"
        "    name = 'Test Plugin Glow'\n"
        "    description = 'Valid plugin'\n"
        "    def drawFrame(self, w, h, t, audio_state=None):\n"
        "        return np.full((h, w, 3), 12, dtype=np.uint8)\n",
        encoding="utf-8",
    )
    (tmp_path / "broken_plugin.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "clash_plugin.py").write_text(
        "import numpy as np\n"
        "from glediator.effects.support import ConfiguredEffect\n"
        "class ClashEffect(ConfiguredEffect):\n"
        "    name = 'Plasma'\n"
        "    description = 'Clash'\n"
        "    def drawFrame(self, w, h, t, audio_state=None):\n"
        "        return np.zeros((h, w, 3), dtype=np.uint8)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GLEDIATOR_EFFECTS_PATH", str(tmp_path))
    try:
        load_effects(reload=True)
        assert "Test Plugin Glow" in effect_names()
        warnings = plugin_warnings()
        assert any("broken_plugin.py" in w for w in warnings)
        assert any("clashes" in w for w in warnings)
    finally:
        monkeypatch.delenv("GLEDIATOR_EFFECTS_PATH", raising=False)
        load_effects(reload=True)


def test_layer_operations_and_timings():
    engine = RenderEngine(EngineConfig(width=16, height=8))
    dup1 = engine.duplicate_layer("left", 0)
    assert dup1 == 1
    assert engine.duplicate_layer("left", 0) == 2
    assert engine.duplicate_layer("left", 0) == 3
    assert engine.duplicate_layer("left", 0) == 4
    assert engine.duplicate_layer("left", 0) is None

    engine.set_generator("right", 0, "Wave")
    engine.copy_scene("right", "left")
    assert engine.scene_snapshot("left")["layers"][0]["generator"] == "Wave"

    engine.set_generator("left", 0, "Fire")
    engine.swap_scenes()
    assert engine.scene_snapshot("right")["layers"][0]["generator"] == "Fire"
    assert engine.scene_snapshot("left")["layers"][0]["generator"] == "Wave"

    engine.rename_scene("left", "Main Stage")
    assert engine.scene_snapshot("left")["name"] == "Main Stage"

    engine.step(0.1)
    st = engine.status()
    assert st.frame_time_ms >= 0.0
    assert st.layer_times_ms[("left", 0)] >= 0.0


def test_project_files_preset_merge_and_lock(tmp_path: Path):
    cfg = EngineConfig(width=40, height=20, presets=[{"name": "Intro", "state": {}}])
    engine = RenderEngine(cfg)
    engine.set_generator("left", 0, "Wave")

    proj_path = tmp_path / "show.gled"
    payload = build_project_payload(cfg, engine.export_state(), include_devices=False)
    assert "devices" not in payload
    save_project(proj_path, payload)

    loaded = load_project(proj_path)
    cfg2 = EngineConfig()
    live = apply_project_to_config(loaded, cfg2)
    assert cfg2.width == 40 and cfg2.height == 20
    assert live["left"]["layers"][0]["generator"] == "Wave"

    merged = merge_imported_presets(
        [{"name": "Intro", "state": {}}],
        [{"name": "Intro", "state": {}}, {"name": "Outro", "state": {}}],
    )
    assert [p["name"] for p in merged] == ["Intro", "Intro (2)", "Outro"]

    lock = tmp_path / "session.lock"
    assert acquire_session_lock(lock) is False
    assert acquire_session_lock(lock) is True
    release_session_lock(lock)
    assert not lock.exists()


def test_video_player_fill_crop_and_playback(tmp_path: Path):
    import time

    import av

    from glediator.effects.video_player import apply_video_fit, compute_video_resize

    # 16:9 source (160x90) -> 32x32 square target with Fill (Crop): scales height=32, width=57, crops center 32x32
    sw, sh = compute_video_resize(160, 90, 32, 32, "Fill (Crop)")
    assert sh == 32 and sw > 32
    wide = np.zeros((sh, sw, 3), dtype=np.uint8)
    wide[:, :10] = (255, 0, 0)
    wide[:, sw // 2 - 4 : sw // 2 + 4] = (0, 255, 0)
    cropped = apply_video_fit(wide, 32, 32, "Fill (Crop)")
    assert cropped.shape == (32, 32, 3)
    assert np.count_nonzero(cropped[..., 1]) > 0
    assert np.count_nonzero(cropped[..., 0]) == 0

    # Real video encode + decode via PyAV
    vid_path = tmp_path / "sample.mp4"
    with av.open(str(vid_path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=24)
        stream.width = 96
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        for _ in range(4):
            arr = np.full((48, 96, 3), 200, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            for pkt in stream.encode(frame):
                container.mux(pkt)
        for pkt in stream.encode():
            container.mux(pkt)

    fx = create_effect("Video Player")
    try:
        fx.configure({"path": str(vid_path), "fit": "Fill (Crop)", "speed": 1.0, "loop": True})
        deadline = time.monotonic() + 2.0
        out = np.zeros((32, 32, 3), dtype=np.uint8)
        while time.monotonic() < deadline:
            out = fx.drawFrame(32, 32, 0.0)
            if np.count_nonzero(out) > 0:
                break
            time.sleep(0.03)
        assert out.shape == (32, 32, 3)
        assert np.mean(out) > 150
    finally:
        fx.cleanup()
