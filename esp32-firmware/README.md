# ESP32 HUB75 firmware

This standalone Arduino sketch receives Glediator frames, advertises itself on the LAN, and displays completed frames on a HUB75 matrix using `ESP32-HUB75-MatrixPanel-I2S-DMA` with double buffering.

## Libraries

- **ESP32-HUB75-MatrixPanel-I2S-DMA** by mrcodetastic
- **WebSockets** by Markus Sattler (Links2004)
- ESP32 Arduino core (`WiFi`, `WiFiUdp`, `ESPmDNS`)

## Configuration

Copy `config.example.h` to `config.h` (`config.h` is gitignored) and edit your Wi-Fi credentials and panel layout (`PANEL_WIDTH`, `PANEL_HEIGHT`, `PANEL_CHAIN`). If `config.h` does not exist, the sketch falls back to `config.example.h`.

The Python app always sends pixels in row-major order from `(0, 0)` to `(W - 1, H - 1)` where `W = PANEL_WIDTH * PANEL_CHAIN` and `H = PANEL_HEIGHT`. Any physical panel chaining or wiring transform is handled in the receiver.

## Discovery and WebSocket protocol

See [`docs/protocol.md`](../docs/protocol.md) for full details:

- Periodically broadcasts a v2 `CODETASTIC {...}` UDP beacon on port **20586**.
- Accepts WebSocket connections on port **12345** and sends a `hello` JSON packet declaring dimensions and capabilities (`delta`, `ack`, `rle`, `brightness`).
- Supports `81 81` full frames (v1 & v2), `81 82` delta rectangles, `81 83` RLE frames, `ack` flow-control replies after `flipDMABuffer()`, and `brightness` commands.
- Shows the IP address on the panel for 5 seconds at boot and displays `NO SIGNAL` after 5 seconds without incoming frames.
