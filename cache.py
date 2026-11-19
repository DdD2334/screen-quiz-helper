# -*- coding: utf-8 -*-
"""cache.py — 答案缓存（T25）：只做 sha256 精确匹配，禁止任何模糊匹配。

缓存键 = sha256( sha256(预处理后图片字节) + provider + model + sha256(prompt_extra) )。
同网站同布局但题目文字不同的截图，感知哈希很可能相近，模糊命中会把上一题答案
错当本题答案——宁可不命中也不许误答。画面有任何变化（时钟跳动等）都不命中，属预期。
存储：内存 OrderedDict + 落盘 cache.json（上限 200 条 LRU，原子写）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import OrderedDict
from pathlib import Path

from config import app_dir

log = logging.getLogger("cache")

MAX_ENTRIES = 200


def make_key(image_bytes: bytes, provider: str, model: str, prompt_extra: str) -> str:
    img = hashlib.sha256(image_bytes).hexdigest()
    pe = hashlib.sha256((prompt_extra or "").encode("utf-8")).hexdigest()
    return hashlib.sha256((img + provider + model + pe).encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(self, path: Path | None = None, max_entries: int = MAX_ENTRIES) -> None:
        self._path = Path(path) if path is not None else app_dir() / "cache.json"
        self._max = max_entries
        self._entries: OrderedDict[str, list[dict]] = OrderedDict()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, list):
                        self._entries[k] = v
        except (OSError, ValueError) as e:
            log.warning("cache load failed (starting empty): %s", e)

    def _save(self) -> None:
        try:
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._entries, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as e:
            log.warning("cache save failed: %s", e)

    def get(self, key: str) -> list[dict] | None:
        """键完全相等才命中；命中移到 LRU 末尾。"""
        if key in self._entries:
            self._entries.move_to_end(key)
            return self._entries[key]
        return None

    def put(self, key: str, questions: list[dict]) -> None:
        self._entries[key] = questions
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)
        self._save()

    def clear(self) -> None:
        self._entries.clear()
        self._save()

    def __len__(self) -> int:
        return len(self._entries)