"""
时序推理引擎 — Chronos

对标 Mem0 Temporal Reasoning (2026-05):
- 每条记忆自动打时间标签（7种类型）
- 查询时按时间意图重新排序
- 状态记忆自动互斥覆盖（state_key）
- 零 LLM 调用（规则 + 启发式）

设计决策: 不依赖 LLM 做时序分类，用纯规则引擎实现，
          保持 Mnemos 的"零外部依赖"原则。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from mnemos.core.models import (
    MemoryEntry,
    MemoryQuery as MemoryQuery,
    MemoryType,
    SearchResult,
    TemporalQueryMode,
)


# ── 时序意图检测（正则 + 关键词，零 LLM） ──────────────


_CURRENT_PATTERNS = [
    re.compile(r'(现在|目前|当前|如今).*(住|在|工作|做|是|用|喜欢|吃)'),
    re.compile(r'where\s+(do|does).*(live|work|stay|now)'),
    re.compile(r'(现在|目前|当前).*(什么|哪|谁|怎么)'),
]

_HISTORICAL_PATTERNS = [
    re.compile(r'(去年|前年|以前|之前|过去|曾经|当时|那时候)'),
    re.compile(r'(上[个周月]|昨天|前天|上周|上月|去年)'),
    re.compile(r'(what|where).*(happen|did|was|were).*(last|ago|before|previous)'),
]

_UPCOMING_PATTERNS = [
    re.compile(r'(计划|打算|将要|即将|准备|下周|下个|明天|后天|明年)'),
    re.compile(r'(这[周月年]|今[天晚]|明天).*(做什么|计划|安排)'),
    re.compile(r'what.*(plan|next|upcoming|this week)'),
]

_DURATION_PATTERNS = [
    re.compile(r'(多久|多长时间|几年|几个月|几天)'),
    re.compile(r'how\s+long'),
]

_SPECIFIC_DATE_PATTERNS = [
    re.compile(r'\d{1,2}月\d{1,2}[日号]'),
    re.compile(r'\d{4}[年/-]\d{1,2}[月/-]\d{1,2}'),
    re.compile(r'(星期[一二三四五六日]|周[一二三四五六日])'),
]


def detect_temporal_intent(query: str) -> TemporalQueryMode:
    """零 LLM 时序意图检测"""
    q = query.lower()

    if any(p.search(q) or p.search(query) for p in _CURRENT_PATTERNS):
        return TemporalQueryMode.CURRENT_STATE
    if any(p.search(q) or p.search(query) for p in _HISTORICAL_PATTERNS):
        return TemporalQueryMode.HISTORICAL_RANGE
    if any(p.search(q) or p.search(query) for p in _UPCOMING_PATTERNS):
        return TemporalQueryMode.UPCOMING
    if any(p.search(q) or p.search(query) for p in _DURATION_PATTERNS):
        return TemporalQueryMode.DURATION
    if any(p.search(q) or p.search(query) for p in _SPECIFIC_DATE_PATTERNS):
        return TemporalQueryMode.SPECIFIC_DATE

    return TemporalQueryMode.ANY


# ── 记忆类型推断（启发式） ──────────────────────────────


_STATE_PATTERNS = [
    re.compile(r'(住|在|工作|担任|任职|就职|供职)'),
    re.compile(r'(live|work|stay|reside|employ)'),
]

_PLAN_PATTERNS = [
    re.compile(r'(计划|打算|将要|准备|预计|安排|预约)'),
    re.compile(r'(plan|will|going|schedule|appointment)'),
]

_PREFERENCE_PATTERNS = [
    re.compile(r'(喜欢|偏好|讨厌|习惯|爱|不喜欢|常用|擅长)'),
    re.compile(r'(prefer|like|love|hate|favorite|usually|always)'),
]

_RELATIONSHIP_PATTERNS = [
    re.compile(r'(是.*的.*|认识|朋友|同事|家人|同学|老板|上司)'),
    re.compile(r'(is\s+(my|a|the).*|knows|friend|colleague)'),
]

_ABSENCE_PATTERNS = [
    re.compile(r'(没有|不会|不能|不可以|无法|禁止)'),
    re.compile(r'(doesn\'t|can\'t|cannot|never|no\s+\w+)'),
]


def infer_memory_type(content: str) -> MemoryType:
    """启发式推断记忆类型"""
    c = content.lower()

    if any(p.search(c) or p.search(content) for p in _ABSENCE_PATTERNS):
        return MemoryType.ABSENCE
    if any(p.search(c) or p.search(content) for p in _PLAN_PATTERNS):
        return MemoryType.PLAN
    if any(p.search(c) or p.search(content) for p in _PREFERENCE_PATTERNS):
        return MemoryType.PREFERENCE
    if any(p.search(c) or p.search(content) for p in _RELATIONSHIP_PATTERNS):
        return MemoryType.RELATIONSHIP
    if any(p.search(c) or p.search(content) for p in _STATE_PATTERNS):
        return MemoryType.STATE

    # 默认：事件
    return MemoryType.EVENT


def generate_state_key(entry: MemoryEntry) -> str:
    """为 STATE 类型记忆生成状态标识符（提取谓语而非具体值）"""
    if entry.memory_type != MemoryType.STATE:
        return ""

    content = entry.content

    # 提取核心谓语作为状态维度
    # "住在上海" → "住", "工作在字节" → "工作"
    state_predicates = ["住", "工作", "担任", "任职", "就职", "供职", "在"]
    for pred in state_predicates:
        if pred in content:
            return f"{entry.scope_id}:state:{pred}"

    # Fallback
    key = content[:6].replace(" ", "")
    return f"{entry.scope_id}:state:{key[:20]}"


# ── 时序重排序 ──────────────────────────────────────


class Chronos:
    """
    时序推理引擎。

    使用示例:
        chronos = Chronos()
        intent = chronos.detect_intent("他现在住哪里")
        reranked = chronos.rerank(results, intent)
    """

    # 时间衰减参数
    DECAY_HALF_LIFE_DAYS = 30  # 30天后共振权重减半

    def detect_intent(self, query: str) -> TemporalQueryMode:
        return detect_temporal_intent(query)

    def classify(self, entry: MemoryEntry) -> MemoryType:
        return infer_memory_type(entry.content)

    def annotate(self, entry: MemoryEntry) -> MemoryEntry:
        """
        自动标注一条记忆的时序元数据。
        调用时机: 每次 inscribe 之前。
        """
        entry.memory_type = self.classify(entry)
        entry.state_key = generate_state_key(entry)

        if entry.memory_type == MemoryType.STATE:
            entry.event_start = entry.event_start or entry.created_at
            entry.event_end = None  # STATE 默认持续中
            entry.is_active = True
        elif entry.memory_type == MemoryType.PLAN:
            entry.is_active = True
            entry.event_start = entry.event_start or entry.created_at
        elif entry.memory_type == MemoryType.EVENT:
            entry.event_start = entry.event_start or entry.created_at
            entry.event_end = entry.event_end or entry.created_at
            entry.is_active = False

        return entry

    def deactivate_states(self, existing: list[MemoryEntry], new_entry: MemoryEntry) -> list[str]:
        """
        当新 STATE 记忆写入时，自动关闭同 state_key 的旧状态。
        返回被关闭的记忆 ID 列表。
        """
        if new_entry.memory_type != MemoryType.STATE or not new_entry.state_key:
            return []

        deactivated = []
        for old in existing:
            if (old.state_key == new_entry.state_key
                    and old.is_active
                    and old.entry_id != new_entry.entry_id):
                old.is_active = False
                old.event_end = new_entry.created_at
                deactivated.append(old.entry_id)

        return deactivated

    def rerank(
        self,
        results: list[SearchResult],
        query: str,
        intent: TemporalQueryMode | None = None,
    ) -> list[SearchResult]:
        """
        按时序意图重新排序结果。

        策略:
        - CURRENT_STATE: 提升活跃 STATE，惩罚已关闭
        - HISTORICAL_RANGE: 提升过去事件，按时间排序
        - UPCOMING: 提升 PLAN 类型
        - DURATION: 提升 STATE（需要 start 和 end）
        - ANY: 不干预
        """
        if intent is None:
            intent = self.detect_intent(query)

        if intent == TemporalQueryMode.ANY:
            return results

        now = datetime.now(timezone.utc)

        for r in results:
            entry = r.entry
            bonus = 0.0

            if intent == TemporalQueryMode.CURRENT_STATE:
                if entry.memory_type == MemoryType.STATE and entry.is_active:
                    bonus = 0.25
                elif entry.memory_type == MemoryType.PREFERENCE:
                    bonus = 0.15
                elif not entry.is_active:
                    bonus = -0.20  # 惩罚已过期

            elif intent == TemporalQueryMode.HISTORICAL_RANGE:
                if entry.memory_type == MemoryType.EVENT:
                    bonus = 0.15
                if entry.event_start:
                    days_ago = (now - entry.event_start).days
                    bonus += 0.05 * min(days_ago / 30, 1.0)  # 越久远越加分

            elif intent == TemporalQueryMode.UPCOMING:
                if entry.memory_type == MemoryType.PLAN and entry.is_active:
                    bonus = 0.30
                if entry.event_start and entry.event_start > now:
                    # 越近的计划分越高
                    days_ahead = (entry.event_start - now).days
                    bonus += 0.10 * max(1.0 - days_ahead / 14, 0)

            elif intent == TemporalQueryMode.DURATION:
                if entry.memory_type == MemoryType.STATE:
                    if entry.event_start and entry.event_end:
                        duration_days = (entry.event_end - entry.event_start).days
                        bonus = 0.10 * min(duration_days / 365, 1.0)
                    elif entry.event_start:
                        duration_days = (now - entry.event_start).days
                        bonus = 0.10 * min(duration_days / 365, 1.0)

            elif intent == TemporalQueryMode.SPECIFIC_DATE:
                if entry.event_start:
                    bonus = 0.10  # 有明确时间戳的记忆

            # 时间衰减
            if entry.event_start:
                days_ago = (now - entry.event_start).days
                if days_ago > 0:
                    decay = 0.5 ** (days_ago / self.DECAY_HALF_LIFE_DAYS)
                    bonus *= decay

            r.resonance_score = min(1.0, r.resonance_score + bonus)

        # 按调整后的得分重新排序
        results.sort(key=lambda r: r.resonance_score, reverse=True)
        return results

    def resolve_state_chain(
        self, entries: list[MemoryEntry], state_key: str
    ) -> list[dict[str, Any]]:
        """
        解析一个状态 key 的完整演化链。
        返回从旧到新的时间线。
        """
        chain = [
            {
                "entry_id": e.entry_id,
                "content": e.content,
                "start": e.event_start.isoformat() if e.event_start else None,
                "end": e.event_end.isoformat() if e.event_end else None,
                "is_active": e.is_active,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
            if e.state_key == state_key
        ]
        chain.sort(key=lambda x: x["created_at"])
        return chain

    def stats(self, entries: list[MemoryEntry]) -> dict[str, int]:
        """时序统计"""
        types = {}
        for e in entries:
            types[e.memory_type.value] = types.get(e.memory_type.value, 0) + 1
        return {
            "total": len(entries),
            "active_states": sum(1 for e in entries if e.is_active and e.memory_type == MemoryType.STATE),
            "upcoming_plans": sum(1 for e in entries if e.is_active and e.memory_type == MemoryType.PLAN),
            **types,
        }
