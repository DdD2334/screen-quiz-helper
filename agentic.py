# -*- coding: utf-8 -*-
"""agentic.py — OpenAI 兼容视觉模型客户端（T12 重写）。

- 真 SSE 流式 ask_stream；ask 聚合后走 parsing 三级解析。
- 429 读 Retry-After 退避重试（最多 3 次）；网络错误 1/2/4s 重试。
- json_mode auto/on/off；400 含 response_format 字样时去字段重发一次并记住。
- extra 透传请求体；api_version 特殊键拼为 URL query（Azure，修 B15）。
- 限流间隔从上次请求完成时刻起算，0.5s 步进倒计时可取消。
- 所有人话错误用 ModelError 承载，UI 直接显示 str(e)。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Iterator
from urllib.parse import quote

from parsing import Question, parse_questions  # re-export 保持旧导入路径兼容
from prompts import REPAIR_PROMPT, SYSTEM_PROMPT, USER_PROMPT

log = logging.getLogger("agentic")

DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_TIMEOUT = 60.0
MIN_INTERVAL_SECONDS = 3.0

BACKOFF_SCHEDULE = [1.0, 2.0, 4.0]
MAX_RETRIES = len(BACKOFF_SCHEDULE)


class ModelError(RuntimeError):
    """人话错误信息，UI 直接显示。"""


class AgenticClient:
    def __init__(
        self,
        api_key: str = "",
        api_base: str = DEFAULT_API_BASE,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval: float = MIN_INTERVAL_SECONDS,
        verbose: bool = False,
        provider: str = "",
        json_mode: str = "auto",
        extra: dict | None = None,
        on_status: Callable[[str], None] | None = None,
        transport: Any = None,  # 测试注入 httpx.MockTransport
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self.min_interval = float(min_interval)
        self.verbose = verbose
        self.provider = provider
        self.json_mode = json_mode
        self.extra = dict(extra or {})
        self.on_status = on_status
        self._transport = transport
        self._lock = threading.Lock()
        self._last_done_ts: float = 0.0  # 上次请求完成时刻（monotonic）
        self._json_mode_works = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ask(self, image_b64: str, prompt: str = "", system: str = "",
            cancel_event: threading.Event | None = None, mime: str = "image/png") -> list[Question]:
        text = "".join(self.ask_stream(image_b64, prompt, system, cancel_event, mime))
        if not text.strip():
            raise ModelError("模型返回了空内容，请重试或换模型")
        return parse_questions(text)

    def ask_stream(self, image_b64: str, prompt: str = "", system: str = "",
                   cancel_event: threading.Event | None = None,
                   mime: str = "image/png") -> Iterator[str]:
        self._throttle(cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return
        body = self._build_body(image_b64, prompt, system, mime)
        try:
            yield from self._stream_with_retry(body, cancel_event)
        finally:
            self._last_done_ts = time.monotonic()

    def repair(self, raw_text: str, cancel_event: threading.Event | None = None) -> list[Question]:
        """解析失败后的纯文本修复请求（无图）。失败返回第 3 级兜底。"""
        self._throttle(cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return []
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "temperature": 0,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": REPAIR_PROMPT + raw_text},
                {"role": "user", "content": "请输出转换后的 JSON。"},
            ],
        }
        if self._json_enabled():
            body["response_format"] = {"type": "json_object"}
        body.update(self.extra)
        try:
            data = self._post_nonstream(body)
            text = self._extract_text(data)
            qs = parse_questions(text)
            if qs:
                return qs
        except ModelError as e:
            log.warning("repair pass failed: %s", e)
        stripped = raw_text.strip()
        return [Question(index=1, answer=stripped)] if stripped else []

    def ask_text(self, prompt: str, system: str = "",
                 cancel_event: threading.Event | None = None) -> str:
        """纯文本请求（T25 追问讲解用），受限流与 429 退避约束，返回原始文本。"""
        self._throttle(cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return ""
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "temperature": 0.3,
            "max_tokens": 4096,
            "messages": messages,
        }
        body.update(self.extra)
        data = self._post_nonstream(body)
        return self._extract_text(data)

    def test_connection(self) -> str:
        """极小纯文本请求，绕过 min_interval。成功返回模型回复，失败抛 ModelError。"""
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "回复 OK 两个字"}],
        }
        body.update(self.extra)
        data = self._post_nonstream(body, timeout=10.0, retries=False)
        return self._extract_text(data) or "(模型已连通，但回复为空)"

    # ------------------------------------------------------------------
    # 请求体 / URL / 头
    # ------------------------------------------------------------------
    def _json_enabled(self) -> bool:
        if not self._json_mode_works or self.json_mode == "off":
            return False
        if self.json_mode == "on":
            return True
        from presets import PRESETS
        return bool(PRESETS.get(self.provider, {}).get("supports_json_mode", False))

    def _build_body(self, image_b64: str, prompt: str, system: str, mime: str) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system or SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": prompt or USER_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ]},
        ]
        body: dict[str, Any] = {
            "model": self.model,
            "stream": True,
            "temperature": 0.2,
            "max_tokens": 4096,
            "messages": messages,
        }
        if self._json_enabled():
            body["response_format"] = {"type": "json_object"}
        body.update(self.extra)
        return body

    def _url(self, body: dict[str, Any]) -> str:
        url = f"{self.api_base}/chat/completions"
        api_version = body.pop("api_version", None)  # Azure 特殊键 → query
        if api_version:
            url += f"?api-version={quote(str(api_version))}"
        return url

    def _headers(self) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if self.provider == "azure":
            h["api-key"] = self.api_key  # Azure 原生 key 头
        return h

    def _status(self, msg: str) -> None:
        if self.on_status is not None:
            try:
                self.on_status(msg)
            except Exception as e:
                log.debug("on_status callback failed: %s", e)

    # ------------------------------------------------------------------
    # 限流 / 可取消 sleep
    # ------------------------------------------------------------------
    def _throttle(self, cancel_event: threading.Event | None) -> None:
        while True:
            with self._lock:
                if self._last_done_ts <= 0:
                    return
                remaining = self.min_interval - (time.monotonic() - self._last_done_ts)
            if remaining <= 0:
                return
            if cancel_event is not None and cancel_event.is_set():
                return
            self._status(f"距下次可调用还需 {remaining:.0f}s")
            time.sleep(min(0.5, remaining))

    def _sleep_cancel(self, seconds: float, cancel_event: threading.Event | None) -> bool:
        """可取消 sleep；返回 True 表示期间被取消。"""
        end = time.monotonic() + max(0.0, seconds)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return True
            left = end - time.monotonic()
            if left <= 0:
                return False
            time.sleep(min(0.2, left))

    # ------------------------------------------------------------------
    # SSE 流式 + 重试
    # ------------------------------------------------------------------
    def _stream_with_retry(self, body: dict[str, Any], cancel_event: threading.Event | None) -> Iterator[str]:
        import httpx

        attempts = 0
        json_retried = False
        yielded_any = False
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return
            try:
                with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10),
                                  transport=self._transport) as client:
                    with client.stream("POST", self._url(body), json=body,
                                       headers=self._headers()) as resp:
                        status = resp.status_code
                        if status == 429:
                            resp.read()
                            if attempts >= MAX_RETRIES:
                                raise ModelError("限流重试 3 次仍失败，请稍后再试或在设置中调大最小间隔")
                            wait = self._retry_after(resp) or BACKOFF_SCHEDULE[attempts]
                            attempts += 1
                            log.warning("429 rate-limited; retry in %.1fs (%d/%d)", wait, attempts, MAX_RETRIES)
                            self._status(f"限流中，{wait:.0f} 秒后重试…")
                            if self._sleep_cancel(wait, cancel_event):
                                return
                            continue
                        if status == 400:
                            resp.read()
                            text = resp.text
                            if (not json_retried and "response_format" in body
                                    and "response_format" in text.lower()):
                                body.pop("response_format", None)
                                self._json_mode_works = False
                                json_retried = True
                                log.info("server rejected response_format; resending without it")
                                continue
                            raise ModelError(f"请求被拒绝：{text[:200]}")
                        if status == 401:
                            raise ModelError("API key 无效或未填写")
                        if status == 404:
                            raise ModelError("api_base 或模型名不对")
                        if status >= 400:
                            resp.read()
                            raise ModelError(f"请求失败 HTTP {status}：{resp.text[:200]}")

                        for line in resp.iter_lines():
                            if cancel_event is not None and cancel_event.is_set():
                                return
                            if not line or line.startswith(":"):
                                continue  # 空行 / keep-alive 注释行
                            if not line.startswith("data:"):
                                continue
                            data = line[len("data:"):].strip()
                            if data == "[DONE]":
                                break
                            try:
                                obj = json.loads(data)
                                delta = obj["choices"][0]["delta"].get("content")
                            except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError):
                                continue  # 单行坏 JSON 容错跳过
                            if delta:
                                yielded_any = True
                                yield delta
                        if not yielded_any:
                            raise ModelError("模型返回了空内容，请重试或换模型")
                        return
            except ModelError:
                raise
            except httpx.TimeoutException as e:
                if yielded_any or attempts >= MAX_RETRIES:
                    raise ModelError(f"模型响应超时（{self.timeout:.0f}s），可在设置中调大") from e
                wait = BACKOFF_SCHEDULE[attempts]
                attempts += 1
                log.warning("timeout; retry in %.1fs (%d/%d)", wait, attempts, MAX_RETRIES)
                self._status(f"响应超时，{wait:.0f} 秒后重试…")
                if self._sleep_cancel(wait, cancel_event):
                    return
            except httpx.HTTPError as e:
                if yielded_any or attempts >= MAX_RETRIES:
                    raise ModelError("无法连接服务器，检查网络或 api_base") from e
                wait = BACKOFF_SCHEDULE[attempts]
                attempts += 1
                log.warning("connect error; retry in %.1fs (%d/%d): %s", wait, attempts, MAX_RETRIES, e)
                self._status(f"连接失败，{wait:.0f} 秒后重试…")
                if self._sleep_cancel(wait, cancel_event):
                    return

    @staticmethod
    def _retry_after(resp) -> float | None:
        val = resp.headers.get("Retry-After")
        if val is None:
            return None
        try:
            return max(0.0, float(val))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # 非流式（repair / test_connection）
    # ------------------------------------------------------------------
    def _post_nonstream(self, body: dict[str, Any], timeout: float | None = None,
                        retries: bool = True) -> dict[str, Any]:
        import httpx

        attempts = 0
        json_retried = False
        max_retries = MAX_RETRIES if retries else 0
        while True:
            try:
                with httpx.Client(timeout=httpx.Timeout(timeout or self.timeout, connect=10),
                                  transport=self._transport) as client:
                    resp = client.post(self._url(body), json=body, headers=self._headers())
            except httpx.TimeoutException as e:
                if attempts >= max_retries:
                    raise ModelError(f"模型响应超时（{timeout or self.timeout:.0f}s），可在设置中调大") from e
                wait = BACKOFF_SCHEDULE[attempts]
                attempts += 1
                self._status(f"响应超时，{wait:.0f} 秒后重试…")
                time.sleep(wait)
                continue
            except httpx.HTTPError as e:
                if attempts >= max_retries:
                    raise ModelError("无法连接服务器，检查网络或 api_base") from e
                wait = BACKOFF_SCHEDULE[attempts]
                attempts += 1
                self._status(f"连接失败，{wait:.0f} 秒后重试…")
                time.sleep(wait)
                continue

            status = resp.status_code
            if status == 429:
                if attempts >= max_retries:
                    raise ModelError("限流重试后仍失败，请稍后再试")
                wait = self._retry_after(resp) or BACKOFF_SCHEDULE[attempts]
                attempts += 1
                self._status(f"限流中，{wait:.0f} 秒后重试…")
                time.sleep(wait)
                continue
            if status == 400:
                text = resp.text
                if (not json_retried and "response_format" in body
                        and "response_format" in text.lower()):
                    body.pop("response_format", None)
                    self._json_mode_works = False
                    json_retried = True
                    continue
                raise ModelError(f"请求被拒绝：{text[:200]}")
            if status == 401:
                raise ModelError("API key 无效或未填写")
            if status == 404:
                raise ModelError("api_base 或模型名不对")
            if status >= 400:
                raise ModelError(f"请求失败 HTTP {status}：{resp.text[:200]}")
            try:
                return resp.json()
            except ValueError as e:
                raise ModelError("服务器返回了非 JSON 内容，检查 api_base 是否正确") from e

    @staticmethod
    def _extract_text(raw: dict[str, Any]) -> str:
        try:
            return raw["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            log.error("unexpected response shape: %s", json.dumps(raw, ensure_ascii=False)[:500])
            return ""