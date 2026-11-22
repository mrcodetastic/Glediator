# Glediator User Guide

## Workspace

Glediator uses a dual-deck live mixer layout:

- **Source A & Source B:** Each source hosts up to 5 layered effects. Layers render top-to-bottom and combine using per-layer blend modes (`Add`, `Subtract`, `Multiply`, `Difference`, `Screen`, `Maximum`, `Normal`, `Lighten`, `Darken`, `Overlay`, `Average`), opacity (`0–100%`), brightness (`0–100%`), and up to 3 chained filters.
- **Layer Inspector dock:** Select any layer to edit its parameters live, reset defaults, configure its filter chain, or bind audio/LFO modulation (`~` button on any numeric parameter).
- **Final Output & Master:** Crossfade manually between A and B or trigger timed transitions (`crossfade`, `cut`, `wipe_*`, `dissolve`, `luma`), toggle **Blackout** / **Freeze**, adjust master **Speed** (`0–4×`), or tap tempo (`Tap BPM`).
- **Preview modes:** Right-click any preview card to toggle between crisp **Pixels** and **LED dots** or copy the current frame as PNG.

## Presets, Playlists & Projects

- **Scene Presets:** Save/load full dual-source states in the top bar, or import/export preset banks via **File → Import/Export Presets…**.
- **Playlist / Sequencer dock (`View → Playlist / Sequencer`):** Step through presets by elapsed time or beat count with optional loop and non-repeating shuffle.
- **Projects (`.gled`):** Save and open complete shows via **File → New / Open / Save / Save As**. Glediator autosaves every 60 seconds and offers crash recovery on restart.

## WebSocket Output & Firmware

- Glediator always sends pixels in **row-major order** from `(0, 0)` to `(W - 1, H - 1)`. Panel chaining and wiring orientation belong to the receiver firmware.
- Discovered `CODETASTIC` receivers appear automatically in **Network Output** with live protocol version (`v1` / `v2`), FPS, bandwidth, skipped frames, and ack latency.
- If a v2 receiver reports a different panel size, Glediator halts sending and offers a one-click **Use device size** button.

## Audio & External Control

- Audio-reactive effects and parameter modulations (`level`, `peak`, `bass`, `mid`, `treble`, `beat`) use `soundcard` loopback (`System Output`) or `Microphone`.
  - **Linux:** Ensure a PipeWire/PulseAudio monitor source is available for loopback.
  - **macOS:** Use a virtual loopback device such as BlackHole if capturing system output.
- **Keyboard shortcuts:** `Space` (auto transition), `B` (blackout), `F` (freeze), `T` (tap tempo), `1–9` (presets), `←/→` (playlist). See **Help → Keyboard Shortcuts…**.
- **MIDI & OSC:** Install `glediator3[midi]` and/or `glediator3[osc]` and configure via **Control → MIDI & OSC Settings…**.
