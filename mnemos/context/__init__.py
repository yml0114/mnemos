# -*- coding: utf-8 -*-
"""
Context Management — 基于 OpenCode 模型的上下文系统

提供：
- 结构化 Context Source 注册与发现
- 自动变更检测与 Mid‑Conversation 消息生成
- Context Epoch 生命周期管理
- Checkpoint / Restore 会话恢复
"""

from .types import (
    ContextEpoch,
    ContextSnapshot,
    ContextSource,
    MidConversationSystemMessage,
    RegisteredSource,
)
from .registry import ContextRegistry
from .system import SystemContextImpl

__all__ = [
    "ContextSource",
    "ContextSnapshot",
    "ContextEpoch",
    "MidConversationSystemMessage",
    "RegisteredSource",
    "ContextRegistry",
    "SystemContextImpl",
]
