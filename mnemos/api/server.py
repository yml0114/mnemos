# -*- coding: utf-8 -*-
"""
Mnemos REST API — 完整实现
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.retrieval.resonance import ResonanceEngine
from mnemos.core.models import (
    ContextScope,
    EntityRef,
    MemoryEntry,
    MemoryQuery,
    MemoryTier,
    ScopeType,
)
from mnemos.sync.engine import SyncEngine
from mnemos.multimodal.engine import MultimodalEngine
from mnemos.healer.engine import HealerEngine
from mnemos.temporal_graph.engine import TemporalGraphEngine

try:
    from mnemos.viz.dashboard import _DASHBOARD_HTML
except Exception:
    _DASHBOARD_HTML = "<h1>Mnemos</h1><p>Dashboard not available</p>"


app = FastAPI(
    title="Mnemos API",
    description="独立记忆世界的 REST API — 支持 MCP 全部功能",
    version="7.15.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局单例 ─────────────────────────────────────────

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


# ── 健康检查 ─────────────────────────────────────────

@app.get("/health")
def health():
    """健康检查"""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── 记忆基本操作 ─────────────────────────────────────

class RememberRequest(BaseModel):
    content: str = Field(..., min_length=1)
    title: str | None = None
    scope_type: str = Field("tenant")
    scope_id: str = Field("")
    tags: list[str] | None = None
    entities: list[dict] | None = None
    related_to: list[str] | None = None


@app.post("/remember")
def remember(req: RememberRequest):
    store = _get_store()
    now = datetime.now(timezone.utc)
    entity_refs = [
        EntityRef(
            label=e.get("label", ""),
            entity_type=e.get("entity_type", "concept"),
            description=e.get("description", ""),
        )
        for e in (req.entities or [])
    ]
    entry = MemoryEntry(
        title=req.title or req.content[:80],
        content=req.content,
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType(req.scope_type),
        scope_id=req.scope_id,
        tags=req.tags or [],
        entities=entity_refs,
        related_ids=req.related_to or [],
        created_at=now,
        last_accessed_at=now,
    )
    entry_id = store.inscribe(entry)
    return {"status": "remembered", "entry_id": entry_id}


class RecallRequest(BaseModel):
    query: str = Field(..., min_length=1)
    keywords: list[str] | None = None
    entities: list[str] | None = None
    tiers: list[str] | None = None
    scope_type: str | None = None
    scope_id: str | None = None
    after: str | None = None
    before: str | None = None
    max_results: int = Field(20, ge=1, le=100)


@app.post("/recall")
def recall(req: RecallRequest):
    engine = _get_engine()
    scopes = []
    if req.scope_type and req.scope_id:
        scopes = [ContextScope(scope_type=ScopeType(req.scope_type), scope_id=req.scope_id)]
    tier_list = [MemoryTier(t) for t in req.tiers] if req.tiers else None
    dt_after = datetime.fromisoformat(req.after) if req.after else None
    dt_before = datetime.fromisoformat(req.before) if req.before else None
    q = MemoryQuery(
        query_text=req.query,
        keywords=req.keywords or [],
        entities=req.entities or [],
        tiers=tier_list or [],
        scopes=scopes,
        after=dt_after,
        before=dt_before,
        max_results=req.max_results,
    )
    results = engine.search(q)
    return {
        "query": req.query,
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
    }


class ReviseRequest(BaseModel):
    entry_id: str = Field(...)
    old_belief_id: str = Field(...)
    new_content: str = Field(...)
    source: str = Field("")


@app.post("/revise")
def revise(req: ReviseRequest):
    store = _get_store()
    entry = store.by_id(req.entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry {req.entry_id} not found")
    new_belief = entry.revise_belief(
        old_belief_id=req.old_belief_id,
        new_content=req.new_content,
        source=req.source,
    )
    store.revise(
        entry.entry_id,
        entry.tier,
        {"beliefs_json": json.dumps([b.model_dump(mode="json") for b in entry.beliefs], ensure_ascii=False)},
    )
    return {
        "status": "revised",
        "entry_id": entry.entry_id,
        "new_belief_id": new_belief.belief_id,
        "superseded_count": len([b for b in entry.beliefs if b.superseded_by is not None]),
    }


@app.post("/condense")
def condense(scope_type: str = Query("tenant"), scope_id: str = Query("")):
    from mnemos.condensation.alchemist import AlchemistCondenser
    store = _get_store()
    condenser = AlchemistCondenser(store)
    result = condenser.auto_condense(
        scope_type=ScopeType(scope_type),
        scope_id=scope_id,
    )
    return {"status": "condensed", **result}


@app.get("/stats")
def get_stats():
    store = _get_store()
    return {"status": "ok", "stats": store.count()}


class TouchRequest(BaseModel):
    entry_id: str = Field(...)
    tier: str = Field("impression")


@app.post("/touch")
def touch(req: TouchRequest):
    store = _get_store()
    store.touch(req.entry_id, MemoryTier(req.tier))
    return {"status": "touched", "entry_id": req.entry_id}


class DecayRequest(BaseModel):
    rate: float = Field(0.01, ge=0.0, le=1.0)


@app.post("/decay")
def decay(req: DecayRequest):
    store = _get_store()
    affected = store.decay_stale(req.rate)
    return {"status": "decayed", "affected_entries": affected}


class NeglectedRequest(BaseModel):
    min_decay: float = Field(0.0, ge=0.0)
    max_decay: float = Field(0.3, le=1.0)
    limit: int = Field(20, ge=1, le=100)


@app.post("/neglected")
def neglected(req: NeglectedRequest):
    store = _get_store()
    entries = store.by_decay(req.min_decay, req.max_decay, req.limit)
    return {
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
    }


class ProfileRequest(BaseModel):
    scope_id: str = Field("")


@app.post("/profile")
def profile(req: ProfileRequest):
    store = _get_store()
    from mnemos.profile import Mneme
    engine = Mneme(store)
    profile = engine.build(req.scope_id)
    return {
        "status": "ok",
        "profile": {
            "preferences": profile.preferences,
            "tools": profile.tools,
            "projects": profile.projects,
            "static": profile.static,
            "dynamic": profile.dynamic,
            "summary": engine.summary(profile),
        },
    }


class StageRequest(BaseModel):
    query: str = Field(...)
    scope_type: str = Query("tenant")
    scope_id: str = Query("")
    core_max: int = Field(3, ge=1, le=10)
    context_max: int = Field(5, ge=1, le=20)


@app.post("/stage")
def stage(req: StageRequest):
    engine = _get_engine()
    from mnemos.retrieval.stager import Stager
    q = MemoryQuery(query_text=req.query)
    if req.scope_type:
        q.scopes = [ContextScope(scope_type=ScopeType(req.scope_type), scope_id=req.scope_id or "default")]
    results = engine.search(q)
    stager = Stager(core_max=req.core_max, context_max=req.context_max)
    plan = stager.plan(results)
    return {
        "status": "ok",
        "core": [{"content": m.formatted, "resonance": round(m.resonance, 3)} for m in plan.core],
        "context": [{"content": m.formatted, "resonance": round(m.resonance, 3)} for m in plan.context],
        "archive_count": len(plan.archive),
        "estimated_tokens": plan.estimated_tokens,
        "baseline_tokens": plan.baseline_tokens,
        "reduction_pct": round(plan.reduction_pct * 100, 1),
        "system_prompt": stager.render_system(plan),
        "context_prompt": stager.render_context(plan),
    }


class ImportRequest(BaseModel):
    memories: list[dict] = Field(..., min_length=1)
    dry_run: bool = False


@app.post("/import")
def import_memories(req: ImportRequest):
    store = _get_store()
    now = datetime.now(timezone.utc)
    results = {"total": len(req.memories), "imported": 0, "skipped": 0, "errors": []}
    for i, mem in enumerate(req.memories):
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
            if not req.dry_run:
                store.inscribe(entry)
            results["imported"] += 1
        except Exception as e:
            results["errors"].append({"index": i, "error": str(e)})
    results["dry_run"] = req.dry_run
    return results


# ── 分布式同步 ───────────────────────────────────────

class SyncRequest(BaseModel):
    action: str = Field(..., description="push/pull/merge/resolve/conflicts/status")
    remote_db: str | None = None
    strategy: str | None = Field("lww")
    conflict_id: str | None = None
    resolution: str | None = Field("keep_local")
    scope_type: str | None = None
    scope_id: str | None = None


@app.post("/sync")
def sync(req: SyncRequest):
    sync_engine = _get_sync()
    try:
        if req.action == "push":
            result = sync_engine.push(scope_type=req.scope_type, scope_id=req.scope_id)
        elif req.action == "pull":
            result = sync_engine.pull(remote_db_path=req.remote_db or "")
        elif req.action == "merge":
            result = sync_engine.merge(remote_db_path=req.remote_db or "", strategy=req.strategy or "lww")
        elif req.action == "resolve":
            result = sync_engine.resolve(conflict_id=req.conflict_id or "", resolution=req.resolution or "keep_local")
        elif req.action == "conflicts":
            result = sync_engine.resolve_conflicts()
        else:
            result = sync_engine.status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


# ── 多模态记忆 ───────────────────────────────────────

class MultimodalRequest(BaseModel):
    action: str = Field(..., description="attach/get/search/search_by_type/update_summary/delete/stats")
    memory_id: str | None = None
    file_path: str | None = None
    media_type: str | None = None
    query: str | None = None
    limit: int = Field(10, ge=1, le=100)
    summary: str | None = None
    attachment_id: str | None = None


@app.post("/multimodal")
def multimodal(req: MultimodalRequest):
    mm = _get_multimodal()
    try:
        if req.action == "attach":
            result = mm.attach_media(memory_id=req.memory_id or "", file_path=req.file_path or "", media_type=req.media_type or "")
        elif req.action == "get":
            attachment = mm.get_attachment(req.attachment_id or "")
            result = attachment.model_dump(mode="json") if attachment else {"error": "not found"}
        elif req.action == "search":
            result = [a.model_dump(mode="json") for a in mm.search_by_summary(query=req.query or "", limit=req.limit)]
        elif req.action == "search_by_type":
            result = [a.model_dump(mode="json") for a in mm.search_by_type(media_type=req.media_type or "")]
        elif req.action == "update_summary":
            result = {"success": mm.update_summary(attachment_id=req.attachment_id or "", summary=req.summary or "")}
        elif req.action == "delete":
            result = {"success": mm.delete_attachment(req.attachment_id or "")}
        else:
            result = mm.stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


# ── 自修复 ───────────────────────────────────────────

class HealRequest(BaseModel):
    action: str = Field(..., description="scan/heal_all/list/dismiss/stats")
    limit: int = Field(50, ge=1, le=500)
    severity: str | None = None
    inconsistency_id: str | None = None
    include_healed: bool = False


@app.post("/heal")
def heal(req: HealRequest):
    healer = _get_healer()
    try:
        if req.action == "scan":
            issues = healer.scan()
            result = {"found": len(issues), "results": [i.to_dict() for i in issues]}
        elif req.action == "heal_all":
            result = healer.heal_all()
        elif req.action == "list":
            issues = healer.list_inconsistencies(severity=req.severity, limit=req.limit, include_healed=req.include_healed)
            result = {"found": len(issues), "results": [i.to_dict() for i in issues]}
        elif req.action == "dismiss":
            result = {"success": healer.dismiss(req.inconsistency_id or "")}
        else:
            result = healer.stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


# ── 时间线回溯 ───────────────────────────────────────

class TimelineRequest(BaseModel):
    action: str = Field(..., description="trace/graph/forks/merges/rollback/viz/stats")
    memory_id: str | None = None
    event_id: str | None = None
    target_event_id: str | None = None
    max_events: int = Field(200, ge=1, le=1000)
    since: str | None = None
    actor: str | None = None
    format: str = Field("d3")


@app.post("/timeline")
def timeline(req: TimelineRequest):
    tg = _get_temporal()
    try:
        if req.action == "trace":
            result = [e.to_dict() for e in tg.timeline(memory_id=req.memory_id or "", include_snapshots=False)]
        elif req.action == "graph":
            result = tg.graph(memory_id=req.memory_id, max_events=req.max_events)
        elif req.action == "forks":
            result = tg.detect_forks(since=req.since)
        elif req.action == "merges":
            result = tg.detect_merges(since=req.since)
        elif req.action == "rollback":
            success = tg.rollback_to(
                memory_id=req.memory_id or "",
                target_event_id=req.target_event_id or "",
                actor=req.actor or "user",
            )
            result = {"status": "rolled_back" if success else "failed"}
        elif req.action == "viz":
            if req.format == "dot":
                result = {"format": "dot", "content": tg.graphviz()}
            else:
                result = tg.graph(max_events=req.max_events)
        else:
            result = tg.stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


# ── 主入口 ───────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mnemos.api.server:app", host="0.0.0.0", port=int(os.environ.get("MNEMOS_PORT", 9730)), reload=False)

# ── Context Management ────────────────────────────────────────
try:
    from mnemos.context import SystemContextImpl
except ImportError:  # pragma: no cover
    SystemContextImpl = None  # type: ignore


_context: SystemContextImpl | None = None

def _get_context() -> SystemContextImpl:
    global _context
    if _context is None:
        if SystemContextImpl is None:
            raise RuntimeError("Context module not available")
        _context = SystemContextImpl(store=_get_store())
    return _context

class CheckpointData(BaseModel):
    checkpoint: dict[str, Any]

@app.get("/context/sources")
def list_context_sources():
    ctx = _get_context()
    return {"sources": ctx.list_sources()}

@app.post("/context/reconcile")
def context_reconcile():
    ctx = _get_context()
    messages = ctx.reconcile()
    return {
        "status": "ok",
        "mid_conversation_messages": [msg.to_system_prompt() for msg in messages],
    }

@app.post("/context/admit")
def context_admit():
    ctx = _get_context()
    ctx.admit()
    return {"status": "admitted"}

@app.post("/context/compact")
def context_compact():
    ctx = _get_context()
    epoch = ctx.compact()
    return {
        "status": "compacted",
        "epoch_id": epoch.epoch_id.hex,
        "started_at": epoch.started_at.isoformat(),
    }

@app.get("/context/state")
def context_state():
    ctx = _get_context()
    return {
        "sources": list(ctx._state.current_snapshot.keys()),
        "has_epoch": ctx._state.current_epoch is not None,
        "pending_updates": len(ctx._state.pending_updates),
    }

@app.post("/context/checkpoint")
def context_checkpoint():
    ctx = _get_context()
    data = ctx.checkpoint()
    return {"checkpoint": data}

@app.post("/context/restore")
def context_restore(req: CheckpointData):
    ctx = _get_context()
    ctx.restore(req.checkpoint)
    return {"status": "restored"}
