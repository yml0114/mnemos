"""
独立记忆世界 — MCP 服务接口

通过 MCP 协议暴露记忆系统能力，任何兼容 MCP 的 Agent 都可接入。
基于 mcp SDK 的 FastMCP 实现，支持 stdio transport。

暴露的工具:
  - mnemos: 统一记忆工具，通过 action 参数分发:
      remember  — 写入一条记忆
      recall    — 检索记忆（6路信号融合）
      revise    — 修正信念
      condense  — 触发记忆凝练
      stats     — 查看记忆统计
      touch     — 刷新衰减
      decay     — 批量衰减
      neglected — 即将遗忘的记忆
      profile   — 用户画像
      stage     — 渐进式上下文注入
"""

from __future__ import annotations

import json
import os
import sys
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


# ── Action 处理器 ─────────────────────────────────────────

def _do_remember(p: dict) -> str:
    content = p["content"]
    title = p.get("title", "")
    scope_type = p.get("scope_type", "tenant")
    scope_id = p.get("scope_id", "")
    tags = p.get("tags")
    entities = p.get("entities")
    related_to = p.get("related_to")

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


def _do_recall(p: dict) -> str:
    query = p["query"]
    keywords = p.get("keywords")
    entities = p.get("entities")
    tiers = p.get("tiers")
    scope_type = p.get("scope_type", "")
    scope_id = p.get("scope_id", "")
    after = p.get("after", "")
    before = p.get("before", "")
    max_results = p.get("max_results", 20)

    engine = _get_engine()

    scopes = []
    if scope_type and scope_id:
        scopes = [ContextScope(scope_type=ScopeType(scope_type), scope_id=scope_id)]

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


def _do_revise(p: dict) -> str:
    entry_id = p["entry_id"]
    old_belief_id = p["old_belief_id"]
    new_content = p["new_content"]
    source = p.get("source", "")

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
            "superseded_count": len([b for b in entry.beliefs if b.superseded_by is not None]),
        },
        ensure_ascii=False,
    )


def _do_condense(p: dict) -> str:
    from mnemos.condensation.alchemist import AlchemistCondenser

    store = _get_store()
    condenser = AlchemistCondenser(store)
    result = condenser.auto_condense(
        scope_type=ScopeType(p.get("scope_type", "tenant")),
        scope_id=p.get("scope_id", ""),
    )
    return json.dumps({"status": "condensed", **result}, ensure_ascii=False)


def _do_stats(_p: dict) -> str:
    store = _get_store()
    return json.dumps({"status": "ok", "stats": store.count()}, ensure_ascii=False, indent=2)


def _do_touch(p: dict) -> str:
    entry_id = p["entry_id"]
    tier = MemoryTier(p.get("tier", "impression"))
    store = _get_store()
    store.touch(entry_id, tier)
    return json.dumps({"status": "touched", "entry_id": entry_id}, ensure_ascii=False)


def _do_decay(p: dict) -> str:
    store = _get_store()
    affected = store.decay_stale(p.get("rate", 0.01))
    return json.dumps({"status": "decayed", "affected_entries": affected}, ensure_ascii=False)


def _do_neglected(p: dict) -> str:
    store = _get_store()
    entries = store.by_decay(p.get("min_decay", 0.0), p.get("max_decay", 0.3), p.get("limit", 20))
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


def _do_profile(p: dict) -> str:
    store = _get_store()
    from mnemos.profile import Mneme

    engine = Mneme(store)
    profile = engine.build(p.get("scope_id", ""))
    return json.dumps(
        {
            "status": "ok",
            "profile": {
                "preferences": profile.preferences,
                "tools": profile.tools,
                "projects": profile.projects,
                "static": profile.static,
                "dynamic": profile.dynamic,
                "summary": engine.summary(profile),
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def _do_stage(p: dict) -> str:
    engine = _get_engine()
    from mnemos.retrieval.stager import Stager

    q = MemoryQuery(query_text=p["query"])
    scope_type = p.get("scope_type", "tenant")
    scope_id = p.get("scope_id", "")
    if scope_type:
        q.scopes = [ContextScope(scope_type=ScopeType(scope_type), scope_id=scope_id or "default")]
    results = engine.search(q)
    stager = Stager(core_max=p.get("core_max", 3), context_max=p.get("context_max", 5))
    plan = stager.plan(results)

    return json.dumps(
        {
            "status": "ok",
            "core": [{"content": m.formatted, "resonance": round(m.resonance, 3)} for m in plan.core],
            "context": [{"content": m.formatted, "resonance": round(m.resonance, 3)} for m in plan.context],
            "archive_count": len(plan.archive),
            "estimated_tokens": plan.estimated_tokens,
            "baseline_tokens": plan.baseline_tokens,
            "reduction_pct": round(plan.reduction_pct * 100, 1),
            "system_prompt": stager.render_system(plan),
            "context_prompt": stager.render_context(plan),
        },
        ensure_ascii=False,
        indent=2,
    )


# ── 统一入口 ──────────────────────────────────────────────

_ACTIONS = {
    "remember": _do_remember,
    "recall": _do_recall,
    "revise": _do_revise,
    "condense": _do_condense,
    "stats": _do_stats,
    "touch": _do_touch,
    "decay": _do_decay,
    "neglected": _do_neglected,
    "profile": _do_profile,
    "stage": _do_stage,
}


@mcp.tool()
def mnemos(action: str, params: str = "{}") -> str:
    """记忆世界统一入口。通过 action 参数调用不同功能。

    action  — 操作名称，必填。可选值:
      remember  — 写入记忆。params: content(必填), title, scope_type, scope_id, tags, entities, related_to
      recall    — 检索记忆。params: query(必填), keywords, entities, tiers, scope_type, scope_id, after, before, max_results
      revise    — 修正信念。params: entry_id(必填), old_belief_id(必填), new_content(必填), source
      condense  — 触发凝练。params: scope_type, scope_id
      stats     — 记忆统计。无必填参数
      touch     — 刷新衰减。params: entry_id(必填), tier
      decay     — 批量衰减。params: rate
      neglected — 遗忘预警。params: min_decay, max_decay, limit
      profile   — 用户画像。params: scope_id
      stage     — 分层注入。params: query(必填), scope_type, scope_id, core_max, context_max

    params — JSON 字符串，传递给对应 action 的参数。

    示例:
      mnemos(action="remember", params='{"content":"用户偏好暗色主题","tags":["preference"]}')
      mnemos(action="recall", params='{"query":"用户喜欢什么"}')
      mnemos(action="stats")
      mnemos(action="profile")
    """
    handler = _ACTIONS.get(action)
    if not handler:
        return json.dumps(
            {"status": "error", "message": f"Unknown action: {action}. Available: {', '.join(_ACTIONS)}"},
            ensure_ascii=False,
        )
    try:
        p = json.loads(params) if params else {}
        return handler(p)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# ── 服务器入口 ───────────────────────────────────────────


def main() -> None:
    """MCP 服务器入口（通过 stdio 通信）"""
    store = _get_store()
    print(f"Mnemos server ready — {store.count()}", file=sys.stderr)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
