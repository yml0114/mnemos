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
      import    — 批量导入记忆
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
from mnemos.sync.engine import SyncEngine
from mnemos.multimodal.engine import MultimodalEngine
from mnemos.healer.engine import HealerEngine
from mnemos.temporal_graph.engine import TemporalGraphEngine

# ── FastMCP 实例 ──────────────────────────────────────────

mcp = FastMCP("mnemos")

# ── 全局单例 ─────────────────────────────────────────────

_store: PalimpsestStore | None = None
_engine: ResonanceEngine | None = None
_sync_engine: SyncEngine | None = None
_mm_engine: MultimodalEngine | None = None
_healer: HealerEngine | None = None
_tg_engine: TemporalGraphEngine | None = None


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


def _get_sync() -> SyncEngine:
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = SyncEngine(_get_store())
    return _sync_engine


def _get_multimodal() -> MultimodalEngine:
    global _mm_engine
    if _mm_engine is None:
        _mm_engine = MultimodalEngine(_get_store())
    return _mm_engine


def _get_healer() -> HealerEngine:
    global _healer
    if _healer is None:
        _healer = HealerEngine(_get_store())
    return _healer


def _get_temporal() -> TemporalGraphEngine:
    global _tg_engine
    if _tg_engine is None:
        _tg_engine = TemporalGraphEngine(_get_store())
    return _tg_engine


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

def _do_import(p: dict) -> str:
    """批量导入记忆。接收 memories 列表，逐条写入。

    params:
      memories — 记忆列表，每项包含:
        content(必填), title, scope_type, scope_id, tags, entities, related_to
      dry_run — 如果为 True，只验证不写入
    """
    memories = p.get("memories", [])
    if not memories:
        return json.dumps({"status": "error", "message": "memories list is empty"}, ensure_ascii=False)

    dry_run = p.get("dry_run", False)
    store = _get_store()
    now = datetime.now(timezone.utc)

    results = {"total": len(memories), "imported": 0, "skipped": 0, "errors": []}

    for i, mem in enumerate(memories):
        try:
            content = mem.get("content", "")
            if not content.strip():
                results["skipped"] += 1
                continue

            title = mem.get("title", "") or content[:80]
            scope_type = mem.get("scope_type", "tenant")
            scope_id = mem.get("scope_id", "")
            tags = mem.get("tags", [])
            entities_raw = mem.get("entities", [])
            related_to = mem.get("related_to", [])

            entity_refs = [
                EntityRef(
                    label=e.get("label", ""),
                    entity_type=e.get("entity_type", "concept"),
                    description=e.get("description", ""),
                )
                for e in entities_raw
            ]

            entry = MemoryEntry(
                title=title,
                content=content,
                tier=MemoryTier.IMPRESSION,
                scope=ScopeType(scope_type),
                scope_id=scope_id,
                tags=tags,
                entities=entity_refs,
                related_ids=related_to,
                created_at=now,
                last_accessed_at=now,
            )

            if dry_run:
                results["imported"] += 1
            else:
                entry_id = store.inscribe(entry)
                results["imported"] += 1

        except Exception as e:
            results["errors"].append({"index": i, "error": str(e)})

    results["dry_run"] = dry_run
    return json.dumps(results, ensure_ascii=False)


# ── 新功能: 分布式同步 ────────────────────────────────────


def _do_sync(p: dict) -> str:
    """分布式多进程记忆同步。

    params:
      action — 操作: push/pull/merge/resolve/status
      remote_db — 远程 SQLite 数据库路径 (push/pull/merge)
      strategy — 冲突消解策略: lww/keep_local/keep_remote
      record_id — 单条记录 ID (resolve)
    """
    sync = _get_sync()
    action = p.get("action", "status")
    try:
        if action == "push":
            result = sync.push(
                scope_type=p.get("scope_type"),
                scope_id=p.get("scope_id"),
            )
        elif action == "pull":
            result = sync.pull(
                remote_db_path=p.get("remote_db", ""),
            )
        elif action == "merge":
            result = sync.merge(
                remote_db_path=p.get("remote_db", ""),
                strategy=p.get("strategy", "lww"),
            )
        elif action == "resolve":
            # 解析冲突：手动指定保留策略
            result = sync.resolve(
                conflict_id=p.get("conflict_id", ""),
                resolution=p.get("resolution", "keep_local"),
            )
        elif action == "conflicts":
            result = sync.resolve_conflicts()
        else:
            result = sync.status()
    except Exception as e:
        result = {"status": "error", "message": str(e)}
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── 新功能: 多模态记忆 ────────────────────────────────────


def _do_multimodal(p: dict) -> str:
    """多模态记忆引擎（图片/音频摘要）。

    params:
      action — attach/search/search_by_type/search_img/stats
      memory_id — 关联的记忆 ID (attach)
      file_path — 文件路径 (attach)
      media_type — 媒体类型: image/audio/video/file/link (search_by_type)
      query — 文本检索查询 (search img)
      limit — 最大结果数
      summary — 更新摘要 (update_summary)
      attachment_id — 附件 ID (update_summary/delete)
    """
    mm = _get_multimodal()
    action = p.get("action", "stats")
    try:
        if action == "attach":
            result = mm.attach_media(
                memory_id=p.get("memory_id", ""),
                file_path=p.get("file_path", ""),
                media_type=p.get("media_type", ""),
            )
        elif action == "get":
            attachment = mm.get_attachment(p.get("attachment_id", ""))
            result = attachment.model_dump(mode="json") if attachment else {"error": "not found"}
        elif action == "search":
            result = [
                a.model_dump(mode="json")
                for a in mm.search_by_summary(
                    query=p.get("query", ""),
                    limit=p.get("limit", 10),
                )
            ]
        elif action == "search_by_type":
            result = [
                a.model_dump(mode="json")
                for a in mm.search_by_type(p.get("media_type", ""))
            ]
        elif action == "update_summary":
            result = {"success": mm.update_summary(
                attachment_id=p.get("attachment_id", ""),
                summary=p.get("summary", ""),
            )}
        elif action == "delete":
            result = {"success": mm.delete_attachment(p.get("attachment_id", ""))}
        else:
            result = mm.stats()
    except Exception as e:
        result = {"status": "error", "message": str(e)}
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── 新功能: 自修复 ────────────────────────────────────────


def _do_heal(p: dict) -> str:
    """自修复记忆引擎 — 不一致性检测与自动修复。

    params:
      action — scan/heal_all/list/dismiss/stats
      limit — 最大结果数 (list)
      min_severity — 最低严重等级 (list)
      inconsistency_id — 指定 ID (dismiss)
    """
    healer = _get_healer()
    action = p.get("action", "stats")
    try:
        if action == "scan":
            issues = healer.scan()
            result = {
                "found": len(issues),
                "results": [i.to_dict() for i in issues],
            }
        elif action == "heal_all":
            result = healer.heal_all()
        elif action == "list":
            issues = healer.list_inconsistencies(
                severity=p.get("severity"),
                limit=p.get("limit", 50),
                include_healed=p.get("include_healed", False),
            )
            result = {
                "found": len(issues),
                "results": [i.to_dict() for i in issues],
            }
        elif action == "dismiss":
            result = {"success": healer.dismiss(p.get("inconsistency_id", ""))}
        else:
            result = healer.stats()
    except Exception as e:
        result = {"status": "error", "message": str(e)}
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── 新功能: 时间线回溯 ─────────────────────────────────────


def _do_timeline(p: dict) -> str:
    """时间线回溯 — 记忆演化图谱与因果追踪。

    params:
      action — trace/graph/forks/merges/rollback/stats/viz
      memory_id — 追溯的记忆 ID (trace/rollback)
      event_id — 事件 ID (rollback)
      target_event_id — 回滚目标事件 (rollback)
      max_events — 最大事件数 (graph/viz)
      since — 起始时间 (forks/merges)
      actor — 操作者 (rollback)
      format — 格式: d3/dot/json (viz)
    """
    tg = _get_temporal()
    action = p.get("action", "stats")
    try:
        if action == "trace":
            result = [e.to_dict() for e in tg.timeline(
                memory_id=p.get("memory_id", ""),
                include_snapshots=p.get("include_snapshots", False),
            )]
        elif action == "graph":
            result = tg.graph(
                memory_id=p.get("memory_id"),
                max_events=p.get("max_events", 200),
            )
        elif action == "forks":
            result = tg.detect_forks(since=p.get("since"))
        elif action == "merges":
            result = tg.detect_merges(since=p.get("since"))
        elif action == "rollback":
            success = tg.rollback_to(
                memory_id=p.get("memory_id", ""),
                target_event_id=p.get("target_event_id", ""),
                actor=p.get("actor", "user"),
            )
            result = {"status": "rolled_back" if success else "failed"}
        elif action == "viz":
            fmt = p.get("format", "d3")
            if fmt == "dot":
                result = {"format": "dot", "content": tg.graphviz()}
            else:
                result = tg.graph(max_events=p.get("max_events", 100))
        else:
            result = tg.stats()
    except Exception as e:
        result = {"status": "error", "message": str(e)}
    return json.dumps(result, ensure_ascii=False, indent=2)



def _do_conversation_append(p: dict) -> str:
    """追加会话消息。创建会话（如果不存在）并追加一条消息（含多个片段）。

    params:
      session_id — 会话标识（同一任务使用相同 ID）
      role — 消息角色: user/assistant/tool
      agent_id — 代理标识（可为空）
      parts — 片段列表，每项: {content, media_type, tokens, metadata{}}
      tokens — 消息总 token 数（可选）
      finish_reason — 结束原因（可选）
    """
    session_id = p["session_id"]
    role = p["role"]
    agent_id = p.get("agent_id", "")
    parts = p["parts"]
    tokens = p.get("tokens", 0)
    finish_reason = p.get("finish_reason")

    store = _get_store()
    msg_id = store.append_message(
        session_id=session_id,
        role=role,
        agent_id=agent_id,
        parts=parts,
        tokens=tokens,
        finish_reason=finish_reason,
    )
    return json.dumps({"status": "appended", "message_id": msg_id}, ensure_ascii=False)

def _do_conversation_search(p: dict) -> str:
    """全文搜索会话片段。基于 FTS5 实现，支持短语匹配、BM25 排序。

    params:
      query — 搜索语句（必需）
      scope — 搜索范围: project/session（默认 project）
      project_id — 项目标识（当 scope=project 时）
      session_id — 会话标识（当 scope=session 时）
      limit — 最大返回数（默认 50）
    """
    query = p["query"]
    scope = p.get("scope", "project")
    project_id = p.get("project_id")
    session_id = p.get("session_id")
    limit = p.get("limit", 50)

    store = _get_store()
    hits = store.conversation_search(
        query=query,
        scope=scope,
        project_id=project_id,
        session_id=session_id,
        limit=limit,
    )
    return json.dumps({"status": "ok", "hits": hits}, ensure_ascii=False)

def _do_link_message_entities(p: dict) -> str:
    """将会话片段与实体图谱关联。

    params:
      part_id — 片段标识
      entity_id — 实体标识
      relevance — 相关度（可选，默认 0.0）
    """
    part_id = p["part_id"]
    entity_id = p["entity_id"]
    relevance = p.get("relevance", 0.0)

    store = _get_store()
    store.link_message_entities(part_id, entity_id, relevance)
    return json.dumps({"status": "linked"}, ensure_ascii=False)

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
    "import": _do_import,
    "sync": _do_sync,
    "multimodal": _do_multimodal,
    "heal": _do_heal,
    "timeline": _do_timeline,
    "conversation_append": _do_conversation_append,
    "conversation_search": _do_conversation_search,
    "link_message_entities": _do_link_message_entities,
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
      import    — 批量导入记忆。params: memories(必填, 记忆列表[{content,title,scope_type,scope_id,tags,entities,related_to}]), dry_run(选填,默认false)
      sync      — 分布式同步。params: action(push/pull/merge/resolve/conflicts/status), remote_db, strategy, scope_type, scope_id, conflict_id, resolution
      multimodal — 多模态记忆。params: action(attach/get/search/search_by_type/update_summary/delete/stats), file_path, media_type, query, memory_id, attachment_id, summary
      heal      — 自修复。params: action(scan/heal_all/list/dismiss/stats), limit, severity, include_healed
      timeline  — 时间线回溯。params: action(record/timeline/graph/forks/merges/rollback/dot/stats), memory_id, event_type, tier, before, after, changed_fields, parent_event, actor, summary, since, target_event_id, max_events

    params — JSON 字符串，传递给对应 action 的参数。

    示例:
      mnemos(action="remember", params='{"content":"用户偏好暗色主题","tags":["preference"]}')
      mnemos(action="recall", params='{"query":"用户喜欢什么"}')
      mnemos(action="stats")
      mnemos(action="profile")
      mnemos(action="import", params='{"memories":[{"content":"用户喜欢Python","title":"偏好","tags":["preference"]}]}')
      mnemos(action="sync", params='{"action":"status"}')
      mnemos(action="sync", params='{"action":"pull","remote_db":"/path/to/remote.db"}')
      mnemos(action="heal", params='{"action":"scan"}')
      mnemos(action="timeline", params='{"action":"graph","memory_id":"xxx","max_events":50}')
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
