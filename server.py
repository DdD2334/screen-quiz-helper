# -*- coding: utf-8 -*-
"""server.py — 可选 FastAPI 通道（T19 降级）。

可选组件，主程序不依赖本文件；安装依赖后可用：
    pip install -r requirements-server.txt
    python server.py
/ask 为非流式接口（stream 参数暂不支持）。
"""
from __future__ import annotations

import base64
import json
import logging
import threading
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agentic import AgenticClient, Question
from config import Config, load_config

log = logging.getLogger("server")

PROJECT_DIR = Path(__file__).resolve().parent

# ----------------------------------------------------------------------
# App factory
# ----------------------------------------------------------------------

app = FastAPI(title="screen-quiz-helper", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_state = {
    "client": None,  # AgenticClient
    "cfg": None,  # Config
    "busy": False,  # single-flight guard
    "lock": threading.Lock(),
}


def get_client() -> AgenticClient:
    assert _state["client"] is not None, "server not initialized (call /init first)"
    return _state["client"]


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------

class AskPayload(BaseModel):
    image_b64: str
    prompt: str = ""
    system: str = ""


class AskResponse(BaseModel):
    questions: list[dict[str, Any]]
    error: str | None = None


class InitPayload(BaseModel):
    api_key: str | None = None
    api_base: str | None = None
    model: str | None = None
    min_interval_seconds: float | None = None


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "initialized": _state["client"] is not None}


@app.post("/init")
def init(p: InitPayload | None = None) -> dict[str, Any]:
    """
    Initialize the AgenticClient. Reads config.json by default;
    optional fields allow runtime overrides (e.g., a fresh API key pasted
    in the UI).
    """
    cfg = load_config()
    if p:
        if p.api_key:
            cfg.model.api_key = p.api_key
        if p.api_base:
            cfg.model.api_base = p.api_base
        if p.model:
            cfg.model.model = p.model
        if p.min_interval_seconds is not None:
            cfg.model.min_interval_seconds = p.min_interval_seconds

    interval = float(cfg.model.min_interval_seconds)
    client = AgenticClient(
        api_key=cfg.model.api_key,
        api_base=cfg.model.api_base,
        model=cfg.model.model,
        timeout=cfg.model.timeout_seconds,
        min_interval=interval,
        provider=cfg.model.provider,
        json_mode=cfg.model.json_mode,
        extra=cfg.model.extra,
    )
    _state["client"] = client
    _state["cfg"] = cfg
    log.info("init complete: provider=%s model=%s base=%s interval=%.1fs",
             cfg.model.provider, cfg.model.model, cfg.model.api_base, interval)
    return {"ok": True, "provider": cfg.model.provider, "model": cfg.model.model, "min_interval_seconds": interval}


@app.post("/ask")
def ask(p: AskPayload) -> AskResponse:
    """
    Accept a base64-encoded PNG/JPEG, forward to the model, parse the
    answer, and return a list of question dicts.
    """
    client = get_client()
    with _state["lock"]:
        if _state["busy"]:
            # single-flight: drop old request (DESIGN.md §3: keep latest only)
            log.warning("busy: dropping request (single-flight)")
            return AskResponse(questions=[], error="busy: previous request still in flight")
        _state["busy"] = True
    try:
        qs: list[Question] = client.ask(p.image_b64, prompt=p.prompt, system=p.system)
        return AskResponse(questions=[q.to_dict() for q in qs])
    except Exception as e:
        log.exception("ask failed")
        return AskResponse(questions=[], error=f"{type(e).__name__}: {e}")
    finally:
        with _state["lock"]:
            _state["busy"] = False


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    log.info("starting server on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    run_server(host=args.host, port=args.port)
