# -*- coding: utf-8 -*-
"""config.py — v2 配置：唯一事实来源。

v2 要点：
- app_dir() 处理 PyInstaller frozen 路径（B17）：exe 运行时配置在 exe 旁边。
- config.json 不存在时自动生成默认配置，cfg.is_first_run=True（T7）。
- 兼容旧版：忽略 model 段里的 _presets/_note，剔除 extra._note（B15）。
- Config.save() 原子写：先写 tmp 再 os.replace（备忘 §5.7）。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def app_dir() -> Path:
    """配置/日志/截图的根目录：frozen 时为 exe 所在目录，源码时为工程目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_config_path() -> Path:
    return app_dir() / "config.json"


_HOTKEY_KEYS = ("capture_fullscreen", "capture_region", "copy_answers", "toggle_panel")


@dataclass
class ModelConfig:
    provider: str = "openai"
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    timeout_seconds: float = 60.0
    low_confidence_threshold: float = 0.6
    min_interval_seconds: float = 3.0
    json_mode: str = "auto"  # "auto" | "on" | "off"
    verify_low_confidence: bool = False
    prompt_extra: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class UIConfig:
    float_mode: str = "on_answer"  # "always" | "on_answer"
    default_corner: str = "bottom-right"
    show_capture_flash: bool = True
    capture_sound: bool = False
    history_size: int = 10
    field_visibility: dict[str, bool] = field(
        default_factory=lambda: {
            "answer": True,
            "confidence": True,
            "reasoning": True,
            "topic": True,
        }
    )


@dataclass
class CaptureConfig:
    debounce_ms: int = 1000
    keep_local_screenshot: bool = False
    monitor: str = "cursor"  # "cursor" | "primary"
    max_image_side: int = 2048
    image_format: str = "jpeg"  # "jpeg" | "png"
    jpeg_quality: int = 85


@dataclass
class ParseConfig:
    repair_pass: bool = True


@dataclass
class CacheConfig:
    enabled: bool = True  # T25 答案缓存（sha256 精确匹配）


@dataclass
class LogConfig:
    level: str = "INFO"
    to_file: bool = True


@dataclass
class Config:
    autostart: bool = False
    hotkeys: dict[str, str] = field(
        default_factory=lambda: {
            "capture_fullscreen": "shift+alt+s",
            "capture_region": "shift+alt+d",
            "copy_answers": "shift+alt+c",
            "toggle_panel": "shift+alt+h",
        }
    )
    model: ModelConfig = field(default_factory=ModelConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    parse: ParseConfig = field(default_factory=ParseConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    log: LogConfig = field(default_factory=LogConfig)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = Path(path) if path is not None else default_config_path()
        if not path.exists():
            cfg = cls()
            cfg.is_first_run = True  # 普通属性，不入 JSON
            cfg.save(path)
            return cfg
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        cfg = cls.from_dict(raw)
        cfg.is_first_run = False
        return cfg

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        cfg = cls()
        cfg.autostart = bool(raw.get("autostart", False))
        if isinstance(raw.get("hotkeys"), dict):
            for k in _HOTKEY_KEYS:
                if k in raw["hotkeys"]:
                    cfg.hotkeys[k] = str(raw["hotkeys"][k])

        m = raw.get("model", {})
        extra = m.get("extra", {})
        if isinstance(extra, dict):
            extra = {k: v for k, v in extra.items() if not k.startswith("_")}  # 剔除 _note 等
        else:
            extra = {}
        cfg.model = ModelConfig(
            provider=m.get("provider", "openai"),
            api_key=m.get("api_key", ""),
            api_base=m.get("api_base", "https://api.openai.com/v1"),
            model=m.get("model", "gpt-4o"),
            timeout_seconds=float(m.get("timeout_seconds", 60)),
            low_confidence_threshold=float(m.get("low_confidence_threshold", 0.6)),
            min_interval_seconds=float(m.get("min_interval_seconds", 3)),
            json_mode=m.get("json_mode", "auto"),
            verify_low_confidence=bool(m.get("verify_low_confidence", False)),
            prompt_extra=m.get("prompt_extra", ""),
            extra=extra,
        )
        # 旧版占位 key 视为未填
        if "PASTE" in cfg.model.api_key:
            cfg.model.api_key = ""

        u = raw.get("ui", {})
        vis = u.get("field_visibility", {})
        cfg.ui = UIConfig(
            float_mode=u.get("float_mode", "on_answer"),
            default_corner=u.get("default_corner", "bottom-right"),
            show_capture_flash=bool(u.get("show_capture_flash", True)),
            capture_sound=bool(u.get("capture_sound", False)),
            history_size=int(u.get("history_size", 10)),
            field_visibility={
                "answer": True,  # 答案不可隐藏
                "confidence": bool(vis.get("confidence", True)),
                "reasoning": bool(vis.get("reasoning", True)),
                "topic": bool(vis.get("topic", True)),
            },
        )

        c = raw.get("capture", {})
        cfg.capture = CaptureConfig(
            debounce_ms=int(c.get("debounce_ms", 1000)),
            keep_local_screenshot=bool(c.get("keep_local_screenshot", False)),
            monitor=c.get("monitor", "cursor"),
            max_image_side=int(c.get("max_image_side", 2048)),
            image_format=c.get("image_format", "jpeg"),
            jpeg_quality=int(c.get("jpeg_quality", 85)),
        )

        p = raw.get("parse", {})
        cfg.parse = ParseConfig(repair_pass=bool(p.get("repair_pass", True)))

        ca = raw.get("cache", {})
        cfg.cache = CacheConfig(enabled=bool(ca.get("enabled", True)))

        lg = raw.get("log", {})
        cfg.log = LogConfig(
            level=str(lg.get("level", "INFO")),
            to_file=bool(lg.get("to_file", True)),
        )
        return cfg

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "autostart": self.autostart,
            "hotkeys": {k: self.hotkeys[k] for k in _HOTKEY_KEYS if k in self.hotkeys},
            "model": {
                "provider": self.model.provider,
                "api_key": self.model.api_key,
                "api_base": self.model.api_base,
                "model": self.model.model,
                "timeout_seconds": self.model.timeout_seconds,
                "low_confidence_threshold": self.model.low_confidence_threshold,
                "min_interval_seconds": self.model.min_interval_seconds,
                "json_mode": self.model.json_mode,
                "verify_low_confidence": self.model.verify_low_confidence,
                "prompt_extra": self.model.prompt_extra,
                "extra": self.model.extra,
            },
            "capture": {
                "debounce_ms": self.capture.debounce_ms,
                "keep_local_screenshot": self.capture.keep_local_screenshot,
                "monitor": self.capture.monitor,
                "max_image_side": self.capture.max_image_side,
                "image_format": self.capture.image_format,
                "jpeg_quality": self.capture.jpeg_quality,
            },
            "ui": {
                "float_mode": self.ui.float_mode,
                "default_corner": self.ui.default_corner,
                "show_capture_flash": self.ui.show_capture_flash,
                "capture_sound": self.ui.capture_sound,
                "history_size": self.ui.history_size,
                "field_visibility": dict(self.ui.field_visibility),
            },
            "parse": {"repair_pass": self.parse.repair_pass},
            "cache": {"enabled": self.cache.enabled},
            "log": {"level": self.log.level, "to_file": self.log.to_file},
        }

    def save(self, path: Path | None = None) -> None:
        path = Path(path) if path is not None else default_config_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)  # 原子写，防写一半损坏


def load_config() -> Config:
    """Convenience wrapper：始终从 app_dir()/config.json 加载。"""
    return Config.load()