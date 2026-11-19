# -*- coding: utf-8 -*-
"""request_manager.py — latest-wins 请求调度（T13）：新请求作废旧请求，旧结果不许污染 UI。"""
from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger("request_manager")


class RequestManager:
    def __init__(self) -> None:
        self._generation = 0
        self._cancel_event: threading.Event | None = None
        self._lock = threading.Lock()

    @property
    def generation(self) -> int:
        return self._generation

    def is_current(self, generation: int) -> bool:
        """回调前必须检查：不等的旧请求结果一律丢弃（覆盖 partial/questions/error 三处）。"""
        return generation == self._generation

    def submit(self, fn: Callable[[int, threading.Event], None]) -> int:
        """fn(generation, cancel_event) 在 daemon 线程执行；返回本次 generation。"""
        with self._lock:
            self._generation += 1
            gen = self._generation
            if self._cancel_event is not None:
                self._cancel_event.set()
                log.info("generation %d cancelled by newer request", gen - 1)
            ev = threading.Event()
            self._cancel_event = ev

        def _runner() -> None:
            try:
                fn(gen, ev)
            except Exception:
                log.exception("request worker crashed (generation %d)", gen)

        threading.Thread(target=_runner, daemon=True).start()
        return gen

    def cancel_current(self) -> None:
        with self._lock:
            if self._cancel_event is not None:
                self._cancel_event.set()