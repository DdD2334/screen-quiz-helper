# -*- coding: utf-8 -*-
"""settings_dialog.py — 设置对话框（T17）：四页 + 首次启动向导 + 测试连接 + 热键录制。

线程铁律：测试连接放 threading 线程，结果经 Signal 回 UI 线程。
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)

from config import app_dir
from presets import PRESETS

log = logging.getLogger("settings")

_HOTKEY_ROWS = [
    ("capture_fullscreen", "整屏截屏答题"),
    ("capture_region", "框选截屏答题"),
    ("copy_answers", "复制答案速览"),
    ("toggle_panel", "显示/隐藏面板"),
]

_SPECIAL_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Tab: "tab", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
    Qt.Key_Escape: "esc", Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete",
    Qt.Key_Insert: "insert", Qt.Key_Home: "home", Qt.Key_End: "end",
    Qt.Key_PageUp: "page up", Qt.Key_PageDown: "page down",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
}


def _key_name(key: int) -> str | None:
    if Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key).lower()
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"f{key - Qt.Key_F1 + 1}"
    return _SPECIAL_KEYS.get(key)


def apply_autostart(cfg) -> None:
    """T23：HKCU Run 键，只动当前用户不需要管理员。"""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
    except OSError as e:
        log.error("open Run key failed: %s", e)
        return
    try:
        if cfg.autostart:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}"'
            else:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                exe = str(pythonw) if pythonw.exists() else sys.executable
                cmd = f'"{exe}" "{app_dir() / "main.py"}"'
            winreg.SetValueEx(key, "ScreenQuizHelper", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "ScreenQuizHelper")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


class SettingsDialog(QDialog):
    _test_done = Signal(bool, str)

    def __init__(self, cfg, client=None, parent=None, on_saved=None, first_run=False,
                 on_clear_cache=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._on_saved = on_saved
        self._on_clear_cache = on_clear_cache
        self._recording_edit: QLineEdit | None = None
        self._recording_btn: QPushButton | None = None
        self.setWindowTitle("设置 — 屏幕答题助手")
        self.setMinimumSize(520, 480)
        self._test_done.connect(self._on_test_result)

        root = QVBoxLayout(self)
        if first_run or not cfg.model.api_key:
            banner = QLabel("第一步：选择模型服务商并填入 API key，然后点测试连接")
            banner.setStyleSheet(
                "background: #fff3cd; color: #856404; font-size: 13px; font-weight: 600; "
                "padding: 8px; border-radius: 4px;"
            )
            banner.setWordWrap(True)
            root.addWidget(banner)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)
        self._build_model_page()
        self._build_hotkey_page()
        self._build_display_page()
        self._build_advanced_page()

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_save = QPushButton("保存")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._save)
        bottom.addWidget(btn_save)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    # 模型页
    # ------------------------------------------------------------------
    def _build_model_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        m = self.cfg.model

        self._preset = QComboBox()
        for key, p in PRESETS.items():
            self._preset.addItem(p["label"], key)
        self._preset.addItem("自定义", "custom")
        idx = self._preset.findData(m.provider)
        self._preset.setCurrentIndex(idx if idx >= 0 else self._preset.count() - 1)
        self._preset.currentIndexChanged.connect(self._apply_preset)
        form.addRow("服务商预设", self._preset)

        key_row = QHBoxLayout()
        self._api_key = QLineEdit(m.api_key)
        self._api_key.setEchoMode(QLineEdit.Password)
        self._api_key.setPlaceholderText("填入 API key")
        key_row.addWidget(self._api_key)
        self._show_key = QCheckBox("显示")
        self._show_key.toggled.connect(
            lambda on: self._api_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        key_row.addWidget(self._show_key)
        form.addRow("API key", key_row)

        self._api_base = QLineEdit(m.api_base)
        form.addRow("api_base", self._api_base)
        self._model = QLineEdit(m.model)
        form.addRow("模型名", self._model)

        self._timeout = QSpinBox()
        self._timeout.setRange(5, 600)
        self._timeout.setValue(int(m.timeout_seconds))
        self._timeout.setSuffix(" s")
        form.addRow("请求超时", self._timeout)

        self._min_interval = QSpinBox()
        self._min_interval.setRange(0, 600)
        self._min_interval.setValue(int(m.min_interval_seconds))
        self._min_interval.setSuffix(" s")
        form.addRow("最小调用间隔", self._min_interval)

        self._low_conf = QDoubleSpinBox()
        self._low_conf.setRange(0.0, 1.0)
        self._low_conf.setSingleStep(0.05)
        self._low_conf.setValue(m.low_confidence_threshold)
        form.addRow("低置信度阈值", self._low_conf)

        self._json_mode = QComboBox()
        self._json_mode.addItems(["auto", "on", "off"])
        self._json_mode.setCurrentText(m.json_mode)
        form.addRow("JSON 模式", self._json_mode)

        self._verify = QCheckBox("低置信度答案自动带图复核（多耗一次额度）")
        self._verify.setChecked(m.verify_low_confidence)
        form.addRow("", self._verify)

        self._prompt_extra = QPlainTextEdit(m.prompt_extra)
        self._prompt_extra.setPlaceholderText("可填背景，如：这是计算机网络方向的测评题")
        self._prompt_extra.setFixedHeight(60)
        form.addRow("补充背景", self._prompt_extra)

        test_row = QHBoxLayout()
        self._btn_test = QPushButton("测试连接")
        self._btn_test.clicked.connect(self._test_connection)
        test_row.addWidget(self._btn_test)
        self._test_label = QLabel("")
        self._test_label.setWordWrap(True)
        test_row.addWidget(self._test_label, 1)
        form.addRow("", test_row)

        self._tabs.addTab(page, "模型")

    def _apply_preset(self) -> None:
        key = self._preset.currentData()
        p = PRESETS.get(key)
        if p:
            self._api_base.setText(p["api_base"])
            self._model.setText(p["model"])
            self._min_interval.setValue(int(p["min_interval_seconds"]))

    def _current_extra(self) -> dict:
        key = self._preset.currentData()
        if key in PRESETS:
            return dict(PRESETS[key]["extra"])
        return dict(self.cfg.model.extra)  # 自定义保留原 extra

    def _test_connection(self) -> None:
        from agentic import AgenticClient
        client = AgenticClient(
            api_key=self._api_key.text().strip(),
            api_base=self._api_base.text().strip(),
            model=self._model.text().strip(),
            timeout=10,
            min_interval=0,
            provider=self._preset.currentData(),
            json_mode=self._json_mode.currentText(),
            extra=self._current_extra(),
        )
        self._btn_test.setEnabled(False)
        self._btn_test.setText("测试中…")
        self._test_label.setText("")

        def worker():
            try:
                reply = client.test_connection()
                self._test_done.emit(True, f"连接成功，模型回复：{reply}")
            except Exception as e:
                self._test_done.emit(False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_result(self, ok: bool, msg: str) -> None:
        self._btn_test.setEnabled(True)
        self._btn_test.setText("测试连接")
        self._test_label.setText(msg)
        self._test_label.setStyleSheet("color: #2e6b2e;" if ok else "color: #721c24;")
        if ok:
            QMessageBox.information(self, "测试连接", msg)
        else:
            QMessageBox.warning(self, "测试连接失败", msg)

    # ------------------------------------------------------------------
    # 热键页
    # ------------------------------------------------------------------
    def _build_hotkey_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self._hotkey_edits: dict[str, QLineEdit] = {}
        for key, label in _HOTKEY_ROWS:
            row = QHBoxLayout()
            edit = QLineEdit(self.cfg.hotkeys.get(key, ""))
            edit.setReadOnly(True)
            row.addWidget(edit)
            btn = QPushButton("录制")
            btn.clicked.connect(lambda _=False, e=edit, b=btn: self._start_recording(e, b))
            row.addWidget(btn)
            form.addRow(label, row)
            self._hotkey_edits[key] = edit
        tip = QLabel("点录制后按下组合键（如 Shift+Alt+S），Esc 取消录制。")
        tip.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow("", tip)
        self._tabs.addTab(page, "热键")

    def _start_recording(self, edit: QLineEdit, btn: QPushButton) -> None:
        self._stop_recording()
        self._recording_edit = edit
        self._recording_btn = btn
        btn.setText("按下组合键…")
        self.grabKeyboard()

    def _stop_recording(self) -> None:
        if self._recording_btn is not None:
            self._recording_btn.setText("录制")
        self._recording_edit = None
        self._recording_btn = None
        self.releaseKeyboard()

    def keyPressEvent(self, e) -> None:
        if self._recording_edit is None:
            super().keyPressEvent(e)
            return
        key = e.key()
        if key == Qt.Key_Escape:
            self._stop_recording()
            return
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
            return  # 只按了修饰键，继续等主键
        name = _key_name(key)
        if name is None:
            return
        mods = e.modifiers()
        parts = []
        if mods & Qt.ShiftModifier:
            parts.append("shift")
        if mods & Qt.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.AltModifier:
            parts.append("alt")
        if mods & Qt.MetaModifier:
            parts.append("windows")
        parts.append(name)
        self._recording_edit.setText("+".join(parts))
        self._stop_recording()

    # ------------------------------------------------------------------
    # 显示页
    # ------------------------------------------------------------------
    def _build_display_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        u = self.cfg.ui

        self._float_mode = QComboBox()
        self._float_mode.addItem("常显", "always")
        self._float_mode.addItem("出答案时弹出", "on_answer")
        self._float_mode.setCurrentIndex(0 if u.float_mode == "always" else 1)
        form.addRow("悬浮窗模式", self._float_mode)

        self._corner = QComboBox()
        for label, val in [("右下", "bottom-right"), ("左下", "bottom-left"),
                           ("右上", "top-right"), ("左上", "top-left")]:
            self._corner.addItem(label, val)
        self._corner.setCurrentIndex(max(0, self._corner.findData(u.default_corner)))
        form.addRow("默认停靠角", self._corner)

        self._vis: dict[str, QCheckBox] = {}
        for key, label in [("answer", "答案（不可隐藏）"), ("confidence", "置信度"),
                           ("reasoning", "理由"), ("topic", "题型")]:
            cb = QCheckBox(label)
            cb.setChecked(u.field_visibility.get(key, True))
            if key == "answer":
                cb.setChecked(True)
                cb.setEnabled(False)
            form.addRow("显示字段", cb)
            self._vis[key] = cb

        self._flash = QCheckBox("截屏瞬间闪边框")
        self._flash.setChecked(u.show_capture_flash)
        form.addRow("", self._flash)
        self._sound = QCheckBox("截屏提示音")
        self._sound.setChecked(u.capture_sound)
        form.addRow("", self._sound)

        self._history_size = QSpinBox()
        self._history_size.setRange(1, 100)
        self._history_size.setValue(u.history_size)
        form.addRow("历史批次数", self._history_size)
        self._tabs.addTab(page, "显示")

    # ------------------------------------------------------------------
    # 高级页
    # ------------------------------------------------------------------
    def _build_advanced_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        c = self.cfg.capture

        self._monitor = QComboBox()
        self._monitor.addItem("光标所在屏", "cursor")
        self._monitor.addItem("主屏", "primary")
        self._monitor.setCurrentIndex(0 if c.monitor == "cursor" else 1)
        form.addRow("整屏截屏目标", self._monitor)

        self._max_side = QSpinBox()
        self._max_side.setRange(512, 8192)
        self._max_side.setValue(c.max_image_side)
        self._max_side.setSuffix(" px")
        form.addRow("图片长边上限", self._max_side)

        self._img_fmt = QComboBox()
        self._img_fmt.addItems(["jpeg", "png"])
        self._img_fmt.setCurrentText(c.image_format)
        form.addRow("图片格式", self._img_fmt)

        self._jpeg_q = QSpinBox()
        self._jpeg_q.setRange(30, 100)
        self._jpeg_q.setValue(c.jpeg_quality)
        form.addRow("JPEG 质量", self._jpeg_q)

        self._debounce = QSpinBox()
        self._debounce.setRange(0, 10000)
        self._debounce.setValue(c.debounce_ms)
        self._debounce.setSuffix(" ms")
        form.addRow("热键防抖", self._debounce)

        self._keep_shot = QCheckBox("保留本地截图（screenshots/）")
        self._keep_shot.setChecked(c.keep_local_screenshot)
        form.addRow("", self._keep_shot)

        self._repair = QCheckBox("解析失败时自动修复请求")
        self._repair.setChecked(self.cfg.parse.repair_pass)
        form.addRow("", self._repair)

        self._cache_enabled = QCheckBox("启用答案缓存（同画面重复截屏秒回，省额度）")
        self._cache_enabled.setChecked(self.cfg.cache.enabled)
        form.addRow("", self._cache_enabled)
        btn_clear_cache = QPushButton("清空缓存")
        btn_clear_cache.clicked.connect(self._clear_cache)
        form.addRow("", btn_clear_cache)

        self._log_level = QComboBox()
        self._log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._log_level.setCurrentText(self.cfg.log.level)
        form.addRow("日志级别", self._log_level)

        self._autostart = QCheckBox("开机自启（当前用户）")
        self._autostart.setChecked(self.cfg.autostart)
        form.addRow("", self._autostart)

        btn_logs = QPushButton("打开日志文件夹")
        btn_logs.clicked.connect(self._open_logs)
        form.addRow("", btn_logs)
        self._tabs.addTab(page, "高级")

    def _open_logs(self) -> None:
        log_dir = app_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(log_dir))

    def _clear_cache(self) -> None:
        if self._on_clear_cache is not None:
            self._on_clear_cache()
            QMessageBox.information(self, "清空缓存", "答案缓存已清空")

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------
    def _save(self) -> None:
        import keyboard
        hotkeys = {k: e.text().strip().lower() for k, e in self._hotkey_edits.items()}
        for k, v in hotkeys.items():
            if not v:
                QMessageBox.warning(self, "热键无效", f"热键不能为空：{k}")
                return
            try:
                keyboard.parse_hotkey(v)
            except (ValueError, KeyError) as e:
                QMessageBox.warning(self, "热键无效", f"{v} 不是合法热键：{e}")
                return
        if len(set(hotkeys.values())) != len(hotkeys):
            QMessageBox.warning(self, "热键冲突", "四个热键不能重复")
            return

        m = self.cfg.model
        m.provider = self._preset.currentData()
        m.api_key = self._api_key.text().strip()
        m.api_base = self._api_base.text().strip()
        m.model = self._model.text().strip()
        m.timeout_seconds = float(self._timeout.value())
        m.min_interval_seconds = float(self._min_interval.value())
        m.low_confidence_threshold = float(self._low_conf.value())
        m.json_mode = self._json_mode.currentText()
        m.verify_low_confidence = self._verify.isChecked()
        m.prompt_extra = self._prompt_extra.toPlainText().strip()
        m.extra = self._current_extra()

        self.cfg.hotkeys.update(hotkeys)

        u = self.cfg.ui
        u.float_mode = self._float_mode.currentData()
        u.default_corner = self._corner.currentData()
        u.field_visibility = {k: cb.isChecked() for k, cb in self._vis.items()}
        u.field_visibility["answer"] = True
        u.show_capture_flash = self._flash.isChecked()
        u.capture_sound = self._sound.isChecked()
        u.history_size = self._history_size.value()

        c = self.cfg.capture
        c.monitor = self._monitor.currentData()
        c.max_image_side = self._max_side.value()
        c.image_format = self._img_fmt.currentText()
        c.jpeg_quality = self._jpeg_q.value()
        c.debounce_ms = self._debounce.value()
        c.keep_local_screenshot = self._keep_shot.isChecked()

        self.cfg.parse.repair_pass = self._repair.isChecked()
        self.cfg.cache.enabled = self._cache_enabled.isChecked()
        self.cfg.log.level = self._log_level.currentText()
        self.cfg.autostart = self._autostart.isChecked()

        try:
            self.cfg.save()
            apply_autostart(self.cfg)
        except OSError as e:
            QMessageBox.critical(self, "保存失败", f"配置写入失败：{e}")
            return
        self._stop_recording()
        if self._on_saved is not None:
            self._on_saved()
        self.accept()