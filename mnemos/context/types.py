# -*- coding: utf-8 -*-
"""
Context Management 核心类型定义 — 基于 OpenCode 架构设计
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol
from uuid import UUID

# ── Context Source 接口 ───────────────────────────────────────

class ContextSource(Protocol):
    """上下文源协议：提供可观察、可渲染的结构化值"""

    @property
    def key(self) -> str:
        """唯一标识符，形如 'namespace:name'"""
        ...

    def loader(self) -> dict[str, Any]:
        """加载当前值"""
        ...

    def renderer(self, value: dict[str, Any]) -> str:
        """将值渲染为文本片段，用于注入 system prompt"""
        ...

    def codec(self) -> str:
        """值的编解码器名称，用于快照存储"""
        return "json"


# ── 系统上下文快照 ────────────────────────────────────────────

@dataclass
class ContextSnapshot:
    """单个 Context Source 的快照，用于 diff 检测"""

    source_key: str
    value_hash: str          # 值的哈希 (如 SHA256)
    rendered: str            # 上次渲染的文本
    admitted_at: datetime    # 上次被 admit 到 system context 的时间
    version: int = 1

    def diff(self, other: ContextSnapshot) -> bool:
        """返回 True 表示与另一个快照有实质变化"""
        return self.value_hash != other.value_hash


# ── 上下文纪元 ────────────────────────────────────────────────

@dataclass
class ContextEpoch:
    """一个 context epoch：基线不变的时间段"""

    epoch_id: UUID
    started_at: datetime
    baseline_snapshot: dict[str, ContextSnapshot]
    mid_conversation_messages: list[str] = field(default_factory=list)

    def baseline_rendered(self) -> str:
        """渲染完整的基线系统上下文（所有源）"""
        parts = [f"Baseline Context (Epoch {self.epoch_id.hex[:8]}):"]
        for key, snap in sorted(self.baseline_snapshot.items()):
            parts.append(f"\n[{key}]\n{snap.rendered}")
        return "\n".join(parts)


# ── Mid‑Conversation 系统消息 ───────────────────────────────────

@dataclass
class MidConversationSystemMessage:
    """在安全 provider‑turn 边界注入的系统消息，携带上下文变更信息"""

    source_key: str
    change_type: str        # created/updated/deprecated
    new_value_summary: str  # 变化摘要（通常比较短）
    rendered: str           # 完整的渲染文本（可选）
    timestamp: datetime

    def to_system_prompt(self) -> str:
        """格式化为可直接插入系统提示的消息"""
        return (
            f"[Context Update - {self.source_key}]\n"
            f"Change: {self.change_type}\n"
            f"Summary: {self.new_value_summary}\n"
            f"Details:\n{self.rendered}"
        )


# ── 注册表项 ───────────────────────────────────────────────────

@dataclass
class RegisteredSource:
    """注册表中的条目"""

    source_factory: Callable[[], ContextSource]
    scope_type: str | None = None
    scope_id: str = ""
    priority: int = 0
    description: str = ""

    def create(self) -> ContextSource:
        return self.source_factory()
