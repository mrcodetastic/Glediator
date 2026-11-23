# ESP32 HUB75 firmware

This standalone Arduino sketch receives Glediator frames, advertises itself on the LAN, and displays completed frames on a HUB75 matrix using `ESP32-HUB75-MatrixPanel-I2S-DMA` with double buffering.

## Libraries

- **ESP32-HUB75-MatrixPanel-I2S-DMA** by mrcodetastic
- **WebSockets** by Markus Sattler (Links2004)
- ESP32 Arduino core (`WiFi`, `WiFiUdp`, `ESPmDNS`)

## Configuration

Copy `config.example.h` to `config.h` (`config.h` is gitignored) and edit your Wi-Fi credentials and panel layout (`PANEL_WIDTH`, `PANEL_HEIGHT`, `PANEL_CHAIN`). If `config.h` does not exist, the sketch falls back to `config.example.h`.

### Virtual Frame vs. Physical Panel Chaining

- Glediator has no knowledge of physical LED wiring, serpentine routing, or chained panel geometry—it only renders and streams the logical **virtual display output** in plain row-major order from `(0, 0)` to `(W - 1, H - 1)`.
- Any physical panel chaining, 2D multi-panel layouts (such as `VirtualMatrixPanel`), scan-rate selection, or wiring transformations must be configured on the ESP32 side via the **ESP32-HUB75-MatrixPanel-I2S-DMA** configuration (`HUB75_I2S_CFG` / virtual mapping classes). Refer to the [ESP32-HUB75-MatrixPanel-DMA documentation](https://github.com/mrcodetastic/ESP32-HUB75-MatrixPanel-DMA) for instructions on chaining and mapping different panel types together.
- **Multiple receivers:** If you connect multiple ESP32 receivers simultaneously, every receiver must use the **same configured virtual matrix dimensions (`W × H`)**, because Glediator produces and broadcasts one uniform output frame size to all connected clients.

## Discovery and WebSocket protocol

See [`docs/protocol.md`](../docs/protocol.md) for full details:

- Periodically broadcasts a v2 `CODETASTIC {...}` UDP beacon on port **20586**.
- Accepts WebSocket connections on port **12345** and sends a `hello` JSON packet declaring dimensions and capabilities (`rgb888`, `delta`, `ack`, `rle`, `brightness`).
- Supports 24-bit RGB888 `81 81` full frames, `81 82` delta rectangles, `81 83` RLE frames, `ack` flow-control replies after `flipDMABuffer()`, and `brightness` commands.
- Shows the IP address on the panel for 5 seconds at boot and displays `NO SIGNAL` after 5 seconds without incoming frames.
