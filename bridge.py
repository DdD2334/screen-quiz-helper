# -*- coding: utf-8 -*-
"""bridge.py — QObject 信号桥：工作线程与 Qt 主线程之间唯一的通信通道。

线程铁律（OPTIMIZATION_PLAN §3.2）：
- Bridge 实例必须在主线程创建。
- 工作线程只允许 emit 信号；任何 Qt 控件方法只能在主线程槽函数里调用。
- connect 用默认 AutoConnection，自动排队到主线程。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    questions_ready = Signal(object)   # 载荷 list[Question]，用 object 避免 Qt 类型注册问题
    partial_text = Signal(str)         # 流式原始文本增量
    status = Signal(str, str)          # (消息文本, 级别 info/busy/warn/error/ok)
    error = Signal(str)                # 人话错误信息
    request_region = Signal()          # 请求主线程弹框选 overlay
    capture_flash = Signal()           # 截屏瞬间闪边框
    copy_answers = Signal()            # 全局热键：复制速览串（T18）
    toggle_panel = Signal()            # 全局热键：显示/隐藏悬浮窗（T18）
    explanation_ready = Signal(object)  # 载荷 (index, 讲解文本)（T25）