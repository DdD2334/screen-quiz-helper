# -*- coding: utf-8 -*-
"""presets.py — 8 家 OpenAI 兼容视觉模型服务商预设（从 config.json._presets 挪出）。

supports_json_mode：该服务商是否支持 response_format={"type":"json_object"}。
json_mode="auto" 时据此决定要不要带该字段；不在预设中的 provider 一律保守不带。
"""
from __future__ import annotations

PRESETS: dict[str, dict] = {
    "agentic": {
        "label": "Agnes AI",
        "api_base": "https://api.agnes-ai.cn/v1",  # 官方文档：国内服务；海外为 https://apihub.agnes-ai.com/v1
        "model": "agnes-3.0-flash",
        "min_interval_seconds": 45,
        "extra": {},
        "supports_json_mode": False,
    },
    "openai": {
        "label": "OpenAI",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "min_interval_seconds": 3,
        "extra": {},
        "supports_json_mode": True,
    },
    "azure": {
        "label": "Azure OpenAI",
        # 官方路径：https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version=...
        # 把 YOUR_RESOURCE / YOUR_DEPLOYMENT 换成你的资源名与部署名，模型名填部署名
        "api_base": "https://YOUR_RESOURCE.openai.azure.com/openai/deployments/YOUR_DEPLOYMENT",
        "model": "gpt-4o",
        "min_interval_seconds": 5,
        "extra": {"api_version": "2024-10-21"},
        "supports_json_mode": False,
    },
    "qwen-vl": {
        "label": "通义千问 VL",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
        "min_interval_seconds": 10,
        "extra": {},
        "supports_json_mode": True,
    },
    "gemini": {
        "label": "Gemini（OpenAI 兼容）",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.8-flash",  # 官方当前主力 Flash（1.5 系列已停用）
        "min_interval_seconds": 10,
        "extra": {},
        "supports_json_mode": True,
    },
    "moonshot": {
        "label": "Moonshot（Kimi）",
        "api_base": "https://api.moonshot.cn/v1",  # 海外为 https://api.moonshot.ai/v1
        "model": "kimi-k3",  # 官方主力，原生支持图片输入
        "min_interval_seconds": 10,
        "extra": {},
        "supports_json_mode": False,
    },
    "ollama": {
        "label": "Ollama（本地）",
        "api_base": "http://localhost:11434/v1",
        "model": "llava",
        "min_interval_seconds": 1,
        "extra": {},
        "supports_json_mode": False,
    },
    "openrouter": {
        "label": "OpenRouter",
        "api_base": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o",
        "min_interval_seconds": 5,
        "extra": {},
        "supports_json_mode": True,
    },
}