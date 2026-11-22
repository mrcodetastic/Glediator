from __future__ import annotations

import struct

import numpy as np

from glediator.core.frame import to_rgb888

MARKER_FULL = b"\x81\x81"
MARKER_DELTA = b"\x81\x82"
MARKER_RLE = b"\x81\x83"


def encode_full(frame: np.ndarray) -> bytes:
    """Encode a full row-major RGB888 frame (marker 81 81)."""
    pixels = to_rgb888(frame)
    return MARKER_FULL + pixels.tobytes()


def diff_rects(
    prev: np.ndarray,
    cur: np.ndarray,
    max_rects: int = 8,
    band_rows: int = 8,
) -> list[tuple[int, int, int, int]]:
    """Find changed bounding rectangles (x, y, w, h) between two RGB frames."""
    if prev.shape != cur.shape:
        h, w = cur.shape[:2]
        return [(0, 0, w, h)]
    changed = np.any(prev != cur, axis=2)
    if not np.any(changed):
        return []

    height, _width = changed.shape
    rects: list[tuple[int, int, int, int]] = []
    for y0 in range(0, height, band_rows):
        y1 = min(height, y0 + band_rows)
        band = changed[y0:y1]
        if not np.any(band):
            continue
        ys, xs = np.nonzero(band)
        rx0 = int(xs.min())
        rx1 = int(xs.max()) + 1
        ry0 = y0 + int(ys.min())
        ry1 = y0 + int(ys.max()) + 1
        rects.append((rx0, ry0, rx1 - rx0, ry1 - ry0))

    # Merge touching/adjacent bands with lowest added bounding area.
    while len(rects) > max_rects:
        best_pair = (0, 1)
        best_cost = None
        for i in range(len(rects) - 1):
            ax, ay, aw, ah = rects[i]
            bx, by, bw, bh = rects[i + 1]
            nx0 = min(ax, bx)
            ny0 = min(ay, by)
            nx1 = max(ax + aw, bx + bw)
            ny1 = max(ay + ah, by + bh)
            cost = (nx1 - nx0) * (ny1 - ny0) - (aw * ah + bw * bh)
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_pair = (i, i + 1)
        i, j = best_pair
        ax, ay, aw, ah = rects[i]
        bx, by, bw, bh = rects[j]
        nx0 = min(ax, bx)
        ny0 = min(ay, by)
        nx1 = max(ax + aw, bx + bw)
        ny1 = max(ay + ah, by + bh)
        merged = (nx0, ny0, nx1 - nx0, ny1 - ny0)
        rects = [*rects[:i], merged, *rects[j + 1 :]]

    return rects


def encode_delta(cur: np.ndarray, rects: list[tuple[int, int, int, int]]) -> bytes:
    """Encode RGB888 delta rectangles (marker 81 82)."""
    rgb888 = to_rgb888(cur)
    chunks = [MARKER_DELTA, struct.pack(">H", len(rects))]
    for x, y, w, h in rects:
        chunks.append(struct.pack(">HHHH", x, y, w, h))
        chunks.append(np.ascontiguousarray(rgb888[y : y + h, x : x + w]).tobytes())
    return b"".join(chunks)


def encode_rle(cur: np.ndarray) -> bytes:
    """Encode a full RGB888 frame using 4-byte RLE runs: (u8 run_minus_1, u8 r, u8 g, u8 b)."""
    rgb = to_rgb888(cur).reshape(-1, 3)
    if rgb.shape[0] == 0:
        return MARKER_RLE
    packed = (
        (rgb[:, 0].astype(np.uint32) << 16)
        | (rgb[:, 1].astype(np.uint32) << 8)
        | rgb[:, 2].astype(np.uint32)
    )
    changes = np.nonzero(packed[1:] != packed[:-1])[0] + 1
    starts = np.concatenate(([0], changes))
    ends = np.concatenate((changes, [packed.size]))
    out = bytearray(MARKER_RLE)
    for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
        r, g, b = int(rgb[start, 0]), int(rgb[start, 1]), int(rgb[start, 2])
        remaining = end - start
        while remaining > 0:
            run = min(256, remaining)
            out.append(run - 1)
            out.append(r)
            out.append(g)
            out.append(b)
            remaining -= run
    return bytes(out)


def choose_encoding(
    prev_ref: np.ndarray | None,
    cur: np.ndarray,
    caps: set[str] | list[str] | tuple[str, ...],
) -> tuple[str, bytes | None]:
    """Choose best RGB888 frame encoding ('skip', 'full', 'delta', or 'rle') and payload."""
    if prev_ref is not None and prev_ref.shape == cur.shape and np.array_equal(prev_ref, cur):
        return "skip", None

    full_payload = encode_full(cur)
    best_kind = "full"
    best_payload = full_payload
    threshold = int(len(full_payload) * 0.8)

    cap_set = set(caps)
    if "delta" in cap_set and prev_ref is not None and prev_ref.shape == cur.shape:
        rects = diff_rects(prev_ref, cur)
        if not rects:
            return "skip", None
        delta_payload = encode_delta(cur, rects)
        if len(delta_payload) < threshold and len(delta_payload) < len(best_payload):
            best_kind = "delta"
            best_payload = delta_payload

    if "rle" in cap_set:
        rle_payload = encode_rle(cur)
        if len(rle_payload) < threshold and len(rle_payload) < len(best_payload):
            best_kind = "rle"
            best_payload = rle_payload

    return best_kind, best_payload
