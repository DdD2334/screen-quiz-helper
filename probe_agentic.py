# -*- coding: utf-8 -*-
"""
Probe: verify parsing/agentic offline without burning rate limit.
- No real API key => import + parse tests only.
- Real key => 1 live call, then stop.
v2: 改用 parsing.py 的三级解析器；空输入返回 []（不再造空题）。
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from parsing import parse_questions  # noqa: E402
from agentic import AgenticClient  # noqa: E402


def build_test_text() -> str:
    return """===第1题===
题型: 单选
答案: B
置信度: 0.92
理由: 选项 B 符合题干描述。

===第2题===
题型: 多选
答案: A, C, D
置信度: 0.55
理由: A/C/D 正确，B 错误。"""


def main() -> int:
    print("== parse_questions unit test ==")
    qs = parse_questions(build_test_text())
    assert len(qs) == 2, f"expected 2 questions, got {len(qs)}"
    assert qs[0].index == 1 and qs[0].topic == "单选" and qs[0].answer == "B"
    assert qs[0].confidence == 0.92
    assert qs[1].index == 2 and qs[1].topic == "多选" and qs[1].answer == "A, C, D"
    assert qs[1].confidence == 0.55
    print("delimiter parse: PASS")

    # JSON 一级解析
    js = '{"questions":[{"index":1,"type":"判断","question":"摘要","answer":"对","confidence":0.8,"reason":"r"}]}'
    qs_j = parse_questions(js)
    assert len(qs_j) == 1 and qs_j[0].answer == "对" and qs_j[0].question == "摘要"
    print("json parse: PASS")

    # No-delimiter fallback
    qs2 = parse_questions("答案: X")
    assert len(qs2) == 1 and qs2[0].answer == "答案: X"
    print("no-delimiter fallback: PASS")

    # Empty input => [] (v2)
    assert parse_questions("") == []
    assert parse_questions("   ") == []
    print("empty input: PASS")

    print("\n== live call (if API key present) ==")
    cfg_path = os.path.join(HERE, "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        cfg = json.load(open(cfg_path, encoding="utf-8"))
    key = cfg.get("model", {}).get("api_key", "")
    base = cfg.get("model", {}).get("api_base", "https://api.openai.com/v1")
    model = cfg.get("model", {}).get("model", "gpt-4o")
    print(f"key={'(set)' if key and 'PASTE' not in key else '(missing)'} base={base} model={model}")
    if not key or "PASTE" in key:
        print("SKIP live call: no real API key in config.json")
        return 0

    client = AgenticClient(api_key=key, api_base=base, model=model,
                           provider=cfg.get("model", {}).get("provider", ""),
                           min_interval=0)
    img_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()
    try:
        live_qs = client.ask(img_b64)
        print(f"live call OK: {len(live_qs)} question(s)")
        for q in live_qs:
            print(f"  Q{q.index} topic={q.topic!r} answer={q.answer!r} conf={q.confidence}")
    except Exception as e:
        print(f"live call FAILED: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())