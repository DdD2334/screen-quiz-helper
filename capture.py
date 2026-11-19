# -*- coding: utf-8 -*-
"""capture.py — screen capture + global hotkeys.

v2 要点：
- 每次截屏在调用线程内新建 mss 实例，用完即关（Windows GDI 资源有线程亲和性，B9）。
- 防抖唯一一层在 AppController 热键入口，本层每次调用都真实截屏（B19，修订版 T5）。
- capture_full 默认截鼠标光标所在显示器，绝不用 monitors[0] 虚拟拼接大屏（B10）。
- capture_region 直接使用传入的绝对屏幕坐标（物理像素），不再加显示器偏移（T14）。
"""
from __future__ import annotations

import ctypes
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("capture")

# Lazy-import heavy deps so the module still imports without them
try:
    import mss  # type: ignore
    import mss.tools  # type: ignore
    _HAS_MSS = True
except ImportError:
    _HAS_MSS = False

try:
    import keyboard  # type: ignore
    _HAS_KEYBOARD = True
except ImportError:
    _HAS_KEYBOARD = False


@dataclass
class CaptureResult:
    png_bytes: bytes
    width: int
    height: int
    region: tuple[int, int, int, int] | None = None  # left, top, w, h（绝对屏幕物理像素）
    timestamp: float = field(default_factory=time.time)
    origin: tuple[int, int] = (0, 0)  # 所截显示器的物理左上角（多屏可能为负）

    @property
    def b64(self) -> str:
        import base64
        return base64.b64encode(self.png_bytes).decode("ascii")


class CaptureError(RuntimeError):
    pass


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _cursor_pos() -> tuple[int, int] | None:
    """用 ctypes GetCursorPos 拿光标物理像素坐标；失败返回 None（降级主屏）。"""
    try:
        pt = _POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return int(pt.x), int(pt.y)
        log.debug("GetCursorPos returned False")
    except Exception as e:
        log.debug("GetCursorPos failed: %s", e)
    return None


class ScreenCapture:
    """mss 截屏封装：整屏（光标所在屏）/ 区域（绝对坐标）。无防抖、无实例缓存。"""

    def __init__(self, monitor_index: int | None = None, keep_local_screenshot: bool = False) -> None:
        if not _HAS_MSS:
            raise CaptureError("mss not installed. Run: pip install mss")
        # monitor_index=None → 光标所在屏；1..N → 指定物理显示器（monitors[1:]）
        self.monitor_index = monitor_index
        self.keep_local = keep_local_screenshot

    # ------------------------------------------------------------------
    @staticmethod
    def _pick_monitor(sct, monitor: int | None) -> dict:
        mons = sct.monitors
        if monitor is not None and 1 <= monitor < len(mons):
            return mons[monitor]
        pos = _cursor_pos()
        if pos is not None:
            x, y = pos
            for mon in mons[1:]:
                if (mon["left"] <= x < mon["left"] + mon["width"]
                        and mon["top"] <= y < mon["top"] + mon["height"]):
                    return mon
        return mons[1]  # 主屏兜底，绝不用 mons[0]

    def capture_full(self, monitor: int | None = None) -> CaptureResult:
        """整屏截屏。monitor=None 时截光标所在显示器。永远真实截屏，失败抛 CaptureError。"""
        target = monitor if monitor is not None else self.monitor_index
        try:
            with mss.mss() as sct:
                mon = self._pick_monitor(sct, target)
                img = sct.grab(mon)
                png = mss.tools.to_png(img.rgb, img.size)
        except Exception as e:
            raise CaptureError(f"截屏失败: {e}") from e
        return CaptureResult(png_bytes=png, width=img.width, height=img.height,
                             origin=(int(mon["left"]), int(mon["top"])))

    def capture_region(self, left: int, top: int, width: int, height: int) -> CaptureResult:
        """区域截屏。left/top 为绝对屏幕坐标（物理像素，含多屏负坐标），不做偏移。"""
        rect = {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}
        if rect["width"] <= 0 or rect["height"] <= 0:
            raise CaptureError("框选区域无效：宽或高为 0")
        try:
            with mss.mss() as sct:
                img = sct.grab(rect)
                png = mss.tools.to_png(img.rgb, img.size)
        except Exception as e:
            raise CaptureError(f"框选截屏失败: {e}") from e
        return CaptureResult(
            png_bytes=png,
            width=img.width,
            height=img.height,
            region=(rect["left"], rect["top"], rect["width"], rect["height"]),
        )

    def maybe_save(self, result: CaptureResult, subdir: str = "screenshots") -> Optional[Path]:
        if not self.keep_local:
            return None
        from config import app_dir
        out_dir = app_dir() / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = "full" if result.region is None else "x".join(str(v) for v in result.region)
        out = out_dir / f"cap_{int(result.timestamp)}_{tag}.png"
        out.write_bytes(result.png_bytes)
        log.info("saved screenshot -> %s", out)
        return out


# ======================================================================
# Global hotkeys (keyboard library)
# ======================================================================

def register_hotkey(key_combo: str, handler: Callable[[], None], repeat: bool = False) -> bool:
    """
    Register a global hotkey. `key_combo` like "shift+alt+s".
    Returns True on success, False if keyboard lib unavailable.
    """
    if not _HAS_KEYBOARD:
        log.warning("keyboard lib not installed; hotkey %r not registered", key_combo)
        return False
    try:
        keyboard.add_hotkey(key_combo, handler, suppress=not repeat, trigger_on_release=False)
        log.info("hotkey registered: %s", key_combo)
        return True
    except Exception as e:
        log.error("hotkey %r failed: %s", key_combo, e)
        return False


def unhook_all() -> None:
    if _HAS_KEYBOARD:
        try:
            keyboard.unhook_all()
        except Exception:
            pass  # 退出清理，允许吞错