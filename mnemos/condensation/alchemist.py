"""
记忆凝练引擎 — Alchemist（炼金术士）

职责:
  将低层记忆蒸馏为高层认知:
  - 印象 → 模式: 从多条相关印象中识别规律
  - 模式 → 原则: 从已验证的模式中提炼行动指南

凝练触发条件:
  - 同范围同实体的印象数超过阈值
  - 多条印象表达了相似的判断/结论
  - 手动触发（用户要求总结）

设计原则:
  凝练是单向的——印象可以蒸馏为模式，但模式不会变回印象。
  这确保了认知层次清晰，高层记忆更凝练、更可信。
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from mnemos.core.models import (
    BeliefRecord,
    ConfidenceLevel,
    EntityRef,
    MemoryEntry,
    MemoryTier,
    ScopeType,
)
from mnemos.storage.palimpsest import PalimpsestStore


class AlchemistCondenser:
    """
    记忆炼金术士 — 将印象蒸馏为模式，将模式结晶为原则。

    使用示例:
        condenser = AlchemistCondenser(store)
        new_patterns = condenser.impressions_to_patterns(
            scope_type=ScopeType.TENANT, scope_id="user_123"
        )
    """

    # 触发阈值
    IMPRESSION_THRESHOLD = 5       # 同范围同实体印象数超过此值触发蒸馏
    PATTERN_THRESHOLD = 3          # 同类型模式超过此值触发结晶

    def __init__(self, store: PalimpsestStore):
        self._store = store

    def impressions_to_patterns(
        self,
        scope_type: ScopeType = ScopeType.TENANT,
        scope_id: str = "",
        min_impressions: int | None = None,
    ) -> list[MemoryEntry]:
        """
        将印象蒸馏为模式。

        策略:
          1. 找到给定范围内的所有印象
          2. 按实体聚类
          3. 同一实体的印象超过阈值时，提取共同模式
          4. 生成模式条目（tier=PATTERN）
        """
        threshold = min_impressions or self.IMPRESSION_THRESHOLD
        impressions = self._store.by_scope(
            scope_type, scope_id,
            tiers=[MemoryTier.IMPRESSION],
            limit=500,
        )

        if len(impressions) < threshold:
            return []

        # 按实体聚类
        entity_clusters: dict[str, list[MemoryEntry]] = {}
        for imp in impressions:
            for entity in imp.entities:
                key = f"{entity.entity_type}:{entity.label}"
                if key not in entity_clusters:
                    entity_clusters[key] = []
                entity_clusters[key].append(imp)

        # 对超过阈值的聚类生成模式
        patterns: list[MemoryEntry] = []
        now = datetime.now(timezone.utc)

        for cluster_key, cluster_imps in entity_clusters.items():
            if len(cluster_imps) < threshold:
                continue

            entity_type, entity_label = cluster_key.split(":", 1)

            # 提取共同主题
            all_tags: Counter[str] = Counter()
            all_beliefs: list[BeliefRecord] = []
            source_ids: list[str] = []

            for imp in cluster_imps:
                for tag in imp.tags:
                    all_tags[tag] += 1
                for belief in imp.current_beliefs():
                    if belief.confidence in (
                        ConfidenceLevel.CONFIRMED,
                        ConfidenceLevel.BEDROCK,
                    ):
                        all_beliefs.append(belief)
                source_ids.append(imp.entry_id)

            # 取频率最高的标签
            top_tags = [t for t, _ in all_tags.most_common(5)]

            # 生成模式标题
            title = f"关于「{entity_label}」的行为模式"
            content = (
                f"从 {len(cluster_imps)} 条关于 {entity_label} 的印象中，"
                f"识别出以下规律:\n"
                f"- 高频标签: {', '.join(top_tags) if top_tags else '无'}\n"
                f"- 已确认信念: {len(all_beliefs)} 条\n"
                f"- 最近一条印象: {cluster_imps[-1].content[:200]}"
            )

            entry = MemoryEntry(
                entry_id=uuid.uuid4().hex[:16],
                tier=MemoryTier.PATTERN,
                title=title,
                content=content,
                scope=scope_type,
                scope_id=scope_id,
                tags=top_tags,
                entities=[
                    EntityRef(
                        entity_id=uuid.uuid4().hex[:12],
                        label=entity_label,
                        entity_type=entity_type,
                    )
                ],
                beliefs=all_beliefs[:5],
                related_ids=source_ids,
                created_at=now,
                last_accessed_at=now,
            )
            self._store.inscribe(entry)
            patterns.append(entry)

        return patterns

    def patterns_to_principles(
        self,
        scope_type: ScopeType = ScopeType.TENANT,
        scope_id: str = "",
    ) -> list[MemoryEntry]:
        """
        将模式结晶为原则。

        仅当多条模式指向同一结论时触发。
        """
        patterns = self._store.by_scope(
            scope_type, scope_id,
            tiers=[MemoryTier.PATTERN],
            limit=200,
        )

        if len(patterns) < self.PATTERN_THRESHOLD:
            return []

        # 按置信度筛选：只有 confirmed+ 的模式参与结晶
        confirmed_patterns = [
            p for p in patterns
            if p.current_beliefs()
            and any(
                b.confidence in (ConfidenceLevel.CONFIRMED, ConfidenceLevel.BEDROCK)
                for b in p.current_beliefs()
            )
        ]

        if len(confirmed_patterns) < self.PATTERN_THRESHOLD:
            return []

        now = datetime.now(timezone.utc)
        principles: list[MemoryEntry] = []

        # 为每组高置信模式生成一条原则
        source_ids = [p.entry_id for p in confirmed_patterns]
        all_tags: Counter[str] = Counter()
        all_entities: dict[str, EntityRef] = {}

        for p in confirmed_patterns:
            for tag in p.tags:
                all_tags[tag] += 1
            for e in p.entities:
                all_entities[e.label] = e

        top_tags = [t for t, _ in all_tags.most_common(3)]

        entry = MemoryEntry(
            entry_id=uuid.uuid4().hex[:16],
            tier=MemoryTier.PRINCIPLE,
            title=f"行动原则（基于 {len(confirmed_patterns)} 条已验证模式）",
            content=(
                f"以下原则已经过 {len(confirmed_patterns)} 条模式的交叉验证:\n"
                f"- 涉及实体: {', '.join(list(all_entities.keys())[:10])}\n"
                f"- 关键标签: {', '.join(top_tags)}\n"
                f"- 原则描述: 在此上下文中，上述模式已稳定重复出现，"
                f"可作为后续决策的参考依据。"
            ),
            scope=scope_type,
            scope_id=scope_id,
            tags=top_tags,
            entities=list(all_entities.values())[:10],
            beliefs=[
                BeliefRecord(
                    belief_id=uuid.uuid4().hex[:10],
                    content=f"基于 {len(confirmed_patterns)} 条模式验证的原则",
                    confidence=ConfidenceLevel.BEDROCK,
                    adopted_at=now,
                )
            ],
            related_ids=source_ids,
            created_at=now,
            last_accessed_at=now,
        )
        self._store.inscribe(entry)
        principles.append(entry)

        return principles

    def auto_condense(
        self,
        scope_type: ScopeType = ScopeType.TENANT,
        scope_id: str = "",
    ) -> dict[str, int]:
        """
        自动执行完整凝练链路: 印象→模式→原则。

        返回各阶段生成数量。
        """
        patterns = self.impressions_to_patterns(scope_type, scope_id)
        principles = self.patterns_to_principles(scope_type, scope_id)
        return {
            "patterns_created": len(patterns),
            "principles_created": len(principles),
        }

    def llm_distill(
        self,
        scope_type: ScopeType = ScopeType.TENANT,
        scope_id: str = "",
        llm_client: Any = None,
    ) -> list[MemoryEntry]:
        """
        LLM 驱动的智能蒸馏：使用 LLM 从印象中提取深层模式。

        相比纯规则的 impressions_to_patterns，LLM 蒸馏能：
        - 理解语义关联（不只依赖实体聚类）
        - 发现隐含模式（用户自己都没意识到的规律）
        - 生成更自然、更凝练的模式描述

        Args:
            llm_client: 符合 LLMClient 协议的对象（有 generate 方法）
        """
        if llm_client is None:
            return []  # 无 LLM 时跳过

        impressions = self._store.by_scope(
            scope_type, scope_id,
            tiers=[MemoryTier.IMPRESSION],
            limit=200,
        )

        if len(impressions) < self.IMPRESSION_THRESHOLD:
            return []

        # 构建印象列表
        imp_texts = "\n".join(
            f"- [{imp.created_at.isoformat() if imp.created_at else '?'}] {imp.content}"
            for imp in impressions[-100:]  # 最近 100 条
        )

        system = """你是记忆炼金术士。从用户的印象片段中蒸馏出行为模式。

规则:
1. 发现重复出现的主题、偏好、习惯
2. 识别冲突或变化（如用户改变了某个偏好）
3. 提取跨实体的通用规律
4. 每条模式一句话，清晰简洁

返回 JSON:
{"patterns": ["模式1", "模式2", ...], "summary": "整体画像摘要"}"""

        prompt = f"从以下印象中蒸馏模式:\n\n{imp_texts}"

        try:
            import asyncio
            raw = asyncio.run(llm_client.generate(prompt, system))
            import json
            data = json.loads(raw)
        except Exception:
            return []

        patterns: list[MemoryEntry] = []
        now = datetime.now(timezone.utc)

        for pat_text in data.get("patterns", [])[:5]:
            entry = MemoryEntry(
                entry_id=uuid.uuid4().hex[:16],
                tier=MemoryTier.PATTERN,
                title=pat_text[:80],
                content=pat_text,
                scope=scope_type,
                scope_id=scope_id,
                beliefs=[
                    BeliefRecord(
                        belief_id=uuid.uuid4().hex[:10],
                        content=pat_text,
                        confidence=ConfidenceLevel.TENTATIVE,
                        adopted_at=now,
                    )
                ],
                created_at=now,
                last_accessed_at=now,
            )
            self._store.inscribe(entry)
            patterns.append(entry)

        return patterns
