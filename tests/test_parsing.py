# -*- coding: utf-8 -*-
"""第八节 test_parsing 用例表。"""
import json

from parsing import Question, answers_digest, parse_questions

STD = '{"questions":[{"index":1,"type":"单选","question":"题干摘要","answer":"B","confidence":0.92,"reason":"依据"}]}'


def test_json_standard():
    qs = parse_questions(STD)
    assert len(qs) == 1
    q = qs[0]
    assert q.index == 1 and q.topic == "单选" and q.question == "题干摘要"
    assert q.answer == "B" and q.confidence == 0.92 and q.reasoning == "依据"


def test_json_fenced():
    qs = parse_questions(f"```json\n{STD}\n```")
    assert len(qs) == 1 and qs[0].answer == "B"


def test_json_with_chatter():
    qs = parse_questions(f"好的，以下是结果：{STD} 希望有帮助")
    assert len(qs) == 1 and qs[0].answer == "B"


def test_json_empty_questions():
    assert parse_questions('{"questions":[],"note":"未识别到题目"}') == []


def test_confidence_clamp():
    def conf(v):
        return parse_questions(json.dumps({"questions": [{"index": 1, "answer": "A", "confidence": v}]}))[0].confidence
    assert conf(1.5) == 1.0
    assert conf(-0.2) == 0.0
    assert conf("92%") == 0.92
    assert conf("abc") is None


def test_delimiter_fullwidth_colon():
    text = "===第1题===\n题型：单选\n答案：B\n置信度：0.9\n理由：xxx"
    qs = parse_questions(text)
    assert len(qs) == 1
    assert qs[0].topic == "单选" and qs[0].answer == "B"
    assert qs[0].confidence == 0.9 and qs[0].reasoning == "xxx"


def test_delimiter_markdown_bold():
    text = "===第1题===\n**答案**: B"
    qs = parse_questions(text)
    assert qs[0].answer == "B"


def test_multiline_reason():
    text = "===第1题===\n答案: B\n理由: 第一行\n第二行\n第三行"
    qs = parse_questions(text)
    assert qs[0].reasoning == "第一行\n第二行\n第三行"


def test_markdown_heading_delimiter():
    text = "## 第1题\n答案: A\n## 第2题\n答案: C"
    qs = parse_questions(text)
    assert len(qs) == 2 and qs[0].answer == "A" and qs[1].answer == "C"


def test_bare_line_delimiter():
    text = "第1题：\n答案: A\n第2题：\n答案: C"
    qs = parse_questions(text)
    assert len(qs) == 2 and qs[1].answer == "C"


def test_delimiter_percent_confidence():
    text = "===第1题===\n答案: B\n置信度: 92%"
    assert parse_questions(text)[0].confidence == 0.92


def test_fallback():
    text = "这看起来是一道数学题…"
    qs = parse_questions(text)
    assert len(qs) == 1 and qs[0].answer == text


def test_empty_input():
    assert parse_questions("") == []
    assert parse_questions("   \n\t ") == []


def test_old_probe_cases():
    text = ("===第1题===\n题型: 单选\n答案: B\n置信度: 0.92\n理由: 选项 B 符合题干描述。\n\n"
            "===第2题===\n题型: 多选\n答案: A, C, D\n置信度: 0.55\n理由: A/C/D 正确，B 错误。")
    qs = parse_questions(text)
    assert len(qs) == 2
    assert qs[0].index == 1 and qs[0].topic == "单选" and qs[0].answer == "B" and qs[0].confidence == 0.92
    assert qs[1].index == 2 and qs[1].topic == "多选" and qs[1].answer == "A, C, D" and qs[1].confidence == 0.55
    qs2 = parse_questions("答案: X")
    assert len(qs2) == 1 and qs2[0].answer == "答案: X"


def test_answers_digest():
    qs = [Question(1, answer="B"), Question(2, answer="ACD"), Question(3, answer="对")]
    assert answers_digest(qs) == "1.B  2.ACD  3.对"


def test_answers_digest_truncate():
    qs = [Question(1, answer="这是一段超过二十个字符的很长很长的简答题答案文本内容")]
    d = answers_digest(qs)
    assert d.endswith("…") and len(d) < 30