from __future__ import annotations

from collections import deque

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from glediator.core.engine import EngineStatus


class SparklineWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: deque[float] = deque(maxlen=80)
        self.setMinimumHeight(42)

    def push(self, ms: float) -> None:
        self._values.append(max(0.0, float(ms)))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0b1118"))
        if len(self._values) < 2:
            painter.end()
            return
        max_v = max(16.7, max(self._values))
        w = max(1, self.width() - 4)
        h = max(1, self.height() - 4)
        painter.setPen(QPen(QColor("#3c9eff"), 1.5))
        pts = [
            (
                2 + int(i / max(1, len(self._values) - 1) * w),
                2 + h - int((v / max_v) * h),
            )
            for i, v in enumerate(self._values)
        ]
        for i in range(len(pts) - 1):
            painter.drawLine(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        painter.end()


class PerformancePanel(QWidget):
    def __init__(self, target_fps: int = 60, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.target_fps = max(1, target_fps)
        layout = QVBoxLayout(self)

        self.summary_label = QLabel("FPS: --  ·  Frame: -- ms  ·  Dropped: 0")
        layout.addWidget(self.summary_label)

        self.sparkline = SparklineWidget()
        layout.addWidget(self.sparkline)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("Layer", "Render (ms)"))
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

    def update_status(self, status: EngineStatus, target_fps: int) -> None:
        self.target_fps = max(1, target_fps)
        budget_ms = 1000.0 / self.target_fps
        over = status.frame_time_ms > budget_ms
        color = "#ef4444" if over else "#67dfa3"
        self.summary_label.setStyleSheet(f"color:{color}; font-weight:600;")
        self.summary_label.setText(
            f"FPS: {status.fps:.1f} / {self.target_fps}  ·  "
            f"Frame: {status.frame_time_ms:.2f} ms (budget {budget_ms:.1f} ms)  ·  "
            f"Dropped: {status.dropped_frames}"
        )
        self.sparkline.push(status.frame_time_ms)

        items = sorted(status.layer_times_ms.items())
        self.table.setRowCount(len(items))
        for row, ((side, idx), ms) in enumerate(items):
            tag = "A" if side == "left" else "B"
            self.table.setItem(row, 0, QTableWidgetItem(f"{tag} / Layer {idx + 1}"))
            self.table.setItem(row, 1, QTableWidgetItem(f"{ms:.2f}"))
