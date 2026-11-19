# -*- coding: utf-8 -*-
"""parsing.py — 三级解析器（T11，修 B14）：JSON → 分隔符 → 兜底，按顺序尝试成功即返回。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("parsing")


@dataclass
class Question:
    index: int
    topic: str = ""
    answer: str = ""
    confidence: float | None = None
    reasoning: str = ""
    question: str = ""  # 题干摘要（v2 新增）

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "topic": self.topic,
            "answer": self.answer,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "question": self.question,
        }


def _clamp01(f: float) -> float:
    return max(0.0, min(1.0, f))


def _conf_from_any(v: Any) -> float | None:
    """JSON 字段用：能直接 float 就 clamp；否则提取首个数字，>1 视为百分制。"""
    if v is None:
        return None
    try:
        return _clamp01(float(v))
    except (TypeError, ValueError):
        return _conf_from_text(str(v))


def _conf_from_text(s: str) -> float | None:
    """文本用：提取首个数字，>1 视为百分制除以 100，clamp [0,1]。"""
    m = re.search(r"\d*\.?\d+", s)
    if not m:
        return None
    f = float(m.group())
    if f > 1:
        f /= 100.0
    return _clamp01(f)


# ----------------------------------------------------------------------
# 第 1 级：JSON
# ----------------------------------------------------------------------

def _try_json(text: str) -> list[Question] | None:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("questions"), list):
        return None
    items = obj["questions"]
    if not items:
        return []  # 空题列表（含 note 情形），调用方显示 note
    out: list[Question] = []
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index", i))
        except (TypeError, ValueError):
            idx = i
        out.append(Question(
            index=idx,
            topic=str(item.get("type") or ""),
            answer=str(item.get("answer") or ""),
            confidence=_conf_from_any(item.get("confidence")),
            reasoning=str(item.get("reason") or ""),
            question=str(item.get("question") or ""),
        ))
    return out or None


# ----------------------------------------------------------------------
# 第 2 级：分隔符（兼容旧格式与模型不听话）
# ----------------------------------------------------------------------

_SEP_PATTERNS = [
    re.compile(r"[=＝]{2,}\s*第\s*(\d+)\s*题\s*[=＝]{2,}"),
    re.compile(r"^#{1,4}\s*第\s*(\d+)\s*题", re.MULTILINE),
    re.compile(r"^第\s*(\d+)\s*题\s*[:：]?\s*$", re.MULTILINE),
]

# 键名后允许残留 Markdown 加粗星号；半角全角冒号都认
_FIELD_RE = re.compile(r"^(题型|类型|答案|置信度|理由|解析|题目|题干)[*\s]*[:：]\s*(.*)$")
_FIELD_MAP = {
    "题型": "topic", "类型": "topic",
    "答案": "answer",
    "置信度": "confidence",
    "理由": "reasoning", "解析": "reasoning",
    "题目": "question", "题干": "question",
}


def _parse_section(section: str, index: int) -> Question:
    fields: dict[str, str] = {}
    current: str | None = None
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^[*#\-\s]+", "", line)
        m = _FIELD_RE.match(cleaned)
        if m:
            current = _FIELD_MAP[m.group(1)]
            fields[current] = m.group(2).strip().rstrip("*").strip()
        elif current is not None:
            # 续行：追加到当前字段（修 B14 多行丢失）
            fields[current] = (fields[current] + "\n" + line).strip()
    return Question(
        index=index,
        topic=fields.get("topic", ""),
        answer=fields.get("answer", ""),
        confidence=_conf_from_text(fields["confidence"]) if "confidence" in fields else None,
        reasoning=fields.get("reasoning", ""),
        question=fields.get("question", ""),
    )


def _try_delimiter(text: str) -> list[Question] | None:
    for pattern in _SEP_PATTERNS:
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        out: list[Question] = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            out.append(_parse_section(text[start:end], int(m.group(1))))
        return out
    return None


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

def parse_questions(text: str) -> list[Question]:
    if not text or not text.strip():
        return []  # 空白不再造一题空答案
    qs = _try_json(text)
    if qs is not None:
        return qs
    qs = _try_delimiter(text)
    if qs is not None:
        return qs
    # 第 3 级兜底：整段文本当一题
    return [Question(index=1, answer=text.strip())]


def answers_digest(questions: list[Question]) -> str:
    """速览串：1.B  2.ACD  3.对（answer 超 20 字截断加 …）。"""
    parts = []
    for q in questions:
        ans = q.answer.strip()
        if len(ans) > 20:
            ans = ans[:20] + "…"
        parts.append(f"{q.index}.{ans}")
    return "  ".join(parts)