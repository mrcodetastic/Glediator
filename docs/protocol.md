# MrCodetastic WebSocket Protocol (v1 & v2)

WebSocket over TCP (default port `12345`) is the sole pixel transport between the Glediator desktop studio and ESP32 HUB75 receivers. Every WebSocket binary message carries one complete atomic update (full, delta, or RLE), and text messages carry optional v2 JSON control frames.

## Pixel layout

Pixels are **always row-major** from `(0, 0)` (top-left) to `(W - 1, H - 1)` (bottom-right), at flat index `i = y * W + x`. Host software never applies serpentine, rotation, or panel-chaining transforms; physical panel wiring is handled on the receiver.

Each pixel is RGB565, big-endian (`uint16` high byte first):

```
Byte 0: R4 R3 R2 R1 R0 G5 G4 G3
Byte 1: G2 G1 G0 B4 B3 B2 B1 B0
```

## Binary messages (app -> device)

All binary messages begin with `0x81` followed by a message-type byte:

### `81 81` — Full frame (v1 and v2)

```
+------+------+-------------------------------------------+
| 0x81 | 0x81 | W * H * 2 bytes: row-major RGB565 pixels  |
+------+------+-------------------------------------------+
```

Worked hex example for a `4 x 2` panel with `(0, 0)` pure red (`0xF800`), `(3, 0)` pure green (`0x07E0`), `(1, 1)` pure blue (`0x001F`), and black (`0x0000`) elsewhere:

```
81 81
F8 00  00 00  00 00  07 E0
00 00  00 1F  00 00  00 00
```

### `81 82` — Delta frame (v2, requires `"delta"` cap)

Updates `n_rects` rectangular regions inside the receiver's persisted framebuffer:

```
+------+------+-------------+--------------------------------------------+
| 0x81 | 0x82 | u16 n_rects | rect[0] ... rect[n_rects - 1]              |
+------+------+-------------+--------------------------------------------+

Each rect (all integers big-endian u16):
+-------+-------+-------+-------+----------------------------------------+
| u16 x | u16 y | u16 w | u16 h | w * h * 2 bytes: row-major RGB565      |
+-------+-------+-------+-------+----------------------------------------+
```

Worked hex example updating a `2 x 1` rectangle at `(x=1, y=1)` to white (`0xFFFF`) and blue (`0x001F`):

```
81 82
00 01                 # n_rects = 1
00 01 00 01           # x = 1, y = 1
00 02 00 01           # w = 2, h = 1
FF FF 00 1F           # pixels (1,1) and (2,1)
```

### `81 83` — RLE frame (v2, optional `"rle"` cap)

Run-length encoded row-major RGB565 covering all `W * H` pixels:

```
+------+------+---------------------------------------------------------+
| 0x81 | 0x83 | Repeated (u8 run_minus_1, u16 rgb565_be) 3-byte records |
+------+------+---------------------------------------------------------+
```

`run_minus_1 = 0..255` encodes `1..256` identical consecutive pixels.

## Text control messages (v2 JSON)

- **Device -> App (`hello`):** sent once right after WebSocket connection opens:
  ```json
  {"type":"hello","v":2,"name":"codetastic-panel","w":64,"h":32,"caps":["delta","ack","brightness"]}
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

## Capability negotiation and backward compatibility

```
App                                      Device
 |--- WebSocket Connect ------------------>|
 |<-- hello JSON (if v2, within 500 ms) ---|
 |                                         |
 |  [No hello in 500 ms -> v1 fallback:    |
 |   81 81 full frames only, no acks]      |
 |                                         |
 |  [If v2 w,h != app W,H -> mismatch:     |
 |   stop sending, show warning in UI]     |
 |                                         |
 |--- 81 81 Initial Full Frame ----------->|
 |<-- {"type":"ack","n":1} ----------------|  (if "ack" in caps)
 |--- 81 82 Delta / 81 81 Full ----------->|  (max 2 in-flight if "ack")
```

- **v1 firmware** ignores unknown text messages and never sends `hello`; the app falls back to v1 open-loop `81 81` full frames after 500 ms.
- **v2 firmware** always accepts `81 81` full frames, so v1 apps continue working unchanged.
- The first frame after connecting or resizing is always `81 81`.

## UDP Discovery Beacon (UDP port `20586`)

- **v1 payload:** `CODETASTIC`
- **v2 payload:** `CODETASTIC {"v":2,"name":"codetastic-panel","w":64,"h":32,"port":12345}`

Parsers accept both; malformed JSON after `CODETASTIC` is treated as v1.

## Measured performance

Run `python scripts/ws_bench.py --host <ip>` to benchmark v1 full, v2 full+ack, and v2 delta+ack on target hardware.
