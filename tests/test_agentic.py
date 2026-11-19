# -*- coding: utf-8 -*-
"""test_agentic — httpx.MockTransport，无网络。"""
import json
import threading

import httpx
import pytest

from agentic import AgenticClient, ModelError

SSE_OK = (
    'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"世界"}}]}\n\n'
    "data: [DONE]\n\n"
)


def make_client(handler, **kw):
    kw.setdefault("min_interval", 0)
    kw.setdefault("api_key", "sk-test-12345678")
    return AgenticClient(transport=httpx.MockTransport(handler), **kw)


def test_sse_normal():
    client = make_client(lambda req: httpx.Response(200, text=SSE_OK))
    assert "".join(client.ask_stream("aW1n")) == "你好世界"


def test_sse_ask_parses_json():
    body = '{"questions":[{"index":1,"type":"单选","answer":"B","confidence":0.9,"reason":"r"}]}'
    sse = f'data: {json.dumps({"choices":[{"delta":{"content":body}}]})}\n\ndata: [DONE]\n\n'
    client = make_client(lambda req: httpx.Response(200, text=sse))
    qs = client.ask("aW1n")
    assert len(qs) == 1 and qs[0].answer == "B"


def test_429_twice_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, text=SSE_OK)

    client = make_client(handler)
    assert "".join(client.ask_stream("aW1n")) == "你好世界"
    assert calls["n"] == 3


def test_429_exhausted():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = make_client(handler)
    with pytest.raises(ModelError):
        list(client.ask_stream("aW1n"))
    assert calls["n"] == 4  # 首次 + 3 次重试


def test_400_response_format_fallback():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(400, text="Unsupported parameter: response_format")
        return httpx.Response(200, text=SSE_OK)

    client = make_client(handler, json_mode="on")
    assert "".join(client.ask_stream("aW1n")) == "你好世界"
    assert seen == [True, False]
    assert client._json_mode_works is False
    # 后续请求不再带 response_format
    "".join(client.ask_stream("aW1n"))
    assert seen[-1] is False


def test_401_human_message():
    client = make_client(lambda req: httpx.Response(401, text="invalid key"))
    with pytest.raises(ModelError, match="API key"):
        list(client.ask_stream("aW1n"))


def test_404_human_message():
    client = make_client(lambda req: httpx.Response(404, text="not found"))
    with pytest.raises(ModelError, match="api_base"):
        list(client.ask_stream("aW1n"))


def test_cancel_before_start():
    client = make_client(lambda req: httpx.Response(200, text=SSE_OK))
    ev = threading.Event()
    ev.set()
    assert list(client.ask_stream("aW1n", cancel_event=ev)) == []


def test_cancel_mid_stream():
    ev = threading.Event()

    def handler(req):
        return httpx.Response(200, text=SSE_OK)

    client = make_client(handler)
    chunks = []
    for delta in client.ask_stream("aW1n", cancel_event=ev):
        chunks.append(delta)
        ev.set()  # 收到第一块后取消
    assert chunks == ["你好"]


def test_extra_api_version_query():
    urls = []

    def handler(req):
        urls.append(str(req.url))
        body = json.loads(req.content)
        assert "api_version" not in body  # 特殊键必须从 body 拿出
        return httpx.Response(200, text=SSE_OK)

    client = make_client(handler, provider="azure", extra={"api_version": "2024-08-01"})
    list(client.ask_stream("aW1n"))
    assert "api-version=2024-08-01" in urls[0]


def test_empty_stream():
    client = make_client(lambda req: httpx.Response(200, text="data: [DONE]\n\n"))
    with pytest.raises(ModelError, match="空内容"):
        list(client.ask_stream("aW1n"))


def test_json_mode_auto_by_provider():
    seen = []

    def handler(req):
        seen.append("response_format" in json.loads(req.content))
        return httpx.Response(200, text=SSE_OK)

    make_client(handler, provider="openai", json_mode="auto").ask("aW1n")
    make_client(handler, provider="ollama", json_mode="auto").ask("aW1n")
    make_client(handler, provider="自定义", json_mode="auto").ask("aW1n")
    make_client(handler, provider="openai", json_mode="off").ask("aW1n")
    assert seen == [True, False, False, False]


def test_repair():
    repaired = '{"questions":[{"index":1,"type":"单选","answer":"B","confidence":0.9,"reason":"r"}]}'

    def handler(req):
        body = json.loads(req.content)
        assert body["stream"] is False
        assert "待转换文本" in body["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": repaired}}]})

    client = make_client(handler)
    qs = client.repair("乱七八糟的原文")
    assert len(qs) == 1 and qs[0].answer == "B"


def test_repair_failure_fallback():
    client = make_client(lambda req: httpx.Response(401))
    qs = client.repair("原始文本")
    assert len(qs) == 1 and qs[0].answer == "原始文本"


def test_test_connection():
    def handler(req):
        body = json.loads(req.content)
        assert body["max_tokens"] == 8 and body["stream"] is False
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    client = make_client(handler, min_interval=999)  # 必须绕过限流
    assert client.test_connection() == "OK"


def test_connection_error_human_message():
    def handler(req):
        raise httpx.ConnectError("refused")

    client = make_client(handler)
    with pytest.raises(ModelError, match="无法连接服务器"):
        list(client.ask_stream("aW1n"))