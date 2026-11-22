# Contributing to Glediator

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check glediator tests scripts
QT_QPA_PLATFORM=offscreen pytest -q
```

## Architecture Rules

1. `glediator/core`, `effects`, `output`, `audio`, `network`, and `control` must **never import `PySide6`**. Only `glediator/ui` may.
2. Rendered frames are always `np.ndarray`, `dtype=uint8`, shape `(height, width, 3)` in RGB row-major order. Host code never applies pixel-order/serpentine/panel-chaining mapping.
3. All engine mutations go through thread-safe public methods on `RenderEngine`. The UI must never access private scene fields directly.
4. Never perform blocking work (thread joins, network I/O, disk I/O) while holding `RenderEngine._lock`.
5. Changes to persisted settings must add a schema migration in `glediator/core/migrations.py`.
6. WebSocket (`docs/protocol.md`) is the sole pixel transport.
