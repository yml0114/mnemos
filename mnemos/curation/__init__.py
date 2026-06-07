"""
记忆去重引擎 — Curator（策展人）

设计理念:
  每次写入记忆前检测是否与已有记忆高度重复，
  避免记忆膨胀和检索噪音。类似 mem0 的 cosine 去重，
  但不依赖向量嵌入（默认用 Jaccard + 编辑距离）。

策略:
  1. Jaccard 相似度（快速筛）：词集合重叠率 > 0.7 → 疑似重复
  2. 编辑距离（精确判）：归一化编辑距离 < 0.3 → 确认重复
  3. 语义合并（可选）：LLM 驱动的两段合并
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from mnemos.core.models import MemoryEntry
from mnemos.storage.palimpsest import PalimpsestStore


@dataclass
class DedupResult:
    """去重检测结果"""
    is_duplicate: bool
    score: float  # 重复程度 0-1，越高越重复
    matched_entry: MemoryEntry | None = None
    strategy: str = "none"  # jaccard, edit, semantic
    suggestion: str = ""    # 建议操作: skip, merge, append


class Curator:
    """
    记忆策展人 — 去重 + 合并。

    使用示例:
        curator = Curator(store)
        result = curator.check(new_entry)
        if result.is_duplicate:
            if result.suggestion == "merge":
                curator.merge(new_entry, result.matched_entry)
    """

    # 阈值
    JACCARD_THRESHOLD = 0.5     # Jaccard > 此值进入编辑距离检查
    EDIT_THRESHOLD = 0.35       # 归一化编辑距离 < 此值判定为重复
    HARD_DUP_THRESHOLD = 0.15   # < 此值几乎完全相同

    # 分词
    _token_pattern = re.compile(r'[\u4e00-\u9fff]+|[a-zA-Z]+')

    def __init__(self, store: PalimpsestStore):
        self._store = store

    def check(self, entry: MemoryEntry, scope_only: bool = True) -> DedupResult:
        """
        检查一条新记忆是否与已有记忆重复。

        Args:
            entry: 待写入的记忆
            scope_only: 是否只检查同 scope 内的记忆
        """
        # 候选召回：同 scope + FTS 搜索
        if scope_only:
            candidates = self._store.by_scope(
                entry.scope, entry.scope_id, limit=30
            )
        else:
            candidates = []

        # FTS 补充
        fts_hits = self._store.fts(entry.title[:50], limit=10)
        for hit in fts_hits:
            if hit.entry_id not in {c.entry_id for c in candidates}:
                candidates.append(hit)

        # 逐条比对
        best_match = None
        best_score = 0.0
        best_strategy = "none"

        for candidate in candidates:
            # 跳过自己
            if candidate.entry_id == entry.entry_id:
                continue

            # 策略 1: Jaccard 快速筛
            jac = self._jaccard(entry.content, candidate.content)
            if jac < self.JACCARD_THRESHOLD:
                continue

            # 策略 2: 编辑距离精确判
            edit = self._normalized_edit(entry.content, candidate.content)
            dup_score = 1.0 - edit  # 编辑距离越小 → 重复得分越高

            if dup_score > best_score:
                best_score = dup_score
                best_match = candidate
                best_strategy = "edit" if edit < self.EDIT_THRESHOLD else "jaccard"

        if best_match is None or best_score < 0.5:
            return DedupResult(is_duplicate=False, score=best_score)

        # 判定
        if best_score > (1 - self.HARD_DUP_THRESHOLD):  # > 0.85
            return DedupResult(
                is_duplicate=True,
                score=best_score,
                matched_entry=best_match,
                strategy=best_strategy,
                suggestion="skip",  # 几乎相同，跳过
            )
        elif best_score > (1 - self.EDIT_THRESHOLD):  # > 0.65
            return DedupResult(
                is_duplicate=True,
                score=best_score,
                matched_entry=best_match,
                strategy=best_strategy,
                suggestion="merge",  # 内容相似，合并
            )

        return DedupResult(is_duplicate=False, score=best_score)

    def merge(
        self, new_entry: MemoryEntry, existing: MemoryEntry
    ) -> MemoryEntry:
        """
        合并两条相似记忆：保留旧记忆，追加新信息，关联起来。
        不会删除旧记忆。
        """
        # 新记忆关联到旧记忆
        if existing.entry_id not in new_entry.related_ids:
            new_entry.related_ids.append(existing.entry_id)

        # 合并标签
        merged_tags = list(set(existing.tags + new_entry.tags))

        # 更新旧记忆的标签和关联
        self._store.revise(
            existing.entry_id,
            existing.tier,
            {
                "tags_json": json.dumps(merged_tags, ensure_ascii=False),
                "related_json": json.dumps(
                    list(set(existing.related_ids + [new_entry.entry_id])),
                    ensure_ascii=False,
                ),
            },
        )

        new_entry.tags = merged_tags
        return new_entry

    def smart_inscribe(self, entry: MemoryEntry) -> dict[str, Any]:
        """
        智能写入：先检查重复，再决定写入策略。

        返回 {"action": "inserted|skipped|merged", "entry_id": ..., "dup_score": ...}
        """
        result = self.check(entry)

        if result.is_duplicate and result.suggestion == "skip":
            return {
                "action": "skipped",
                "entry_id": entry.entry_id,
                "dup_score": result.score,
                "matched_id": result.matched_entry.entry_id if result.matched_entry else None,
            }

        if result.is_duplicate and result.suggestion == "merge":
            if result.matched_entry:
                entry = self.merge(entry, result.matched_entry)

        entry_id = self._store.inscribe(entry)
        return {
            "action": "merged" if result.is_duplicate else "inserted",
            "entry_id": entry_id,
            "dup_score": result.score,
            "matched_id": result.matched_entry.entry_id if result.matched_entry else None,
        }

    # ── 相似度算法 ──────────────────────────────────

    def _tokenize(self, text: str) -> set[str]:
        """分词"""
        return set(self._token_pattern.findall(text.lower()))

    def _jaccard(self, a: str, b: str) -> float:
        """Jaccard 相似度"""
        set_a = self._tokenize(a)
        set_b = self._tokenize(b)
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)

    def _normalized_edit(self, a: str, b: str) -> float:
        """归一化编辑距离 (Levenshtein)"""
        m, n = len(a), len(b)
        if max(m, n) == 0:
            return 0.0

        # 取前 500 字符做精确计算，避免长文本性能问题
        a = a[:500]
        b = b[:500]
        m, n = len(a), len(b)

        # 滚动数组优化
        prev = list(range(n + 1))
        curr = [0] * (n + 1)

        for i in range(1, m + 1):
            curr[0] = i
            for j in range(1, n + 1):
                cost = 0 if a[i-1] == b[j-1] else 1
                curr[j] = min(
                    prev[j] + 1,        # 删除
                    curr[j-1] + 1,      # 插入
                    prev[j-1] + cost,   # 替换
                )
            prev, curr = curr, prev

        return prev[n] / max(m, n)
