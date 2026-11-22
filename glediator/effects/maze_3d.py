import math

import numpy as np
from PIL import Image, ImageDraw

from glediator.effects.support import ConfiguredEffect
from glediator.generators.palettes import PALETTE_NAMES, colorize

# Cardinals: 0=North (+Z), 1=East (+X), 2=South (-Z), 3=West (-X)
_DIRS = ((0, 1), (1, 0), (0, -1), (-1, 0))


class Maze3DEffect(ConfiguredEffect):
    name = "3D Maze"
    description = "Endless first-person 3D wireframe maze walking through corridors and side doors."
    category = "Generative"
    settings = {
        "speed": ("float", 1.2, 0.2, 5.0, 0.1),
        "depth": ("int", 6, 3, 10, 1),
        "palette": ("choice", "Neon", PALETTE_NAMES, "", ""),
    }

    def __init__(self) -> None:
        super().__init__()
        self._cells: dict[tuple[int, int], set[int]] = {}
        self._pos = (0, 0)
        self._heading = 0
        self._step_phase = 0.0
        self._action = "forward"  # "forward", "turn_left", "turn_right"
        self._turn_target = 0
        self._last_time: float | None = None
        self._reset_maze()

    def _reset_maze(self) -> None:
        self._cells = {(0, 0): {0, 2}}
        self._pos = (0, 0)
        self._heading = 0
        self._step_phase = 0.0
        self._action = "forward"
        self._turn_target = 0
        self._ensure_corridor_ahead(10)

    def _carve_passage(self, cell: tuple[int, int], direction: int) -> tuple[int, int]:
        dx, dz = _DIRS[direction]
        nxt = (cell[0] + dx, cell[1] + dz)
        self._cells.setdefault(cell, set()).add(direction)
        self._cells.setdefault(nxt, set()).add((direction + 2) % 4)
        return nxt

    def _carve_side_alcove(self, cell: tuple[int, int], direction: int) -> None:
        cur = cell
        steps = int(self._rng.integers(1, 3))
        for _ in range(steps):
            nx, nz = cur[0] + _DIRS[direction][0], cur[1] + _DIRS[direction][1]
            if (nx, nz) in self._cells:
                break
            cur = self._carve_passage(cur, direction)

    def _ensure_corridor_ahead(self, lookahead: int) -> None:
        """Guarantee carved walkable cells and side 'doors' ahead of the camera."""
        cx, cz = self._pos
        heading = self._heading
        cur = (cx, cz)
        for step_idx in range(lookahead):
            exits = self._cells.setdefault(cur, set())
            forward_dir = heading
            left_dir = (heading - 1) % 4
            right_dir = (heading + 1) % 4

            candidates = []
            for d in (forward_dir, left_dir, right_dir):
                dx, dz = _DIRS[d]
                nb = (cur[0] + dx, cur[1] + dz)
                if nb not in self._cells:
                    candidates.append(d)

            if forward_dir in exits:
                next_dir = forward_dir
            elif candidates:
                if forward_dir in candidates and self._rng.random() < 0.62:
                    next_dir = forward_dir
                else:
                    next_dir = int(self._rng.choice(candidates))
            else:
                open_fwd = [d for d in (forward_dir, left_dir, right_dir) if d in exits]
                next_dir = open_fwd[0] if open_fwd else forward_dir

            for side_dir in (left_dir, right_dir):
                chance = 0.42 if step_idx > 0 else 0.5
                if side_dir != next_dir and side_dir not in exits and self._rng.random() < chance:
                    self._carve_side_alcove(cur, side_dir)

            cur = self._carve_passage(cur, next_dir)
            heading = next_dir

        cutoff = lookahead + 6
        stale = [k for k in self._cells if abs(k[0] - cx) > cutoff or abs(k[1] - cz) > cutoff]
        for k in stale:
            del self._cells[k]

    def _pick_next_action(self) -> None:
        self._ensure_corridor_ahead(10)
        exits = self._cells.get(self._pos, set())
        fwd = self._heading
        left = (self._heading - 1) % 4
        right = (self._heading + 1) % 4

        options: list[tuple[str, int, float]] = []
        if fwd in exits:
            options.append(("forward", fwd, 1.4))
        if left in exits:
            options.append(("turn_left", left, 1.0))
        if right in exits:
            options.append(("turn_right", right, 1.0))

        if not options:
            self._carve_passage(self._pos, fwd)
            options.append(("forward", fwd, 1.0))

        weights = np.array([w for _, _, w in options], dtype=np.float64)
        weights /= weights.sum()
        idx = int(self._rng.choice(len(options), p=weights))
        act, nxt_dir, _ = options[idx]
        self._action = act
        self._turn_target = nxt_dir

    def _advance(self, delta: float) -> None:
        self._step_phase += delta
        while self._step_phase >= 1.0:
            self._step_phase -= 1.0
            if self._action in ("turn_left", "turn_right"):
                self._heading = self._turn_target
            dx, dz = _DIRS[self._heading]
            self._pos = (self._pos[0] + dx, self._pos[1] + dz)
            self._ensure_corridor_ahead(10)
            self._pick_next_action()

    def _camera_pose(self) -> tuple[float, float, float]:
        base_yaw = self._heading * (math.pi * 0.5)
        t = self._step_phase
        smooth = t * t * (3.0 - 2.0 * t)
        if self._action == "turn_left":
            yaw = base_yaw - smooth * (math.pi * 0.5)
            dx, dz = _DIRS[self._turn_target]
            return self._pos[0] + dx * smooth * 0.25, self._pos[1] + dz * smooth * 0.25, yaw
        if self._action == "turn_right":
            yaw = base_yaw + smooth * (math.pi * 0.5)
            dx, dz = _DIRS[self._turn_target]
            return self._pos[0] + dx * smooth * 0.25, self._pos[1] + dz * smooth * 0.25, yaw

        dx, dz = _DIRS[self._heading]
        return self._pos[0] + dx * t, self._pos[1] + dz * t, base_yaw

    def _visible_cells(self, max_depth: int) -> set[tuple[int, int]]:
        """Collect cells strictly along the active forward (and turning) corridor ray."""
        visible: set[tuple[int, int]] = set()
        ray_dirs = [self._heading]
        if self._action in ("turn_left", "turn_right") and self._turn_target not in ray_dirs:
            ray_dirs.append(self._turn_target)

        for walk_dir in ray_dirs:
            cur = self._pos
            for _ in range(max_depth + 1):
                visible.add(cur)
                exits = self._cells.get(cur, set())
                if walk_dir not in exits:
                    break
                dx, dz = _DIRS[walk_dir]
                cur = (cur[0] + dx, cur[1] + dz)
        return visible

    @staticmethod
    def _clip_and_project(
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        cam_x: float,
        cam_z: float,
        sin_y: float,
        cos_y: float,
        cx: float,
        cy: float,
        focal: float,
    ) -> tuple[float, float, float, float, float] | None:
        def to_cam(pt: tuple[float, float, float]) -> tuple[float, float, float]:
            dx = pt[0] - cam_x
            dz = pt[2] - cam_z
            vx = dx * cos_y - dz * sin_y
            vz = dx * sin_y + dz * cos_y
            return vx, pt[1], vz

        a = to_cam(p0)
        b = to_cam(p1)
        z_near = 0.14
        if a[2] < z_near and b[2] < z_near:
            return None
        if a[2] < z_near:
            t = (z_near - a[2]) / max(1e-6, b[2] - a[2])
            a = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), z_near)
        elif b[2] < z_near:
            t = (z_near - b[2]) / max(1e-6, a[2] - b[2])
            b = (b[0] + t * (a[0] - b[0]), b[1] + t * (a[1] - b[1]), z_near)

        avg_z = 0.5 * (a[2] + b[2])
        sx0 = cx + (a[0] / a[2]) * focal
        sy0 = cy - (a[1] / a[2]) * focal
        sx1 = cx + (b[0] / b[2]) * focal
        sy1 = cy - (b[1] / b[2]) * focal
        return sx0, sy0, sx1, sy1, avg_z

    def drawFrame(self, width, height, time_seconds, audio_state=None):
        p = self.parameters
        speed = float(p.get("speed", 1.2))
        max_depth = int(p.get("depth", 6))
        palette = str(p.get("palette", "Neon"))

        now = float(time_seconds)
        dt = 1.0 / 30.0 if self._last_time is None else max(0.0, min(0.25, now - self._last_time))
        self._last_time = now
        self._advance(dt * speed * 1.15)

        cam_x, cam_z, yaw = self._camera_pose()
        sin_y = math.sin(yaw)
        cos_y = math.cos(yaw)
        cx = (width - 1) * 0.5
        cy = (height - 1) * 0.5
        focal = min(width * 0.58, height * 0.92)

        wall_h = 0.45
        door_lintel = 0.24
        segments: list[tuple[tuple[float, float, float], tuple[float, float, float], float]] = []
        drawn_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()

        for gx, gz in self._visible_cells(max_depth):
            exits = self._cells.get((gx, gz))
            if exits is None:
                continue
            for d, (dx, dz) in enumerate(_DIRS):
                nb = (gx + dx, gz + dz)
                edge_key = tuple(sorted(((gx, gz), nb)))
                if edge_key in drawn_edges:
                    continue
                drawn_edges.add(edge_key)

                ex, ez = gx + dx * 0.5, gz + dz * 0.5
                tx, tz = (-dz * 0.5, dx * 0.5)
                x0, z0 = ex - tx, ez - tz
                x1, z1 = ex + tx, ez + tz

                if d not in exits:
                    segments.append(((x0, -wall_h, z0), (x1, -wall_h, z1), 1.0))
                    segments.append(((x0, wall_h, z0), (x1, wall_h, z1), 1.0))
                    segments.append(((x0, -wall_h, z0), (x0, wall_h, z0), 0.72))
                    segments.append(((x1, -wall_h, z1), (x1, wall_h, z1), 0.72))
                else:
                    # Only draw doorway jambs/lintels on perpendicular side openings or turns
                    is_side_door = d != self._heading and d != (self._heading + 2) % 4
                    if is_side_door:
                        segments.append(((x0, door_lintel, z0), (x1, door_lintel, z1), 0.85))
                        segments.append(((x0, -wall_h, z0), (x0, door_lintel, z0), 0.65))
                        segments.append(((x1, -wall_h, z1), (x1, door_lintel, z1), 0.65))

        projected: list[tuple[float, float, float, float, float, float]] = []
        clip_dist = float(max_depth) + 1.0
        for p0, p1, weight in segments:
            proj = self._clip_and_project(p0, p1, cam_x, cam_z, sin_y, cos_y, cx, cy, focal)
            if proj is None:
                continue
            sx0, sy0, sx1, sy1, avg_z = proj
            if avg_z <= clip_dist:
                projected.append((avg_z, sx0, sy0, sx1, sy1, weight))

        projected.sort(key=lambda item: item[0], reverse=True)

        img = Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        if projected:
            depths = np.clip(1.0 - np.array([item[0] for item in projected], dtype=np.float32) / clip_dist, 0.08, 1.0)
            palette_rgb = colorize(depths, palette).astype(np.float32)
            for idx, (_, sx0, sy0, sx1, sy1, weight) in enumerate(projected):
                fade = float(depths[idx]) * weight
                col = tuple(int(max(0, min(255, round(c * (0.25 + 0.75 * fade))))) for c in palette_rgb[idx])
                draw.line((sx0, sy0, sx1, sy1), fill=col, width=1)

        return np.asarray(img, dtype=np.uint8)
