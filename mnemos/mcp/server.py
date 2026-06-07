"""
独立记忆世界 — MCP 服务接口

通过 MCP 协议暴露记忆系统能力，任何兼容 MCP 的 Agent 都可接入。
基于 mcp SDK 的 FastMCP 实现，支持 stdio transport。

暴露的工具:
  - mnemos_remember:  写入一条记忆
  - mnemos_recall:    检索记忆（多信号融合）
  - mnemos_forget:    软删除记忆
  - mnemos_revise:    修正信念
  - mnemos_condense:  触发记忆凝练
  - mnemos_stats:     查看记忆统计
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from mnemos.core.models import (
    ContextScope,
    EntityRef,
    MemoryEntry,
    MemoryQuery,
    MemoryTier,
    ScopeType,
)
from mnemos.retrieval.resonance import ResonanceEngine
from mnemos.storage.palimpsest import PalimpsestStore

# ── FastMCP 实例 ──────────────────────────────────────────

mcp = FastMCP("mnemos")

# ── 全局单例 ─────────────────────────────────────────────

_store: PalimpsestStore | None = None
_engine: ResonanceEngine | None = None


def _get_store() -> PalimpsestStore:
    global _store
    if _store is None:
        db_path = os.environ.get("MNEMOS_DB_PATH", "mnemos.db")
        _store = PalimpsestStore(db_path)
        _store.connect()
    return _store


def _get_engine() -> ResonanceEngine:
    global _engine
    if _engine is None:
        _engine = ResonanceEngine(_get_store())
    return _engine


# ── 工具定义 ─────────────────────────────────────────────


@mcp.tool()
def mnemos_remember(
    content: str,
    title: str = "",
    scope_type: str = "tenant",
    scope_id: str = "",
    tags: list[str] | None = None,
    entities: list[dict[str, str]] | None = None,
    related_to: list[str] | None = None,
) -> str:
    """将一条记忆写入记忆世界。记忆会自动归类到印象层(impression)，
    后续可通过凝练升级为模式(pattern)或原则(principle)。

    Args:
        content: 要记住的内容
        title: 简短标题（可选，默认取内容前80字）
        scope_type: 记忆归属范围(universe/tenant/persona/session)，默认 tenant
        scope_id: 范围标识（用户ID/Agent ID/Session ID）
        tags: 标签列表
        entities: 关联实体列表，每项含 label/entity_type/description
        related_to: 关联的记忆ID列表
    """
    store = _get_store()
    now = datetime.now(timezone.utc)

    entity_refs = [
        EntityRef(
            label=e.get("label", ""),
            entity_type=e.get("entity_type", "concept"),
            description=e.get("description", ""),
        )
        for e in (entities or [])
    ]

    entry = MemoryEntry(
        title=title or content[:80],
        content=content,
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType(scope_type),
        scope_id=scope_id,
        tags=tags or [],
        entities=entity_refs,
        related_ids=related_to or [],
        created_at=now,
        last_accessed_at=now,
    )

    entry_id = store.inscribe(entry)
    return json.dumps({"status": "remembered", "entry_id": entry_id}, ensure_ascii=False)


@mcp.tool()
def mnemos_recall(
    query: str,
    keywords: list[str] | None = None,
    entities: list[str] | None = None,
    tiers: list[str] | None = None,
    scope_type: str = "",
    scope_id: str = "",
    after: str = "",
    before: str = "",
    max_results: int = 20,
) -> str:
    """从记忆世界中检索记忆。支持语义搜索、关键词过滤、实体关联、
    时间范围和范围过滤。多信号融合排序。

    Args:
        query: 搜索查询文本
        keywords: 关键词列表
        entities: 限定实体标签
        tiers: 限定记忆层次(impression/pattern/principle)
        scope_type: 范围类型(universe/tenant/persona/session)
        scope_id: 范围标识
        after: 起始时间 ISO 格式
        before: 结束时间 ISO 格式
        max_results: 最大返回数量，默认20
    """
    engine = _get_engine()

    scopes = []
    if scope_type and scope_id:
        scopes = [
            ContextScope(
                scope_type=ScopeType(scope_type),
                scope_id=scope_id,
            )
        ]

    tier_list = [MemoryTier(t) for t in tiers] if tiers else None

    dt_after = datetime.fromisoformat(after) if after else None
    dt_before = datetime.fromisoformat(before) if before else None

    q = MemoryQuery(
        query_text=query,
        keywords=keywords or [],
        entities=entities or [],
        tiers=tier_list or [],
        scopes=scopes,
        after=dt_after,
        before=dt_before,
        max_results=max_results,
    )

    results = engine.search(q)
    return json.dumps(
        {
            "query": query,
            "found": len(results),
            "results": [
                {
                    "entry_id": r.entry.entry_id,
                    "title": r.entry.title,
                    "content": r.entry.content[:300],
                    "tier": r.entry.tier.value,
                    "resonance": round(r.resonance_score, 4),
                    "signals": r.signal_breakdown,
                    "entities": [e.label for e in r.entry.entities],
                    "tags": r.entry.tags,
                    "created_at": r.entry.created_at.isoformat(),
                }
                for r in results
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def mnemos_revise(
    entry_id: str,
    old_belief_id: str,
    new_content: str,
    source: str = "",
) -> str:
    """修正记忆中的信念。旧信念不会被删除，作为历史版本保留。

    Args:
        entry_id: 要修正的记忆ID
        old_belief_id: 被修正的旧信念ID
        new_content: 修正后的信念内容
        source: 修正来源（Agent名/对话ID）
    """
    store = _get_store()
    entry = store.by_id(entry_id)
    if entry is None:
        return json.dumps({"status": "error", "message": f"Entry {entry_id} not found"}, ensure_ascii=False)

    new_belief = entry.revise_belief(
        old_belief_id=old_belief_id,
        new_content=new_content,
        source=source,
    )

    store.revise(
        entry.entry_id,
        entry.tier,
        {"beliefs_json": json.dumps(
            [b.model_dump(mode="json") for b in entry.beliefs],
            ensure_ascii=False,
        )},
    )

    return json.dumps(
        {
            "status": "revised",
            "entry_id": entry.entry_id,
            "new_belief_id": new_belief.belief_id,
            "superseded_count": len(
                [b for b in entry.beliefs if b.superseded_by is not None]
            ),
        },
        ensure_ascii=False,
    )


@mcp.tool()
def mnemos_condense(
    scope_type: str = "tenant",
    scope_id: str = "",
) -> str:
    """触发记忆凝练：将印象蒸馏为模式，或将模式结晶为原则。

    Args:
        scope_type: 范围类型(universe/tenant/persona/session)
        scope_id: 范围标识
    """
    from mnemos.condensation.alchemist import AlchemistCondenser

    store = _get_store()
    condenser = AlchemistCondenser(store)
    result = condenser.auto_condense(
        scope_type=ScopeType(scope_type),
        scope_id=scope_id,
    )
    return json.dumps({"status": "condensed", **result}, ensure_ascii=False)


@mcp.tool()
def mnemos_stats() -> str:
    """查看记忆世界统计信息。"""
    store = _get_store()
    return json.dumps({"status": "ok", "stats": store.count()}, ensure_ascii=False, indent=2)


@mcp.tool()
def mnemos_touch(
    entry_id: str,
    tier: str = "impression",
) -> str:
    """标记一条记忆为被访问，刷新衰减并增加访问计数。

    Args:
        entry_id: 记忆ID
        tier: 记忆层次(impression/pattern/principle)
    """
    from mnemos.core.models import MemoryTier
    store = _get_store()
    tier_enum = MemoryTier(tier)
    store.touch(entry_id, tier_enum)
    return json.dumps({"status": "touched", "entry_id": entry_id}, ensure_ascii=False)


@mcp.tool()
def mnemos_decay(
    rate: float = 0.01,
) -> str:
    """对长期未访问的记忆施加衰减。衰减归零的记忆将被自动清除。

    Args:
        rate: 每次衰减量（默认0.01）
    """
    store = _get_store()
    affected = store.decay_stale(rate)
    return json.dumps({"status": "decayed", "affected_entries": affected}, ensure_ascii=False)


@mcp.tool()
def mnemos_neglected(
    min_decay: float = 0.0,
    max_decay: float = 0.3,
    limit: int = 20,
) -> str:
    """检索衰减严重、即将被遗忘的记忆，可用于复习或决策是否保留。

    Args:
        min_decay: 最小衰减值（默认0.0）
        max_decay: 最大衰减值（默认0.3）
        limit: 最大返回数量（默认20）
    """
    store = _get_store()
    entries = store.by_decay(min_decay, max_decay, limit)
    return json.dumps(
        {
            "found": len(entries),
            "results": [
                {
                    "entry_id": e.entry_id,
                    "title": e.title,
                    "tier": e.tier.value,
                    "decay": e.decay_factor,
                    "hits": e.access_count,
                    "content": e.content[:200],
                    "last_accessed_at": e.last_accessed_at.isoformat(),
                }
                for e in entries
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


# ── 服务器入口 ───────────────────────────────────────────


def main() -> None:
    """MCP 服务器入口（通过 stdio 通信）"""
    # 初始化 store 以打印就绪信息
    store = _get_store()
    import sys
    print(f"Mnemos server ready — {store.count()}", file=sys.stderr)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
