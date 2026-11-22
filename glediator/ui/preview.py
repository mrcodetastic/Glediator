from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGroupBox, QLabel, QMenu, QSizePolicy, QVBoxLayout


class FramePreview(QGroupBox):
    def __init__(self, title: str, accent: str, matrix_width: int = 64, matrix_height: int = 32) -> None:
        super().__init__(title)
        self._aspect = max(1, matrix_width) / max(1, matrix_height)
        self._source_image: QImage | None = None
        self._mode: str = "pixels"  # "pixels" | "dots"
        self._badge: str = ""
        self.setObjectName("previewCard")
        self.setStyleSheet(
            f"QGroupBox#previewCard {{ background:#111923; border:1px solid #263343; "
            f"border-top:3px solid {accent}; border-radius:9px; margin-top:10px; padding:10px; }}"
            "QGroupBox#previewCard::title { subcontrol-origin:margin; left:12px; "
            "padding:0 5px; color:#a8b8c9; font-size:9pt; font-weight:600; letter-spacing:1px; }"
        )
        size_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        size_policy.setHeightForWidth(True)
        self.setSizePolicy(size_policy)
        self.setMinimumSize(240, 210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        self.image = QLabel("Waiting for first frame…")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(1, 1)
        self.image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.image.setStyleSheet("background:#080c11; border-radius:5px; color:#627386;")
        layout.addWidget(self.image, 1)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_mode(self, mode: str) -> None:
        if mode in ("pixels", "dots"):
            self._mode = mode
            self._render_image()

    def set_badge(self, text: str) -> None:
        if self._badge != text:
            self._badge = text
            self._render_image()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        layout = self.layout()
        margins = layout.contentsMargins()
        image_width = max(1, width - margins.left() - margins.right())
        return (
            margins.top()
            + margins.bottom()
            + self.fontMetrics().height()
            + layout.spacing()
            + round(image_width / self._aspect)
        )

    def sizeHint(self) -> QSize:
        width = 360
        return QSize(width, max(210, self.heightForWidth(width)))

    def minimumSizeHint(self) -> QSize:
        width = 240
        return QSize(width, max(210, self.heightForWidth(width)))

    def set_matrix_size(self, width: int, height: int) -> None:
        self._aspect = max(1, int(width)) / max(1, int(height))
        self._update_minimum_height(max(self.width(), 240))
        self.updateGeometry()
        self._activate_parent_layouts()

    def set_frame(self, frame: np.ndarray) -> None:
        height, width, _ = frame.shape
        self._source_image = QImage(frame.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        self._render_image()

    def _render_led_dots(self, target_size: QSize) -> QPixmap:
        assert self._source_image is not None
        img = self._source_image
        mw, mh = img.width(), img.height()
        pixmap = QPixmap(target_size)
        pixmap.fill(QColor("#05070b"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        cell_w = target_size.width() / max(1, mw)
        cell_h = target_size.height() / max(1, mh)
        radius = max(1.0, min(cell_w, cell_h) * 0.42)
        for y in range(mh):
            cy = (y + 0.5) * cell_h
            for x in range(mw):
                painter.setBrush(img.pixelColor(x, y))
                painter.drawEllipse(
                    int((x + 0.5) * cell_w - radius),
                    int(cy - radius),
                    int(radius * 2),
                    int(radius * 2),
                )
        painter.end()
        return pixmap

    def _render_image(self) -> None:
        if self._source_image is None or self.image.width() < 2 or self.image.height() < 2:
            return
        if self._mode == "dots" and self._source_image.width() <= 128 and self._source_image.height() <= 128:
            pixmap = self._render_led_dots(self.image.size())
        else:
            scaled = QPixmap.fromImage(self._source_image).scaled(
                self.image.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.FastTransformation,
            )
            x = max(0, (scaled.width() - self.image.width()) // 2)
            y = max(0, (scaled.height() - self.image.height()) // 2)
            pixmap = scaled.copy(x, y, self.image.width(), self.image.height())

        if self._badge:
            painter = QPainter(pixmap)
            painter.fillRect(8, 8, 96, 22, QColor(180, 30, 30, 210))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(14, 23, self._badge)
            painter.end()

        self.image.setPixmap(pixmap)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        pixels_act = QAction("Pixels", menu, checkable=True)
        pixels_act.setChecked(self._mode == "pixels")
        pixels_act.triggered.connect(lambda: self.set_mode("pixels"))
        dots_act = QAction("LED dots", menu, checkable=True)
        dots_act.setChecked(self._mode == "dots")
        dots_act.triggered.connect(lambda: self.set_mode("dots"))
        copy_act = QAction("Copy frame as PNG", menu)
        copy_act.triggered.connect(self._copy_png)
        menu.addAction(pixels_act)
        menu.addAction(dots_act)
        menu.addSeparator()
        menu.addAction(copy_act)
        menu.exec(self.mapToGlobal(pos))

    def _copy_png(self) -> None:
        if self._source_image is not None:
            QGuiApplication.clipboard().setImage(self._source_image)

    def _update_minimum_height(self, width: int) -> None:
        desired = max(210, self.heightForWidth(width))
        if self.minimumHeight() != desired:
            self.setMinimumHeight(desired)

    def _activate_parent_layouts(self) -> None:
        parent = self.parentWidget()
        while parent is not None:
            parent.updateGeometry()
            if parent.layout() is not None:
                parent.layout().invalidate()
                parent.layout().activate()
            parent = parent.parentWidget()

    def resizeEvent(self, event) -> None:
        self._update_minimum_height(max(self.width(), 240))
        self._render_image()
        super().resizeEvent(event)
