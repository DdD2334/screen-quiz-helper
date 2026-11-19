# -*- coding: utf-8 -*-
"""ui.py — PySide6 置顶悬浮窗 + 托盘（T4 修复 + T18 增强）。

- field_visibility / float_mode / default_corner / capture_flash / capture_sound 全部生效（B16）。
- 历史回看、速览复制、流式临时 label、低置信度整卡标黄、状态条级别配色。
- 折叠 48×48"答"字按钮，展开恢复记忆尺寸（B11）；flash 不覆盖新状态（B20）。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

log = logging.getLogger("ui")

try:
    from PySide6.QtCore import Qt, QPoint, QRect, QTimer
    from PySide6.QtGui import (QGuiApplication, QIcon, QColor, QPixmap, QPainter, QPen,
                               QClipboard)
    from PySide6.QtWidgets import (
        QApplication, QWidget, QLabel, QFrame, QScrollArea, QVBoxLayout, QHBoxLayout,
        QMenu, QPushButton, QSystemTrayIcon,
    )
    _HAS_QT = True
except ImportError as _e:
    _HAS_QT = False
    log.warning("PySide6 unavailable: %s", _e)

if _HAS_QT:
    from parsing import Question, answers_digest
    from config import app_dir
    import config  # noqa: F401


class FloatingPanel(QWidget):
    """置顶、可拖动、可折叠的答案面板；只允许在 Qt 主线程调用。"""

    def __init__(self, cfg: "config.Config") -> None:
        super().__init__()
        self.cfg = cfg
        self._collapsed = False
        self._history: list[list[Question]] = []
        self._hist_idx = -1
        self._user_moved = False
        self._corner_done = False
        self._partial_label = None
        self._partial_buf = ""
        self.on_settings = None  # 由 AppController 注入的设置回调
        self.on_explain = None   # 由 AppController 注入的追问回调（T25）
        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setMinimumSize(360, 180)
        self.resize(460, 300)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header（可拖动）：标题 + 历史导航 + 设置
        self._header = QWidget()
        self._header.setFixedHeight(28)
        self._header.setStyleSheet("background: #2c3e50;")
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(10, 0, 6, 0)
        hl.setSpacing(4)
        self._title = QLabel("屏幕答题助手")
        self._title.setStyleSheet("color: white; font-size: 13px; font-weight: 600; background: transparent;")
        hl.addWidget(self._title)
        hl.addStretch(1)
        nav_style = ("QPushButton { color: white; background: transparent; border: none; "
                     "font-size: 13px; padding: 0 4px; } QPushButton:disabled { color: #7f8c8d; }")
        self._btn_prev = QPushButton("◀")
        self._btn_prev.setStyleSheet(nav_style)
        self._btn_prev.clicked.connect(lambda: self._nav(-1))
        hl.addWidget(self._btn_prev)
        self._nav_label = QLabel("0/0")
        self._nav_label.setStyleSheet("color: #bdc3c7; font-size: 11px; background: transparent;")
        hl.addWidget(self._nav_label)
        self._btn_next = QPushButton("▶")
        self._btn_next.setStyleSheet(nav_style)
        self._btn_next.clicked.connect(lambda: self._nav(1))
        hl.addWidget(self._btn_next)
        self._btn_settings = QPushButton("⚙")
        self._btn_settings.setStyleSheet(nav_style)
        self._btn_settings.setToolTip("设置")
        self._btn_settings.clicked.connect(self._open_settings)
        hl.addWidget(self._btn_settings)
        self._header.mousePressEvent = self._header_mouse_press
        self._header.mouseMoveEvent = self._header_mouse_move
        self._header.mouseReleaseEvent = self._header_mouse_release
        self._header_drag_pos: QPoint | None = None
        root.addWidget(self._header)

        # 状态条
        self._status = QLabel("等待热键触发…")
        self._status.setFixedHeight(22)
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        self.set_idle()

        # 卡片区
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("border: none;")
        inner = QFrame()
        self._inner_layout = QVBoxLayout(inner)
        self._inner_layout.setContentsMargins(8, 8, 8, 8)
        self._inner_layout.setSpacing(6)
        self._inner_layout.addStretch(1)
        self._scroll.setWidget(inner)
        root.addWidget(self._scroll)

        # Footer
        self._footer = QWidget()
        footer = QHBoxLayout(self._footer)
        footer.setContentsMargins(4, 4, 4, 4)
        self._btn_copy_answers = QPushButton("复制答案")
        self._btn_copy_answers.setFixedHeight(26)
        self._btn_copy_answers.setToolTip("只复制速览串：1.B  2.ACD  3.对")
        self._btn_copy_answers.clicked.connect(self.copy_answers)
        footer.addWidget(self._btn_copy_answers)
        self._btn_copy_all = QPushButton("全部复制")
        self._btn_copy_all.setFixedHeight(26)
        self._btn_copy_all.clicked.connect(self.copy_all)
        footer.addWidget(self._btn_copy_all)
        self._btn_clear = QPushButton("清空")
        self._btn_clear.setFixedHeight(26)
        self._btn_clear.clicked.connect(self.clear)
        footer.addWidget(self._btn_clear)
        self._btn_export = QPushButton("导出复习笔记")
        self._btn_export.setFixedHeight(26)
        self._btn_export.setToolTip("把收藏的题目导出为 Markdown")
        self._btn_export.clicked.connect(self.export_notes)
        footer.addWidget(self._btn_export)
        self._btn_collapse = QPushButton("折叠")
        self._btn_collapse.setFixedHeight(26)
        self._btn_collapse.clicked.connect(self.toggle_collapse)
        footer.addWidget(self._btn_collapse)
        root.addWidget(self._footer)

        # 折叠态专用"答"字展开按钮
        self._btn_expand = QPushButton("答", self)
        self._btn_expand.setFixedSize(48, 48)
        self._btn_expand.setStyleSheet(
            "background: #2c3e50; color: white; font-size: 18px; font-weight: 700; border-radius: 8px;"
        )
        self._btn_expand.clicked.connect(self.toggle_collapse)
        self._btn_expand.hide()
        self._normal_size = self.size()
        self._update_nav()

    def _open_settings(self) -> None:
        if self.on_settings is not None:
            self.on_settings()

    # ------------------------------------------------------------------
    # 状态条
    # ------------------------------------------------------------------
    _STATUS_STYLES = {
        "info": "background: #ecf0f1; color: #555;",
        "busy": "background: #d6e9f8; color: #1a5276;",
        "warn": "background: #fff3cd; color: #856404;",
        "error": "background: #f8d7da; color: #721c24;",
        "ok": "background: #d5f5d5; color: #2e6b2e;",
    }

    def set_status(self, msg: str, level: str = "info") -> None:
        style = self._STATUS_STYLES.get(level, self._STATUS_STYLES["info"])
        self._status.setText(msg)
        self._status.setStyleSheet(style + " padding: 4px 8px; font-size: 12px;")

    def set_error(self, msg: str) -> None:
        self.set_status(f"失败: {msg}", "error")
        self._show_if_needed()

    def set_idle(self) -> None:
        self.set_status("等待热键触发…", "info")

    def set_throttled(self, seconds: int) -> None:
        self.set_status(f"限流中，请等 {seconds} 秒再试", "warn")

    def _flash_status(self, msg: str) -> None:
        prev_text = self._status.text()
        prev_style = self._status.styleSheet()
        self._status.setText(msg)

        def _restore() -> None:
            if self._status.text() == msg:  # 期间被改过就不动（B20）
                self._status.setText(prev_text)
                self._status.setStyleSheet(prev_style)

        QTimer.singleShot(1500, _restore)

    # ------------------------------------------------------------------
    # 答案批次 / 历史
    # ------------------------------------------------------------------
    def set_questions(self, questions: list["Question"]) -> None:
        self._history.append(list(questions))
        cap = max(1, int(self.cfg.ui.history_size))
        if len(self._history) > cap:
            self._history = self._history[-cap:]
        self._hist_idx = len(self._history) - 1
        self._render_batch(questions)
        self.set_status(f"已收到 {len(questions)} 题", "ok")
        self._show_if_needed()

    def _render_batch(self, questions: list["Question"]) -> None:
        self._clear_cards()
        for q in questions:
            self._inner_layout.insertWidget(self._inner_layout.count() - 1, self._make_card(q))
        self._update_nav()

    def _nav(self, delta: int) -> None:
        if not self._history:
            return
        idx = max(0, min(len(self._history) - 1, self._hist_idx + delta))
        if idx != self._hist_idx:
            self._hist_idx = idx
            self._render_batch(self._history[idx])

    def _update_nav(self) -> None:
        n = len(self._history)
        self._nav_label.setText(f"{self._hist_idx + 1}/{n}" if n else "0/0")
        self._btn_prev.setEnabled(n > 0 and self._hist_idx > 0)
        self._btn_next.setEnabled(n > 0 and self._hist_idx < n - 1)

    def _current_batch(self) -> list["Question"]:
        if 0 <= self._hist_idx < len(self._history):
            return self._history[self._hist_idx]
        return []

    def _clear_cards(self) -> None:
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._inner_layout.addStretch(1)
        self._partial_label = None
        self._partial_buf = ""

    def clear(self) -> None:
        self._history = []
        self._hist_idx = -1
        self._clear_cards()
        self._update_nav()
        self.set_idle()

    def apply_config(self, cfg: "config.Config") -> None:
        """设置保存后刷新：字段可见性、历史上限、当前批重绘。"""
        self.cfg = cfg
        cap = max(1, int(cfg.ui.history_size))
        if len(self._history) > cap:
            self._history = self._history[-cap:]
            self._hist_idx = len(self._history) - 1
        if self._history:
            self._render_batch(self._current_batch())
        self._update_nav()

    # ------------------------------------------------------------------
    # 流式 / 截屏反馈
    # ------------------------------------------------------------------
    def append_partial(self, chunk: str) -> None:
        if self._partial_label is None:
            self._partial_label = QLabel()
            self._partial_label.setWordWrap(True)
            self._partial_label.setStyleSheet(
                "color: #888; font-size: 11px; background: #fafafa; border: 1px dashed #ccc; padding: 4px;"
            )
            self._inner_layout.insertWidget(self._inner_layout.count() - 1, self._partial_label)
            self._partial_buf = ""
        self._partial_buf += chunk
        self._partial_label.setText(self._partial_buf[-500:])
        self._show_if_needed()

    def flash_capture(self) -> None:
        if self.cfg.ui.capture_sound:
            QApplication.beep()
        if self.cfg.ui.show_capture_flash:
            self.setAttribute(Qt.WA_StyledBackground, True)
            self.setStyleSheet("FloatingPanel { border: 2px solid #00e5ff; }")
            QTimer.singleShot(300, lambda: self.setStyleSheet(""))

    # ------------------------------------------------------------------
    # 显示 / 定位 / 折叠
    # ------------------------------------------------------------------
    def _show_if_needed(self) -> None:
        if not self.isVisible() and not self._collapsed:
            self.show()
            self.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._corner_done and not self._user_moved:
            self._place_at_corner()
            self._corner_done = True

    def _place_at_corner(self) -> None:
        geo = QGuiApplication.primaryScreen().availableGeometry()
        margin = 16
        corner = self.cfg.ui.default_corner
        x = geo.right() - self.width() - margin if "right" in corner else geo.left() + margin
        y = geo.bottom() - self.height() - margin if "bottom" in corner else geo.top() + margin
        self.move(x, y)

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._normal_size = self.size()
            self._header.hide()
            self._status.hide()
            self._scroll.hide()
            self._footer.hide()
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.setFixedSize(48, 48)
            self._btn_expand.move(0, 0)
            self._btn_expand.show()
        else:
            self._btn_expand.hide()
            self.setMinimumSize(360, 180)
            self.setMaximumSize(16777215, 16777215)
            self.resize(self._normal_size)
            self._header.show()
            self._status.show()
            self._scroll.show()
            self._footer.show()

    # ------------------------------------------------------------------
    # 拖动（header）
    # ------------------------------------------------------------------
    def _header_mouse_press(self, e: Any) -> None:
        if e.button() == Qt.LeftButton:
            self._header_drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _header_mouse_move(self, e: Any) -> None:
        if self._header_drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._header_drag_pos)
            self._user_moved = True  # 拖动过之后不再自动挪

    def _header_mouse_release(self, e: Any) -> None:
        self._header_drag_pos = None

    # ------------------------------------------------------------------
    # 复制
    # ------------------------------------------------------------------
    def _question_text(self, q: "Question") -> str:
        head = f"第{q.index}题"
        if q.topic:
            head += f" [{q.topic}]"
        if q.question:
            head += f" {q.question}"
        parts = [head, f"答案: {q.answer}"]
        if q.confidence is not None:
            parts.append(f"置信度: {q.confidence:.2f}")
        if q.reasoning:
            parts.append(f"理由: {q.reasoning}")
        return "\n".join(parts)

    def copy_answers(self) -> None:
        batch = self._current_batch()
        if not batch:
            self._flash_status("暂无答案可复制")
            return
        digest = answers_digest(batch)
        QGuiApplication.clipboard().setText(digest)
        self._flash_status(f"已复制：{digest}")

    def copy_all(self) -> None:
        batch = self._current_batch()
        if not batch:
            self._flash_status("暂无答案可复制")
            return
        QGuiApplication.clipboard().setText("\n\n".join(self._question_text(q) for q in batch))
        self._flash_status("已复制全部答案")

    def _copy_one(self, q: "Question") -> None:
        QGuiApplication.clipboard().setText(self._question_text(q))
        self._flash_status(f"已复制第{q.index}题")

    def _collect_questions(self) -> list["Question"]:
        out: list["Question"] = []
        for i in range(self._inner_layout.count()):
            w = self._inner_layout.itemAt(i).widget()
            if hasattr(w, "_q"):
                out.append(w._q)
        return out

    # ------------------------------------------------------------------
    # 卡片
    # ------------------------------------------------------------------
    def _make_card(self, q: "Question") -> QWidget:
        vis = self.cfg.ui.field_visibility
        threshold = self.cfg.model.low_confidence_threshold
        low = q.confidence is not None and q.confidence < threshold

        card = QFrame()
        if low:
            card.setStyleSheet("QFrame { background: #fffbe6; border: 1px solid #e6d9a8; border-radius: 4px; }")
        else:
            card.setStyleSheet("QFrame { background: white; border: 1px solid #ddd; border-radius: 4px; }")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # 标题：第N题 · 题型 · 题干摘要（30 字）
        head = f"第{q.index}题"
        if vis.get("topic", True) and q.topic:
            head += f" · {q.topic}"
        if q.question:
            summary = q.question[:30] + ("…" if len(q.question) > 30 else "")
            head += f" · {summary}"
        title = QLabel(head)
        title.setStyleSheet("font-size: 13px; font-weight: 600; color: #333; border: none; background: transparent;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # 答案永远显示
        ans = QLabel(f"答案: {q.answer or '(无)'}")
        ans.setStyleSheet("font-size: 13px; color: #2e6b2e; font-weight: 600; border: none; background: transparent;")
        ans.setWordWrap(True)
        ans.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(ans)

        if vis.get("confidence", True) and q.confidence is not None:
            hint = f"置信度 {q.confidence:.2f}" + ("（建议人工核对）" if low else "")
            lbl = QLabel(hint)
            color = "#b58900; font-weight: 600" if low else "#2e6b2e"
            lbl.setStyleSheet(f"font-size: 11px; color: {color}; border: none; background: transparent;")
            layout.addWidget(lbl)

        if vis.get("reasoning", True) and q.reasoning:
            r = QLabel(f"理由: {q.reasoning}")
            r.setStyleSheet("font-size: 12px; color: #666; border: none; background: transparent;")
            r.setWordWrap(True)
            layout.addWidget(r)

        btn_row = QHBoxLayout()
        btn = QPushButton("复制本题")
        btn.setFixedHeight(22)
        btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn.clicked.connect(lambda _=False, q=q: self._copy_one(q))
        btn_row.addWidget(btn)
        btn_fav = QPushButton("收藏")
        btn_fav.setFixedHeight(22)
        btn_fav.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn_fav.clicked.connect(lambda _=False, q=q: self._favorite(q))
        btn_row.addWidget(btn_fav)
        btn_ask = QPushButton("追问")
        btn_ask.setFixedHeight(22)
        btn_ask.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn_ask.setToolTip("让模型详细讲解这道题")
        btn_ask.clicked.connect(lambda _=False, q=q: self._explain(q))
        btn_row.addWidget(btn_ask)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        card._q = q
        return card

    # ------------------------------------------------------------------
    # T25 收藏 / 导出 / 追问讲解
    # ------------------------------------------------------------------
    def _favorite(self, q: "Question") -> None:
        path = app_dir() / "favorites.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            if not isinstance(data, list):
                data = []
            data.append({**q.to_dict(), "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
            self._flash_status(f"已收藏第{q.index}题")
        except OSError as e:
            self.set_status(f"收藏失败: {e}", "error")

    def export_notes(self) -> None:
        path = app_dir() / "favorites.json"
        if not path.exists():
            self._flash_status("还没有收藏题目")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.set_status(f"收藏读取失败: {e}", "error")
            return
        if not data:
            self._flash_status("还没有收藏题目")
            return
        by_date: dict[str, list] = {}
        for item in data:
            date = str(item.get("ts", ""))[:10] or "未知日期"
            by_date.setdefault(date, []).append(item)
        lines = ["# 复习笔记", ""]
        for date in sorted(by_date):
            lines.append(f"## {date}")
            lines.append("")
            for item in by_date[date]:
                head = f"### 第{item.get('index', '?')}题"
                if item.get("topic"):
                    head += f"（{item['topic']}）"
                lines.append(head)
                if item.get("question"):
                    lines.append(f"- 题干摘要：{item['question']}")
                lines.append(f"- 我的答案：{item.get('answer', '')}")
                if item.get("confidence") is not None:
                    lines.append(f"- 置信度：{item['confidence']}")
                if item.get("reasoning"):
                    lines.append(f"- 解析：{item['reasoning']}")
                lines.append("")
        out_dir = app_dir() / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"复习笔记_{time.strftime('%Y%m%d')}.md"
        try:
            out.write_text("\n".join(lines), encoding="utf-8")
        except OSError as e:
            self.set_status(f"导出失败: {e}", "error")
            return
        self.set_status(f"已导出：{out}", "ok")
        os.startfile(str(out))

    def _explain(self, q: "Question") -> None:
        if self.on_explain is not None:
            self.on_explain(q)
        else:
            self._flash_status("追问功能未接线")

    def show_explanation(self, payload) -> None:
        """payload = (index, 讲解文本)：在该题卡片下方插入讲解卡片。"""
        idx, text = payload
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #eef6ff; border: 1px solid #b8d4f0; border-radius: 4px; }")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 6, 8, 6)
        title = QLabel(f"第{idx}题 · 讲解")
        title.setStyleSheet("font-size: 12px; font-weight: 600; color: #1a5276; border: none; background: transparent;")
        lay.addWidget(title)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet("font-size: 12px; color: #333; border: none; background: transparent;")
        lay.addWidget(body)
        btn = QPushButton("复制讲解")
        btn.setFixedHeight(22)
        btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn.clicked.connect(lambda _=False, t=text: (
            QGuiApplication.clipboard().setText(t), self._flash_status("已复制讲解")))
        lay.addWidget(btn)
        # 找到对应题卡，插到它后面；找不到（批次已切换）则追加到末尾
        pos = self._inner_layout.count() - 1
        for i in range(self._inner_layout.count()):
            w = self._inner_layout.itemAt(i).widget()
            if getattr(w, "_q", None) is not None and w._q.index == idx:
                pos = i + 1
                break
        self._inner_layout.insertWidget(pos, frame)
        self._show_if_needed()


# ----------------------------------------------------------------------
# 托盘
# ----------------------------------------------------------------------

class TrayIcon:
    def __init__(self, panel: FloatingPanel) -> None:
        self._panel = panel
        self._icon = QSystemTrayIcon()
        self._icon.setIcon(self._make_icon())
        self._icon.setToolTip("屏幕答题助手")
        self._menu = QMenu()  # 保持引用防 GC
        self._menu.addAction("显示/隐藏", self._panel.toggle_visibility)
        self._menu.addAction("设置", self._open_settings)
        self._menu.addAction("清空答案", self._panel.clear)
        quit_action = self._menu.addAction("退出")
        quit_action.triggered.connect(QApplication.quit)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_click)
        self._icon.show()

    def _open_settings(self) -> None:
        if self._panel.on_settings is not None:
            self._panel.on_settings()

    def _make_icon(self) -> QIcon:
        pix = QPixmap(24, 24)
        pix.fill(QColor("#2c3e50"))
        p = QPainter(pix)
        p.setPen(QPen(QColor("white"), 2))
        p.drawText(QRect(0, 0, 24, 24), Qt.AlignCenter, "S")
        p.end()
        return QIcon(pix)

    def _on_click(self, reason: Any) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._panel.toggle_visibility()
        elif reason == QSystemTrayIcon.DoubleClick:
            self._open_settings()  # 双击托盘打开设置


# ----------------------------------------------------------------------
# 独立入口（调试用）
# ----------------------------------------------------------------------

if __name__ == "__main__":
    import config as _config
    app = QApplication(sys.argv)
    panel = FloatingPanel(_config.load_config())
    panel.show()
    tray = TrayIcon(panel)
    sys.exit(app.exec())