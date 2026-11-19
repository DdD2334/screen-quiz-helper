# -*- coding: utf-8 -*-
import threading
import time

from request_manager import RequestManager


def test_latest_wins():
    rm = RequestManager()
    results = []
    first_started = threading.Event()
    release = threading.Event()
    events = {}

    def slow(gen, ev):
        events["first"] = ev
        first_started.set()
        release.wait(3)
        if rm.is_current(gen) and not ev.is_set():
            results.append("first")

    def fast(gen, ev):
        if rm.is_current(gen) and not ev.is_set():
            results.append("second")

    g1 = rm.submit(slow)
    assert first_started.wait(3)
    g2 = rm.submit(fast)
    assert g2 == g1 + 1
    assert events["first"].is_set()  # 旧请求已被取消
    release.set()
    time.sleep(0.3)
    assert results == ["second"]


def test_is_current():
    rm = RequestManager()
    done = threading.Event()
    gens = []

    def fn(gen, ev):
        gens.append(gen)
        done.set()

    g = rm.submit(fn)
    assert done.wait(3)
    assert rm.is_current(g)
    rm.submit(lambda gen, ev: None)
    assert not rm.is_current(g)