# MrCodetastic WebSocket Protocol (RGB888)

WebSocket over TCP (default port `12345`) is the sole pixel transport between the Glediator desktop studio and ESP32 HUB75 receivers. Every WebSocket binary message carries one complete atomic update (full, delta, or RLE) in full 24-bit RGB888, and text messages carry optional v2 JSON control frames.

## Pixel layout

Pixels are **always row-major** from `(0, 0)` (top-left) to `(W - 1, H - 1)` (bottom-right), at flat pixel index `i = y * W + x`. Host software never applies serpentine, rotation, or panel-chaining transforms; physical panel wiring is handled on the receiver.

Each pixel is **24-bit RGB888** (3 consecutive bytes):

```
Byte 0: R (0..255)
Byte 1: G (0..255)
Byte 2: B (0..255)
```

## Binary messages (app -> device)

All binary messages begin with `0x81` followed by a message-type byte:

### `81 81` — Full frame (v1 and v2)

```
+------+------+-------------------------------------------+
| 0x81 | 0x81 | W * H * 3 bytes: row-major RGB888 pixels  |
+------+------+-------------------------------------------+
```

Worked hex example for a `4 x 2` panel with `(0, 0)` pure red (`FF 00 00`), `(3, 0)` pure green (`00 FF 00`), `(1, 1)` pure blue (`00 00 FF`), and black (`00 00 00`) elsewhere:

```
81 81
FF 00 00  00 00 00  00 00 00  00 FF 00
00 00 00  00 00 FF  00 00 00  00 00 00
```

### `81 82` — Delta frame (v2, requires `"delta"` cap)

Updates `n_rects` rectangular regions inside the receiver's persisted framebuffer:

```
+------+------+-------------+--------------------------------------------+
| 0x81 | 0x82 | u16 n_rects | rect[0] ... rect[n_rects - 1]              |
+------+------+-------------+--------------------------------------------+

Each rect (geometry fields big-endian u16):
+-------+-------+-------+-------+----------------------------------------+
| u16 x | u16 y | u16 w | u16 h | w * h * 3 bytes: row-major RGB888      |
+-------+-------+-------+-------+----------------------------------------+
```

Worked hex example updating a `2 x 1` rectangle at `(x=1, y=1)` to white (`FF FF FF`) and blue (`00 00 FF`):

```
81 82
00 01                 # n_rects = 1
00 01 00 01           # x = 1, y = 1
00 02 00 01           # w = 2, h = 1
FF FF FF 00 00 FF     # pixels (1,1) and (2,1)
```

### `81 83` — RLE frame (v2, optional `"rle"` cap)

Run-length encoded row-major RGB888 covering all `W * H` pixels:

```
+------+------+--------------------------------------------------------------+
| 0x81 | 0x83 | Repeated (u8 run_minus_1, u8 r, u8 g, u8 b) 4-byte records   |
+------+------+--------------------------------------------------------------+
```

`run_minus_1 = 0..255` encodes `1..256` identical consecutive pixels.

## Text control messages (v2 JSON)

- **Device -> App (`hello`):** sent once right after WebSocket connection opens:
  ```json
  {"type":"hello","v":2,"name":"codetastic-panel","w":64,"h":32,"caps":["rgb888","delta","ack","rle","brightness"]}
  ```
- **Device -> App (`ack`):** sent after `flipDMABuffer()` presents a frame (requires `"ack"` cap):
  ```json
  {"type":"ack","n":123}
  ```
  `n` is the cumulative count of displayed frames on the current connection.
- **App -> Device (`brightness`):** requires `"brightness"` cap:
  ```json
  {"type":"brightness","value":180}
  ```

## Capability negotiation

```
App                                      Device
 |--- WebSocket Connect ------------------>|
 |<-- hello JSON (if v2, within 500 ms) ---|
 |                                         |
 |  [No hello in 500 ms -> v1 fallback:    |
 |   81 81 full RGB888 frames, no acks]    |
 |                                         |
 |  [If v2 w,h != app W,H -> mismatch:     |
 |   stop sending, show warning in UI]     |
 |                                         |
 |--- 81 81 Initial Full Frame ----------->|
 |<-- {"type":"ack","n":1} ----------------|  (if "ack" in caps)
 |--- 81 82 Delta / 81 81 Full ----------->|  (max 2 in-flight if "ack")
```

- **v1 receivers** ignore unknown text messages and never send `hello`; the app falls back to v1 open-loop `81 81` full RGB888 frames after 500 ms.
- **v2 receivers** accept `81 81` full frames, `81 82` deltas (when `"delta"` cap is advertised), and `81 83` RLE frames (when `"rle"` cap is advertised).
- The first frame after connecting or resizing is always `81 81`.

## UDP Discovery Beacon (UDP port `20586`)

- **v1 payload:** `CODETASTIC`
- **v2 payload:** `CODETASTIC {"v":2,"name":"codetastic-panel","w":64,"h":32,"port":12345}`

Parsers accept both; malformed JSON after `CODETASTIC` is treated as v1.

## Measured performance

Run `python scripts/ws_bench.py --host <ip>` to benchmark full, full+ack, and delta+ack on target hardware.
