# -*- coding: utf-8 -*-
"""test_cache — sha256 精确缓存：差 1 字节/换模型/改 prompt_extra 都不命中；LRU；落盘。"""
from cache import AnswerCache, make_key

IMG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
QS = [{"index": 1, "topic": "单选", "answer": "B", "confidence": 0.9, "reasoning": "r", "question": "q"}]


def key(img=IMG, provider="openai", model="gpt-4o", extra=""):
    return make_key(img, provider, model, extra)


def test_exact_hit(tmp_path):
    c = AnswerCache(tmp_path / "cache.json")
    c.put(key(), QS)
    assert c.get(key()) == QS


def test_one_byte_diff_miss(tmp_path):
    c = AnswerCache(tmp_path / "cache.json")
    c.put(key(), QS)
    assert c.get(key(img=IMG + b"\x01")) is None
    assert c.get(key(img=IMG[:-1] + b"\x01")) is None


def test_model_change_miss(tmp_path):
    c = AnswerCache(tmp_path / "cache.json")
    c.put(key(), QS)
    assert c.get(key(model="gpt-4o-mini")) is None
    assert c.get(key(provider="qwen-vl")) is None


def test_prompt_extra_change_miss(tmp_path):
    c = AnswerCache(tmp_path / "cache.json")
    c.put(key(extra="计算机网络"), QS)
    assert c.get(key(extra="操作系统")) is None
    assert c.get(key(extra="")) is None


def test_lru_eviction(tmp_path):
    c = AnswerCache(tmp_path / "cache.json", max_entries=200)
    for i in range(201):
        c.put(key(img=bytes([i % 256]) * 8 + i.to_bytes(4, "big")), QS)
    assert len(c) == 200
    # 最旧的一条被淘汰
    oldest = key(img=bytes([0]) * 8 + (0).to_bytes(4, "big"))
    assert c.get(oldest) is None
    newest = key(img=bytes([200 % 256]) * 8 + (200).to_bytes(4, "big"))
    assert c.get(newest) == QS


def test_lru_touch(tmp_path):
    c = AnswerCache(tmp_path / "cache.json", max_entries=2)
    k1, k2, k3 = key(img=b"a"), key(img=b"b"), key(img=b"c")
    c.put(k1, QS)
    c.put(k2, QS)
    c.get(k1)  # touch k1，k2 变最旧
    c.put(k3, QS)
    assert c.get(k1) == QS
    assert c.get(k2) is None


def test_persistence(tmp_path):
    p = tmp_path / "cache.json"
    c = AnswerCache(p)
    c.put(key(), QS)
    c2 = AnswerCache(p)
    assert c2.get(key()) == QS


def test_clear(tmp_path):
    p = tmp_path / "cache.json"
    c = AnswerCache(p)
    c.put(key(), QS)
    c.clear()
    assert c.get(key()) is None
    assert AnswerCache(p).get(key()) is None