"""
多信号检索引擎 — Resonance（共振）

设计理念:
  单一语义检索像"模糊记忆"，多信号共振才接近人类回忆方式——
  语义相似 + 关键词命中 + 实体关联 + 时间锚定 + 访问频率，
  五路信号加权融合，每条记忆得到一个"共振得分"。

查询流程:
  1. 信号分解: 将查询拆解为语义、关键词、实体、时序、热度五路
  2. 并行召回: 各信号独立在对应索引中检索
  3. 融合排序: 加权融合 → 去重 → 按共振得分排序
  4. 上下文填充: 关联记忆链扩展（BFS 1-2跳）
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from mnemos.core.models import (
    MemoryEntry,
    MemoryQuery,
    MemoryTier,
    SearchResult,
    ScopeType,
)
from mnemos.storage.palimpsest import PalimpsestStore


# ── 信号提取器 ──────────────────────────────────────────


_ENTITY_PATTERN = re.compile(
    r'(?:公司|产品|项目|框架|工具|语言|协议|人物|组织|事件)[：:]?\s*([^\s，。,\.]{2,30})'
)
_KEYWORD_PATTERN = re.compile(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}')
_TIME_HINTS = {
    "今天": 0, "昨天": -1, "前天": -2,
    "本周": "this_week", "上周": "last_week",
    "本月": "this_month", "上月": "last_month",
    "刚才": 0, "刚刚": 0, "最近": "recent",
    "之前": "before", "以前": "before",
}


def _extract_query_entities(text: str) -> list[str]:
    """从查询文本中提取可能的实体提及"""
    entities = []
    for m in _ENTITY_PATTERN.finditer(text):
        name = m.group(1).strip()
        if len(name) >= 2:
            entities.append(name)
    return entities


def _extract_keywords(text: str) -> list[str]:
    """提取关键词（中文词 + 英文词）"""
    return [m.group() for m in _KEYWORD_PATTERN.finditer(text)]


def _parse_time_hint(text: str) -> tuple[datetime | None, datetime | None]:
    """从文本中解析时间提示"""
    now = datetime.now(timezone.utc)
    after: datetime | None = None
    before: datetime | None = None

    for hint, offset in _TIME_HINTS.items():
        if hint in text:
            if isinstance(offset, int):
                target = now.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) + timedelta(days=offset)
                after = target
                before = target + timedelta(days=1)
            elif offset == "this_week":
                after = now - timedelta(days=now.weekday())
                after = after.replace(hour=0, minute=0, second=0, microsecond=0)
            elif offset == "last_week":
                after = now - timedelta(days=now.weekday() + 7)
                after = after.replace(hour=0, minute=0, second=0, microsecond=0)
                before = after + timedelta(days=7)
            break

    return after, before


# ── 检索引擎 ─────────────────────────────────────────────


class ResonanceEngine:
    """
    共振检索引擎。

    使用示例:
        engine = ResonanceEngine(store)
        results = engine.search(MemoryQuery(query_text="小米股价"))
    """

    def __init__(self, store: PalimpsestStore):
        self._store = store

    def search(self, query: MemoryQuery) -> list[SearchResult]:
        """执行多信号融合检索"""
        # 1. 信号分解
        entities = query.entities or _extract_query_entities(query.query_text)
        keywords = query.keywords or _extract_keywords(query.query_text)
        after, before = _parse_time_hint(query.query_text)

        # 用户指定优先
        if query.after:
            after = query.after
        if query.before:
            before = query.before

        # 2. 并行召回各信号
        candidates: dict[str, dict[str, float]] = {}  # entry_id → {signal: score}

        # 语义信号（通过 FTS5 近似，实际部署时替换为向量检索）
        if query.query_text:
            semantic_hits = self._store.fts(query.query_text, limit=50)
            for i, entry in enumerate(semantic_hits):
                score = 1.0 - (i / max(len(semantic_hits), 1)) * 0.5
                self._add_signal(candidates, entry.entry_id, "semantic", score)

        # 关键词信号
        if keywords:
            for kw in keywords:
                kw_hits = self._store.fts(kw, limit=20)
                for i, entry in enumerate(kw_hits):
                    score = 0.8 - (i / max(len(kw_hits), 1)) * 0.3
                    # 精准匹配加成
                    if kw.lower() in entry.content.lower():
                        score += 0.2
                    self._add_signal(candidates, entry.entry_id, "keyword", score)

        # 实体信号
        if entities:
            for entity in entities:
                entity_hits = self._store.by_entity(entity, limit=20)
                for i, entry in enumerate(entity_hits):
                    score = 0.9 - (i / max(len(entity_hits), 1)) * 0.4
                    self._add_signal(candidates, entry.entry_id, "entity", score)

        # 时序信号
        if after or before:
            time_hits = self._store.by_time(
                after=after, before=before, limit=100
            )
            for entry in time_hits:
                # 越接近时间窗口中心，得分越高
                if after and before:
                    mid = after + (before - after) / 2
                    delta = abs((entry.created_at - mid).total_seconds())
                    window = (before - after).total_seconds()
                    score = max(0, 1.0 - delta / window) if window > 0 else 0.5
                else:
                    score = 0.6
                self._add_signal(candidates, entry.entry_id, "temporal", score)

        # 范围过滤
        if query.scopes:
            for scope in query.scopes:
                scope_hits = self._store.by_scope(
                    scope.scope_type, scope.scope_id, limit=100
                )
                for entry in scope_hits:
                    self._add_signal(candidates, entry.entry_id, "scope_boost", 0.3)

        # 3. 融合排序
        results: list[SearchResult] = []
        for entry_id, signals in candidates.items():
            entry = self._store.by_id(entry_id)
            if entry is None:
                continue

            # 层次过滤
            if query.tiers and entry.tier not in query.tiers:
                continue

            # 计算加权共振得分
            resonance = self._compute_resonance(signals, query)

            # 访问热度加成
            access_bonus = min(0.15, entry.access_count * 0.01)
            resonance += access_bonus * query.access_weight

            # 信念置信度加成
            current_beliefs = entry.current_beliefs()
            if current_beliefs:
                best_confidence = max(
                    {"speculative": 0.1, "tentative": 0.3,
                     "confirmed": 0.5, "bedrock": 0.7}.get(
                        b.confidence.value, 0.1
                    )
                    for b in current_beliefs
                )
                resonance += best_confidence * 0.1

            results.append(SearchResult(
                entry=entry,
                resonance_score=min(1.0, resonance),
                signal_breakdown={
                    k: round(v, 3) for k, v in signals.items()
                },
            ))

        # 去重排序
        results.sort(key=lambda r: r.resonance_score, reverse=True)
        results = results[:query.max_results]

        # 4. 上下文扩展：高得分结果的相关记忆
        if results and results[0].resonance_score > 0.4:
            expanded = self._expand_context(results, max_depth=1)
            return expanded[:query.max_results]

        return results

    def _add_signal(
        self, candidates: dict[str, dict[str, float]],
        entry_id: str, signal_name: str, score: float
    ) -> None:
        """累加信号得分"""
        if entry_id not in candidates:
            candidates[entry_id] = {}
        current = candidates[entry_id].get(signal_name, 0.0)
        candidates[entry_id][signal_name] = max(current, score)

    def _compute_resonance(
        self, signals: dict[str, float], query: MemoryQuery
    ) -> float:
        """计算加权共振得分"""
        weights = {
            "semantic": query.semantic_weight,
            "keyword": query.keyword_weight,
            "entity": query.entity_weight,
            "temporal": query.temporal_weight,
        }
        total = 0.0
        total_weight = 0.0
        for signal, score in signals.items():
            w = weights.get(signal, 0.05)
            total += score * w
            total_weight += w

        # 归一化
        if total_weight > 0:
            total /= total_weight

        # 多信号加成：命中的信号越多，额外加分
        signal_count = len(signals)
        if signal_count >= 3:
            total *= 1.2
        elif signal_count >= 2:
            total *= 1.1

        return min(1.0, total)

    def _expand_context(
        self, results: list[SearchResult], max_depth: int = 1
    ) -> list[SearchResult]:
        """扩展上下文：高得分结果的关联记忆"""
        seen_ids = {r.entry.entry_id for r in results}
        expanded = list(results)

        for result in results[:5]:  # 只扩展 top-5
            if result.resonance_score < 0.3:
                continue
            related = self._store.traverse(
                result.entry.entry_id, depth=max_depth
            )
            for entry in related:
                if entry.entry_id not in seen_ids:
                    seen_ids.add(entry.entry_id)
                    expanded.append(SearchResult(
                        entry=entry,
                        resonance_score=result.resonance_score * 0.5,
                        signal_breakdown={"context_expansion": 0.5},
                    ))

        expanded.sort(key=lambda r: r.resonance_score, reverse=True)
        return expanded
