# -*- coding: utf-8 -*-
from config import Config
from prompts import REPAIR_PROMPT, SYSTEM_PROMPT, USER_PROMPT, build_system_prompt


def test_constants_exist():
    assert "JSON" in SYSTEM_PROMPT and "confidence" in SYSTEM_PROMPT
    assert "待转换文本" in REPAIR_PROMPT
    assert USER_PROMPT


def test_build_system_prompt_plain():
    cfg = Config()
    assert build_system_prompt(cfg) == SYSTEM_PROMPT


def test_build_system_prompt_extra():
    cfg = Config()
    cfg.model.prompt_extra = "这是计算机网络方向的测评题"
    p = build_system_prompt(cfg)
    assert p == SYSTEM_PROMPT + "\n\n补充背景：这是计算机网络方向的测评题"