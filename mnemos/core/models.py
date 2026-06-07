"""
记忆单元数据模型

设计哲学: Memory Palimpsest（记忆重写本）
每个记忆单元保留完整修订历史，新认知叠加于旧认知之上，
查询时总能追溯"我们曾经相信什么"以及"现在相信什么"。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


# ── 记忆分层 ────────────────────────────────────────────────


class MemoryTier(StrEnum):
    """记忆三层次，从原始到凝练"""

    IMPRESSION = "impression"   # 原始印象：对话片段、事件记录
    PATTERN = "pattern"         # 识别模式：从印象中提炼的规律
    PRINCIPLE = "principle"     # 行动原则：可指导未来决策的结晶


class ConfidenceLevel(StrEnum):
    """信念置信度"""
    SPECULATIVE = "speculative"  # 推测，未经验证
    TENTATIVE = "tentative"      # 初步确认
    CONFIRMED = "confirmed"      # 多方印证
    BEDROCK = "bedrock"          # 不可撼动的事实


class ScopeType(StrEnum):
    """记忆归属范围"""
    UNIVERSE = "universe"    # 全局：所有Agent可见
    TENANT = "tenant"        # 租户级：同一用户的所有Agent
    PERSONA = "persona"      # 角色级：单个Agent专属
    SESSION = "session"      # 会话级：单次对话


class MemoryType(StrEnum):
    """记忆类型 — 对标 Mem0 的 7 种时序分类"""
    EVENT = "event"              # 一次性事件: "去了日本"
    STATE = "state"              # 持续状态: "住在上海" (可被新状态覆盖)
    PLAN = "plan"                # 未来计划: "下周开会"
    PREFERENCE = "preference"    # 偏好: "喜欢黑暗模式"
    RELATIONSHIP = "relationship"  # 关系: "是张三的同事"
    ABSENCE = "absence"          # 缺失/否定: "没有驾照"
    TIMELESS = "timeless"        # 永恒事实: "Python 是编程语言"


class TemporalQueryMode(StrEnum):
    """查询的时序意图"""
    CURRENT_STATE = "current_state"        # "现在住在哪"
    HISTORICAL_RANGE = "historical_range"  # "去年发生了什么"
    UPCOMING = "upcoming"                  # "这周有什么计划"
    DURATION = "duration"                  # "这份工作做了多久"
    SPECIFIC_DATE = "specific_date"        # "3月15日做了什么"
    ANY = "any"                            # 无时序偏好


# ── 实体模型 ────────────────────────────────────────────────


class EntityRef(BaseModel):
    """记忆中涉及的实体引用"""

    entity_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    label: str                                    # 显示名称
    entity_type: str = "concept"                  # person, organization, concept, event, artifact
    aliases: list[str] = Field(default_factory=list)
    description: str = ""


class TemporalAnchor(BaseModel):
    """时间锚点 — 让记忆可沿时间轴定位"""

    anchor_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    event_at: datetime | None = None              # 事件发生时间
    recorded_at: datetime = Field(                # 记录时间
        default_factory=lambda: datetime.now(timezone.utc)
    )
    relative_expression: str | None = None        # 相对时间表达 "三天前" "上周五聚议时"
    precision: str = "day"                        # year, month, day, hour, minute


class BeliefRecord(BaseModel):
    """单条信念记录 — 可被修订"""

    belief_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    content: str                                  # 信念内容
    confidence: ConfidenceLevel = ConfidenceLevel.SPECULATIVE
    source: str | None = None                     # 来源（对话ID / Agent名 / 文档名）
    adopted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    superseded_by: str | None = None              # 被哪个新信念取代
    superseded_at: datetime | None = None         # 取代时间


# ── 核心记忆单元 ───────────────────────────────────────────


class MemoryEntry(BaseModel):
    """记忆世界中的最小可检索单元"""

    entry_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    tier: MemoryTier = MemoryTier.IMPRESSION

    # 内容
    title: str = ""                               # 简短摘要（用于列表展示）
    content: str                                  # 完整记忆内容

    # 时空定位
    anchors: list[TemporalAnchor] = Field(default_factory=list)
    entities: list[EntityRef] = Field(default_factory=list)

    # 归属
    scope: ScopeType = ScopeType.TENANT
    scope_id: str = ""                            # 范围标识（用户ID/Agent ID/Session ID）

    # 信念追踪
    beliefs: list[BeliefRecord] = Field(default_factory=list)

    # 关联
    parent_id: str | None = None                  # 衍生自哪条记忆
    related_ids: list[str] = Field(default_factory=list)  # 相关记忆
    tags: list[str] = Field(default_factory=list)

    # 生命周期
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_accessed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    access_count: int = 0
    decay_factor: float = 1.0                     # 衰减因子 0-1，0=遗忘

    # 时序元数据（2026-06 新增，对标 Mem0 Temporal Reasoning）
    memory_type: MemoryType = MemoryType.TIMELESS
    state_key: str = ""                           # 状态标识符（同key的记忆自动互斥覆盖）
    event_start: datetime | None = None           # 事件/状态开始时间
    event_end: datetime | None = None             # 事件/状态结束时间（None=持续中）
    is_active: bool = True                        # 是否仍生效
    temporal_precision: str = "day"               # year/month/day/hour/minute

    # 向量（外部管理）
    embedding_model: str = ""                     # 使用的嵌入模型名
    embedding: list[float] | None = None          # 向量值（查询时不返回）

    @model_validator(mode="after")
    def _ensure_scope_id(self) -> Self:
        if not self.scope_id and self.scope != ScopeType.UNIVERSE:
            self.scope_id = "default"
        return self

    def touch(self) -> None:
        """标记为被访问，刷新衰减"""
        self.last_accessed_at = datetime.now(timezone.utc)
        self.access_count += 1
        self.decay_factor = min(1.0, self.decay_factor + 0.05)

    def revise_belief(
        self, old_belief_id: str, new_content: str, source: str = ""
    ) -> BeliefRecord:
        """修订一条信念：旧信念标记为被取代，追加新信念"""
        now = datetime.now(timezone.utc)
        for b in self.beliefs:
            if b.belief_id == old_belief_id:
                b.superseded_by = f"{old_belief_id}_rev{len(self.beliefs)}"
                b.superseded_at = now

        new_belief = BeliefRecord(
            content=new_content,
            confidence=ConfidenceLevel.TENTATIVE,
            source=source,
            adopted_at=now,
        )
        self.beliefs.append(new_belief)
        return new_belief

    def current_beliefs(self) -> list[BeliefRecord]:
        """返回当前有效（未被取代）的信念"""
        return [b for b in self.beliefs if b.superseded_by is None]


class ContextScope(BaseModel):
    """定义一段记忆的访问边界"""

    scope_type: ScopeType
    scope_id: str
    label: str = ""                               # 可读名称
    parent_scope: str | None = None               # 上级范围ID（如 session→persona→tenant）

    def matches(self, other: ContextScope) -> bool:
        """判断两个范围是否有交集"""
        if self.scope_type == ScopeType.UNIVERSE:
            return True
        if self.scope_type == other.scope_type and self.scope_id == other.scope_id:
            return True
        return False


# ── 查询模型 ────────────────────────────────────────────────


class MemoryQuery(BaseModel):
    """记忆检索查询"""

    query_text: str = ""                          # 语义搜索文本
    keywords: list[str] = Field(default_factory=list)  # 关键词过滤
    tiers: list[MemoryTier] = Field(default_factory=list)  # 限定层次
    scopes: list[ContextScope] = Field(default_factory=list)  # 限定范围
    entities: list[str] = Field(default_factory=list)  # 限定实体
    tags: list[str] = Field(default_factory=list)

    # 时序过滤
    after: datetime | None = None
    before: datetime | None = None
    around: str | None = None                     # 相对时间表达 "上周二"

    # 检索策略
    max_results: int = 20
    include_embedding: bool = False
    include_superseded: bool = False              # 是否包含被取代的信念

    # 检索信号权重
    semantic_weight: float = 0.35
    keyword_weight: float = 0.25
    entity_weight: float = 0.20
    temporal_weight: float = 0.10
    access_weight: float = 0.10                   # 访问频次加成


class SearchResult(BaseModel):
    """单条检索结果"""

    entry: MemoryEntry
    resonance_score: float                        # 综合共振得分 0-1
    signal_breakdown: dict[str, float] = Field(  # 各信号得分明细
        default_factory=dict
    )


class MemoryExtractionResult(BaseModel):
    """从一段文本中提取出的记忆"""

    impressions: list[MemoryEntry] = Field(default_factory=list)
    patterns_updated: list[str] = Field(default_factory=list)   # 被更新的模式ID
    entities_extracted: list[EntityRef] = Field(default_factory=list)
