# Glediator User Guide

Repository & latest documentation: [github.com/mrcodetastic/Glediator](https://github.com/mrcodetastic/Glediator)

---

## 1. Workspace Overview

Glediator uses a dual-deck live mixer layout:

- **Source A & Source B:** Each source hosts up to **5 layers**. Layers render top-to-bottom and combine using per-layer blend modes (`Add`, `Subtract`, `Multiply`, `Difference`, `Screen`, `Maximum`, `Normal`, `Lighten`, `Darken`, `Overlay`, `Average`), **Opacity** (`0–100%`), **Brightness** (`0–100%`), and up to **3 chained filters**.
- **Layer Operations:** Drag and drop layers to reorder them, right-click for **Duplicate / Move / Remove / Rename source**, or use **Edit → Copy A to B**, **Copy B to A**, and **Swap A and B**.
- **Layer Inspector (right dock):** Click any layer to edit its parameters live (changes apply immediately), reset defaults, manage its filter chain, or attach audio/LFO modulation (`~` button on any numeric parameter).
- **Preview Modes:** Right-click any preview card to toggle between crisp **Pixels** and **LED dots**, or **Copy frame as PNG** to the clipboard.

---

## 2. Effects & Media

- **39 Built-in Effects:** Includes generative patterns (`Plasma`, `Wave`, `Fire`, `Falling Snow`, `Starfield`, `3D Maze`, `Meta Balls`, `Random Pixel`, etc.), Aurora patterns, `Scrolling Text` (with cross-platform font lookup and palette/solid colors), and `Screen Capture`.
- **Image / GIF (`Image / GIF`):** Plays static images and animated GIFs with `Stretch`, `Fit`, `Fill`, and `Center` modes.
- **Video Player (`Video Player`):** Decodes video files scaled to your matrix dimensions. Defaults to **Fill (Crop)** (aspect-preserving scale cropped on whichever axis overflows to completely fill the panel), with `Fit (Letterbox)` and `Stretch` options.
- **User Effect Plugins:** Drop custom Python effects into `~/.glediator/effects/` (open quickly via **Help → Open Effects Folder**). See [docs/effects.md](https://github.com/mrcodetastic/Glediator/blob/master/docs/effects.md).

---

## 3. Live Show Control

- **Transitions & Looping:** Use the crossfader manually, click **Auto A ↔ B** with `crossfade`, `cut`, `wipe_left`, `wipe_right`, `wipe_up`, `wipe_down`, `dissolve`, or `luma` over `0.1–30 s`, or enable **Loop A ↔ B** with a configurable **Hold** time (`0–300 s`) to alternate continuously between A and B.
- **Master Controls:**
  - **Blackout:** Sends all-black frames to connected LED panels while keeping previews visible with a `BLACKOUT` badge.
  - **Freeze:** Pauses scene rendering and holds the current output frame.
  - **Speed (`0–4×`):** Scales animation speed globally.
  - **Tap BPM (`T`):** Tap 2+ times to clock `lfo_sine` and `lfo_saw` parameter modulations in sync with music.
- **Audio Reactivity & Modulation:**
  - `VU Meter` and `Spectrum Analyser` capture **System Output** (loopback) or **Microphone** audio.
  - Click **`~`** next to any numeric parameter in the **Layer Inspector** to modulate it with `bass`, `mid`, `treble`, `level`, `peak`, `beat`, `lfo_sine`, or `lfo_saw`.
  - *Linux:* ensure a PipeWire/PulseAudio monitor source is enabled for loopback. *macOS:* use a loopback device such as BlackHole.

---

## 4. Presets, Playlists & Projects

- **Scene Presets:** Use **Save as preset…** in the top bar to save both sources and the fader position. Import or export preset banks via **File → Import / Export Presets…**.
- **Playlist / Sequencer (`View → Playlist / Sequencer`):**
  1. Save at least one scene preset in the top bar.
  2. Click **New…** in the Playlist dock to create a playlist.
  3. Pick a saved scene, choose **time** (seconds) or **beats** (audio beat count) and transition settings, then click **+ Add**.
  4. Enable **Loop** or **Shuffle** and click **Play** to automate transitions on the inactive deck.
- **Project Files (`.gled`):** **File → New / Open / Save / Save As** saves your entire show. Glediator autosaves every 60 seconds and offers crash recovery on restart.
- **Undo / Redo:** Full undo stack for layer edits, parameter changes, preset loads, and scene swaps (`Ctrl+Z` / `Ctrl+Y`).

---

## 5. WebSocket Output & ESP32 Hardware

- **Row-Major Virtual Output:** Glediator only sends the logical display frame in plain row-major order from `(0, 0)` to `(W - 1, H - 1)`. Physical panel wiring, chaining, and multi-panel layouts belong in the ESP32 receiver firmware ([esp32-firmware](https://github.com/mrcodetastic/Glediator/tree/master/esp32-firmware) and the [ESP32-HUB75-MatrixPanel-DMA library](https://github.com/mrcodetastic/ESP32-HUB75-MatrixPanel-DMA)). When streaming to multiple receivers, all must share the same matrix dimensions (`W × H`).
- **Panel Size:** Configure matrix dimensions via **File → LED Panel Config…**.
- **Discovery & Protocol v1/v2:** Glediator listens for UDP `CODETASTIC` beacons on port **20586** and streams 24-bit RGB888 frames over WebSocket port **12345** ([protocol.md](https://github.com/mrcodetastic/Glediator/blob/master/docs/protocol.md)).
  - **v2 receivers** report their name, panel size, and capabilities (`delta`, `ack`, `rle`, `brightness`), enabling automatic flow control, delta compression, hardware **Panel brightness**, and one-click **Use device size** on mismatch.
  - Use **Connect manually** for direct IP/host connections; check **Auto** on a device row to reconnect automatically on startup.

---

## 6. Keyboard Shortcuts & OSC

- **Default Shortcuts** (**Help → Keyboard Shortcuts…**):
  - `Space`: Auto transition A ↔ B
  - `B`: Toggle Blackout
  - `F`: Toggle Freeze
  - `T`: Tap BPM
  - `1–9`: Load saved presets 1–9
  - `←` / `→`: Previous / Next playlist entry
  - `Ctrl+Z` / `Ctrl+Y`: Undo / Redo
  - `F1`: Open User Guide
- **OSC Control:** Install `glediator3[osc]` and enable the UDP listener via **Control → OSC Settings…** (default port `9000`, address `/glediator/<action/id>`).
