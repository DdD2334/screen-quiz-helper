# -*- coding: utf-8 -*-
"""applog.py — 日志初始化：控制台 + 滚动文件，API key 脱敏（T8）。"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from config import app_dir

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+\S+"),
]


class _SecretFilter(logging.Filter):
    """把 sk- 长 token 和 Bearer xxx 替换为 ***，防止 key 落盘。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for pat in _SECRET_PATTERNS:
            msg = pat.sub("***", msg)
        record.msg = msg
        record.args = ()
        return True


def setup_logging(cfg) -> None:
    level = getattr(logging, str(cfg.log.level).upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    secret = _SecretFilter()

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(secret)
    root.addHandler(console)

    if cfg.log.to_file:
        log_dir = app_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        fh.addFilter(secret)
        root.addHandler(fh)

    # 避免请求体刷屏
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)