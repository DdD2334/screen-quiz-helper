# -*- coding: utf-8 -*-
"""overlay.py — 框选截屏全屏遮罩（T14）。

- 背景是先截好的整屏图（冻结屏幕），框选期间画面不动。
- 逻辑坐标 → 截图像素坐标统一用 pixmap/window 尺寸比例换算（不硬乘 devicePixelRatio，
  多屏混合 DPI 也正确）。
- 回调交回的是"截图内物理像素矩形"，AppController 加 CaptureResult.origin 得到绝对坐标。
- 只能在 Qt 主线程创建/销毁。
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

log = logging.getLogger("overlay")

_MIN_SIDE = 20  # 物理像素，小于视为误触


class RegionOverlay(QWidget):
    def __init__(
        self,
        png_bytes: bytes,
        screen_geometry: QRect,
        on_done: Callable[[int, int, int, int], None],
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_done = on_done
        self._on_cancel = on_cancel
        self._pixmap = QPixmap()
        if not self._pixmap.loadFromData(png_bytes):
            raise ValueError("冻结背景图解码失败")
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self._finished = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(screen_geometry)  # 逻辑坐标
        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    def _selection_rect(self) -> QRect:
        return QRect(self._origin, self._current).normalized()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        # 冻结背景：整张 pixmap 拉伸到窗口（比例换算也基于此）
        p.drawPixmap(self.rect(), self._pixmap)
        # 半透明黑色蒙层
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        sel = self._selection_rect()
        if self._dragging and sel.width() > 1 and sel.height() > 1:
            # 清除蒙层：把选区内的背景原样画回
            sx = self._pixmap.width() / max(1, self.width())
            sy = self._pixmap.height() / max(1, self.height())
            src = QRect(int(sel.x() * sx), int(sel.y() * sy),
                        int(sel.width() * sx), int(sel.height() * sy))
            p.drawPixmap(sel, self._pixmap, src)
            p.setPen(QPen(QColor("#00e5ff"), 2))
            p.drawRect(sel)
            # 左上角尺寸提示（物理像素，坐标差）
            pw = int(abs(self._current.x() - self._origin.x()) * sx)
            ph = int(abs(self._current.y() - self._origin.y()) * sy)
            hint = f"{pw}×{ph}"
            p.setFont(QFont("Microsoft YaHei", 10))
            p.setPen(QPen(QColor("white")))
            p.fillRect(sel.x(), max(0, sel.y() - 22), 90, 20, QColor(0, 0, 0, 160))
            p.drawText(sel.x() + 4, max(14, sel.y() - 7), hint)
        # 顶部说明
        p.setFont(QFont("Microsoft YaHei", 12))
        p.setPen(QPen(QColor("white")))
        tip = "拖动框选题目区域，松开确认，Esc 取消"
        p.drawText(self.rect().adjusted(0, 24, 0, 0), Qt.AlignHCenter | Qt.AlignTop, tip)
        p.end()

    # ------------------------------------------------------------------
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()
        elif e.button() == Qt.RightButton:
            self._cancel()

    def mouseMoveEvent(self, e) -> None:
        if self._dragging:
            self._current = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._current = e.position().toPoint()
        sel = self._selection_rect()
        sx = self._pixmap.width() / max(1, self.width())
        sy = self._pixmap.height() / max(1, self.height())
        # QRect 含端点（width=差值+1），物理尺寸用坐标差计算
        left, top = int(sel.x() * sx), int(sel.y() * sy)
        w = int(abs(self._current.x() - self._origin.x()) * sx)
        h = int(abs(self._current.y() - self._origin.y()) * sy)
        if w < _MIN_SIDE or h < _MIN_SIDE:
            self._cancel()  # 误触
            return
        self._finish(left, top, w, h)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self._cancel()

    # ------------------------------------------------------------------
    def _finish(self, left: int, top: int, w: int, h: int) -> None:
        if self._finished:
            return
        self._finished = True
        self.close()
        self.deleteLater()
        self._on_done(left, top, w, h)

    def _cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.close()
        self.deleteLater()
        if self._on_cancel is not None:
            self._on_cancel()