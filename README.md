# Glediator Python / Qt6 Studio

A real-time LED matrix visualizer and dual-deck mixer built with Python, NumPy, and PySide6. It pairs a UI-independent rendering core (two 5-layer scenes, 47 effects, parameterised filters, audio beat/BPM modulation, playlist sequencer, undo/redo, and `.gled` projects) with a backward-compatible WebSocket v1/v2 receiver protocol for ESP32 HUB75 panels (`esp32-firmware/`).

![App In Action](app.gif)

## Quick Start

Requires Python 3.10+.

```bash
python -m venv .venv
. .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -e .
python main.py
```

Optional extras: `glediator3[osc]`, `glediator3[camera]`.

## Key Features

- **Dual-Deck 5-Layer Mixing:** Source A and Source B with 11 blend modes, per-layer opacity/brightness, 12 parameterised filters (up to 3 chained), live docked Layer Inspector, and undo/redo (`Ctrl+Z` / `Ctrl+Y`).
- **47 Built-in Effects + Plugins:** 28 Aurora patterns, generative effects, Wave, Scrolling Text (cross-platform fonts & palettes), Screen Capture, Image/GIF player, Video Player (aspect-preserving fill crop), optional Webcam, and user plugins from `~/.glediator/effects/`.
- **Live Show Control:** Transition modes (`crossfade`, `cut`, `wipe_*`, `dissolve`, `luma`), blackout/freeze/speed master bus, bass/mid/treble & beat/BPM extraction, tap tempo, audio/LFO parameter modulation, timed/beat playlists, keyboard shortcuts, and optional OSC.
- **Row-Major WebSocket v1/v2 Link:** Sends plain row-major RGB565 pixels (`(0,0)` to `(W-1,H-1)`) over WebSocket port `12345` with UDP `CODETASTIC` discovery (`20586`), size-mismatch protection, ack flow control, and delta/RLE compression. Physical panel wiring is handled by the ESP32 firmware.

## Documentation

- [User Guide](docs/user-guide.md)
- [WebSocket Protocol v1 & v2](docs/protocol.md)
- [Writing Custom Effects](docs/effects.md)
- [ESP32 HUB75 Firmware](esp32-firmware/README.md)
- [Contributing](CONTRIBUTING.md)

## Development

```bash
pip install -e ".[dev]"
ruff check glediator tests scripts
QT_QPA_PLATFORM=offscreen pytest -q
```
