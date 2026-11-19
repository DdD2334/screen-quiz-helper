# -*- coding: utf-8 -*-
"""main.py — 入口：AppController 组装 UI + 热键 + 模型客户端。

v2 要点：
- 全局唯一 AgenticClient（B6）。
- 防抖唯一一层在热键入口（B19）；框选续跑等链路中间步骤不过防抖。
- 工作线程与 UI 只通过 Bridge 信号通信（B4）。
- latest-wins：RequestManager 递增 generation，旧请求取消、旧结果丢弃（T13）。
"""
from __future__ import annotations

import ctypes
import json
import logging
import sys
import threading
import time

log = logging.getLogger("main")


def _set_dpi_awareness() -> None:
    """启动最早处声明 DPI 感知，保证 mss 拿到真实物理分辨率（备忘 §5.3）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception as e:
        log.debug("SetProcessDpiAwareness failed: %s", e)
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception as e2:
            log.warning("DPI awareness unavailable: %s", e2)


class AppController:
    """唯一调度中心：热键 → 防抖 → 截屏 → 预处理 → RequestManager → Bridge → UI。"""

    def __init__(self, cfg, bridge, panel) -> None:
        from capture import ScreenCapture
        from request_manager import RequestManager
        from cache import AnswerCache
        self.cfg = cfg
        self.bridge = bridge
        self.panel = panel
        self.capture = ScreenCapture(keep_local_screenshot=cfg.capture.keep_local_screenshot)
        self.requests = RequestManager()
        self.cache = AnswerCache()
        self.client = self._build_client()
        self._last_hotkey_ts: float = 0.0
        self._active_gen: int = 0
        self._overlay = None

    def _build_client(self):
        from agentic import AgenticClient
        m = self.cfg.model
        return AgenticClient(
            api_key=m.api_key,
            api_base=m.api_base,
            model=m.model,
            timeout=m.timeout_seconds,
            min_interval=float(m.min_interval_seconds),
            provider=m.provider,
            json_mode=m.json_mode,
            extra=m.extra,
            on_status=self._client_status,
        )

    def _client_status(self, msg: str) -> None:
        # 旧 generation 的限流倒计时不许覆盖新请求状态
        if self.requests.is_current(self._active_gen):
            self.bridge.status.emit(msg, "busy")

    def _monitor_arg(self) -> int | None:
        return 1 if self.cfg.capture.monitor == "primary" else None

    # ------------------------------------------------------------------
    # 设置 / 热键注册
    # ------------------------------------------------------------------
    def register_hotkeys(self) -> None:
        from capture import register_hotkey, unhook_all
        unhook_all()
        hk = self.cfg.hotkeys
        oks = [
            register_hotkey(hk.get("capture_fullscreen", "shift+alt+s"), lambda: self.on_hotkey("full")),
            register_hotkey(hk.get("capture_region", "shift+alt+d"), lambda: self.on_hotkey("region")),
            register_hotkey(hk.get("copy_answers", "shift+alt+c"), lambda: self.bridge.copy_answers.emit()),
            register_hotkey(hk.get("toggle_panel", "shift+alt+h"), lambda: self.bridge.toggle_panel.emit()),
        ]
        if not all(oks):
            log.warning("one or more hotkeys failed to register — check keyboard lib + admin rights")
            self.bridge.status.emit("部分热键注册失败，尝试以管理员身份运行", "warn")

    def open_settings(self) -> None:
        from settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            self.cfg, self.client, self.panel,
            on_saved=self._apply_settings,
            first_run=getattr(self.cfg, "is_first_run", False),
            on_clear_cache=self.cache.clear,
        )
        dlg.exec()
        if not self.cfg.model.api_key:
            self.bridge.status.emit("未配置 API key，双击托盘打开设置", "warn")

    def _apply_settings(self) -> None:
        from applog import setup_logging
        self.client = self._build_client()
        self.capture.keep_local = self.cfg.capture.keep_local_screenshot
        self.panel.apply_config(self.cfg)
        self.register_hotkeys()
        setup_logging(self.cfg)  # 日志级别可能变了
        self.bridge.status.emit("设置已保存", "ok")

    # ------------------------------------------------------------------
    # 热键入口（keyboard 线程）：防抖唯一一层
    # ------------------------------------------------------------------
    def on_hotkey(self, kind: str) -> None:
        now = time.monotonic()
        if now - self._last_hotkey_ts < self.cfg.capture.debounce_ms / 1000.0:
            self.bridge.status.emit("触发太快，已忽略", "info")
            return
        self._last_hotkey_ts = now
        if kind == "region":
            self.bridge.request_region.emit()  # 主线程弹 overlay
        else:
            # 截屏+预处理在热键线程内同步做（很快），保证 submit 顺序 = 热键顺序，
            # 避免两个截屏线程乱序提交导致旧请求反而成为"最新"（T13）
            self._capture_full_and_submit()

    # ------------------------------------------------------------------
    # 截屏 + 预处理（提交前做，很快）
    # ------------------------------------------------------------------
    def _prepare(self, res):
        from image_utils import prepare_image
        c = self.cfg.capture
        self.capture.maybe_save(res)
        self.bridge.capture_flash.emit()
        return prepare_image(res.png_bytes, c.max_image_side, c.image_format, c.jpeg_quality)

    def _capture_full_and_submit(self) -> None:
        try:
            res = self.capture.capture_full(monitor=self._monitor_arg())
            b64, mime = self._prepare(res)
        except Exception as e:
            log.exception("capture failed")
            self.bridge.error.emit(str(e))
            return
        self._submit_ask(b64, mime)

    def _capture_region_and_submit(self, left: int, top: int, w: int, h: int) -> None:
        try:
            res = self.capture.capture_region(left, top, w, h)
            b64, mime = self._prepare(res)
        except Exception as e:
            log.exception("region capture failed")
            self.bridge.error.emit(str(e))
            return
        self._submit_ask(b64, mime)

    # ------------------------------------------------------------------
    # 框选 overlay（只在主线程）
    # ------------------------------------------------------------------
    def show_region_overlay(self) -> None:
        from PySide6.QtGui import QCursor, QGuiApplication
        from overlay import RegionOverlay
        try:
            # 冻结背景：capture 层无防抖，刚按过整屏热键也不影响（修订版 T14）
            res = self.capture.capture_full(monitor=self._monitor_arg())
        except Exception as e:
            log.exception("overlay freeze capture failed")
            self.bridge.error.emit(str(e))
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

        def on_done(x: int, y: int, w: int, h: int) -> None:
            # 截图内坐标 + 显示器物理原点 = 绝对屏幕坐标；续跑不再过防抖。
            # 同步截屏保证提交顺序（与整屏路径一致）。
            abs_left, abs_top = res.origin[0] + x, res.origin[1] + y
            self._capture_region_and_submit(abs_left, abs_top, w, h)

        def on_cancel() -> None:
            self.bridge.status.emit("已取消框选", "info")

        try:
            self._overlay = RegionOverlay(res.png_bytes, screen.geometry(), on_done, on_cancel)
            self._overlay.show()
            self._overlay.raise_()
            self._overlay.activateWindow()
        except Exception as e:
            log.exception("overlay failed")
            self.bridge.error.emit(f"框选遮罩创建失败: {e}")

    # ------------------------------------------------------------------
    # 请求链路（RequestManager worker 线程）
    # ------------------------------------------------------------------
    def _submit_ask(self, b64: str, mime: str) -> None:
        from agentic import ModelError
        from parsing import parse_questions
        from prompts import USER_PROMPT, build_system_prompt

        def fn(gen: int, ev: threading.Event) -> None:
            def stale() -> bool:
                return ev.is_set() or not self.requests.is_current(gen)

            try:
                # T25 缓存：sha256 精确匹配（键含 provider/model/prompt_extra），命中秒回
                cache_key = None
                if self.cfg.cache.enabled:
                    import base64 as _b64
                    from cache import make_key
                    from parsing import Question
                    cache_key = make_key(_b64.b64decode(b64), self.cfg.model.provider,
                                         self.cfg.model.model, self.cfg.model.prompt_extra)
                    hit = self.cache.get(cache_key)
                    if hit is not None:
                        self.bridge.questions_ready.emit([Question(**d) for d in hit])
                        self.bridge.status.emit("缓存命中，未消耗额度", "ok")
                        return

                self.bridge.status.emit("模型思考中…", "busy")
                chunks: list[str] = []
                for delta in self.client.ask_stream(
                    b64, prompt=USER_PROMPT, system=build_system_prompt(self.cfg),
                    cancel_event=ev, mime=mime,
                ):
                    if stale():
                        return
                    chunks.append(delta)
                    self.bridge.partial_text.emit(delta)
                if stale():
                    return
                text = "".join(chunks)
                if not text.strip():
                    raise ModelError("模型返回了空内容，请重试或换模型")
                qs = parse_questions(text)

                # 修复请求：第 1、2 级都失败的判定 = 只有 1 题且 answer 超长或含 "{"
                if (self.cfg.parse.repair_pass and len(qs) == 1
                        and (len(qs[0].answer) > 200 or "{" in qs[0].answer)):
                    if stale():
                        return
                    self.bridge.status.emit("解析不理想，尝试修复…", "busy")
                    qs = self.client.repair(text, cancel_event=ev)

                if stale():
                    return
                self.bridge.questions_ready.emit(qs)
                if not qs:
                    self.bridge.status.emit("未识别到题目", "warn")
                    return
                final_qs = qs

                # T16 低置信度复核（带原图 + 首批全部题目 JSON，同 generation 串行）
                threshold = self.cfg.model.low_confidence_threshold
                low = any(q.confidence is not None and q.confidence < threshold for q in qs)
                if self.cfg.model.verify_low_confidence and low:
                    if stale():
                        return
                    self.bridge.status.emit("存在低置信度答案，自动复核中…", "busy")
                    verified = self._verify(b64, mime, qs, ev)
                    if stale():
                        return
                    if verified:
                        final_qs = verified
                        self.bridge.questions_ready.emit(verified)
                        self.bridge.status.emit("已复核", "ok")

                # 缓存最终结果（复核后的版本）
                if cache_key is not None and final_qs:
                    self.cache.put(cache_key, [q.to_dict() for q in final_qs])
            except ModelError as e:
                if not stale():
                    self.bridge.error.emit(str(e))
            except Exception as e:
                log.exception("request worker failed (generation %d)", gen)
                if not stale():
                    self.bridge.error.emit(f"{type(e).__name__}: {e}")

        self._active_gen = self.requests.submit(fn)

    def _verify(self, b64: str, mime: str, qs, ev):
        from prompts import SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT
        payload = json.dumps(
            {"questions": [
                {"index": q.index, "question": q.question, "answer": q.answer, "reason": q.reasoning}
                for q in qs
            ]},
            ensure_ascii=False,
        )
        system = SYSTEM_PROMPT + "\n\n" + VERIFY_SYSTEM_PROMPT + "\n首批答案：\n" + payload
        return self.client.ask(
            b64, prompt="请逐题核对截图并输出全部题目的最终 JSON。",
            system=system, cancel_event=ev, mime=mime,
        )

    # ------------------------------------------------------------------
    # T25 追问讲解
    # ------------------------------------------------------------------
    def explain(self, q) -> None:
        from prompts import EXPLAIN_SYSTEM_PROMPT

        def fn(gen: int, ev: threading.Event) -> None:
            try:
                self.bridge.status.emit(f"第{q.index}题讲解生成中…", "busy")
                prompt = (f"题目：{q.question}\n答案：{q.answer}\n理由：{q.reasoning}\n"
                          "请详细讲解这道题的知识点和解题步骤。")
                text = self.client.ask_text(prompt, system=EXPLAIN_SYSTEM_PROMPT, cancel_event=ev)
                if ev.is_set() or not self.requests.is_current(gen):
                    return
                if text.strip():
                    self.bridge.explanation_ready.emit((q.index, text.strip()))
                    self.bridge.status.emit("讲解已生成", "ok")
                else:
                    self.bridge.status.emit("讲解返回为空，请重试", "warn")
            except Exception as e:
                log.exception("explain failed")
                if not ev.is_set() and self.requests.is_current(gen):
                    self.bridge.error.emit(str(e))

        self._active_gen = self.requests.submit(fn)


def run(cfg=None) -> int:
    _set_dpi_awareness()

    from config import Config, load_config
    cfg = cfg or load_config()

    from applog import setup_logging
    setup_logging(cfg)  # 启动最先初始化日志（T8）

    try:
        import ui
    except ImportError as e:
        print(f"ui.py unavailable: {e}\nInstall PySide6: pip install PySide6", file=sys.stderr)
        return 1

    from PySide6.QtWidgets import QApplication
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from bridge import Bridge
    from capture import unhook_all

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 托盘常驻，关窗口不退出

    # ---- T9 单实例保护 ----
    single_name = "screen-quiz-helper-single"
    probe = QLocalSocket()
    probe.connectToServer(single_name)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        log.info("already running; asked existing instance to show, exiting")
        return 0

    bridge = Bridge()  # 必须在主线程创建
    panel = ui.FloatingPanel(cfg)
    tray = ui.TrayIcon(panel)
    controller = AppController(cfg, bridge, panel)

    server = QLocalServer()
    QLocalServer.removeServer(single_name)  # 清理上次异常退出的残留
    if not server.listen(single_name):
        log.warning("single-instance listen failed: %s", server.errorString())

    def _on_new_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(300)
            data = bytes(conn.readAll())
            if b"show" in data:
                panel.show()
                panel.raise_()
                panel.activateWindow()
            conn.deleteLater()

    server.newConnection.connect(_on_new_connection)

    # 信号接线：全部在主线程 connect，AutoConnection 自动排队
    bridge.questions_ready.connect(panel.set_questions)
    bridge.error.connect(panel.set_error)
    bridge.status.connect(panel.set_status)
    bridge.partial_text.connect(panel.append_partial)
    bridge.request_region.connect(controller.show_region_overlay)
    bridge.capture_flash.connect(panel.flash_capture)
    bridge.copy_answers.connect(panel.copy_answers)
    bridge.toggle_panel.connect(panel.toggle_visibility)
    bridge.explanation_ready.connect(panel.show_explanation)
    panel.on_settings = controller.open_settings
    panel.on_explain = controller.explain

    controller.register_hotkeys()

    # float_mode：always 常显；on_answer 启动隐藏、托盘常驻（T18）
    if cfg.ui.float_mode == "always":
        panel.show()

    # 首次启动向导（T17）
    if getattr(cfg, "is_first_run", False) or not cfg.model.api_key:
        from PySide6.QtCore import QTimer
        if not cfg.model.api_key:
            bridge.status.emit("未配置 API key，双击托盘打开设置", "warn")
        QTimer.singleShot(200, controller.open_settings)

    log.info("entering Qt event loop")
    try:
        return app.exec()
    finally:
        unhook_all()


if __name__ == "__main__":
    sys.exit(run())